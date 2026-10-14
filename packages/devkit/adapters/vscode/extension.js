"use strict";

// Thin adapter: shells out to `devin-devkit` and renders the result — no
// install/update logic is reimplemented here. Read-only by construction:
// the CLI's mutating apply/force switches are never passed — every plan
// shown is a dry run.

const vscode = require("vscode");
const cp = require("child_process");
// Shared Restricted-Mode-safe executable resolver — byte-identical copy of
// devin-powerups adapters/shared/safe-executable.cjs (lockstep enforced by
// config-restricted-check). On Windows, CreateProcess searches cwd before
// PATH: spawn only the absolute path this returns.
const { resolveSafeExecutable } = require("./safe-executable.cjs");

let statusBar;
let statusSeq = 0; // monotonic — a slow check must not overwrite a newer verdict
let compatWarned = false;

// Contract with the CLI JSON payloads — keep in sync with the
// "devin-devkit-cli" range in package.json (cli-contract.test.js asserts it).
const COMPATIBLE_CLI = { min: [0, 1], maxExclusive: [0, 2] };
const pkgRange = () =>
  `>=${COMPATIBLE_CLI.min.join(".")}.0,<${COMPATIBLE_CLI.maxExclusive.join(".")}.0`;

// "Cannot update here" action kinds: the updater emits blocked,
// environment-blocked and unsupported — all attention, never current.
// not-installed/unmanaged carry no verdict and don't count.
const GATED_ACTIONS = new Set(["blocked", "environment-blocked", "unsupported"]);

// First workspace folder, when one is open — used only to bound
// resolveSafeExecutable's inside-workspace rejection, not as spawn cwd.
function workspaceDir() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri.fsPath : null;
}

// Resolves {code, stdout, stderr}; never throws on non-zero exit —
// `install <p> --json` exits 2 on a blocked plan: a renderable result.
function runDevkit(args) {
  const exe = vscode.workspace.getConfiguration("devinDevkit").get("executable", "devin-devkit");
  const spec = resolveSafeExecutable(exe, {
    workspaceDir: workspaceDir(),
    trusted: vscode.workspace.isTrusted,
    npmPackage: null,
  });
  return new Promise((resolve, reject) => {
    if (!spec) return reject(new Error(
      "devin-devkit not found on PATH. Install it (uv tool install devin-devkit) " +
      "or set devinDevkit.executable."));
    cp.execFile(spec.file, spec.argv.concat(args), { timeout: 120000, maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && err.killed) return reject(new Error("devin-devkit timed out after 120s"));
      if (err && err.code === "ENOENT") return reject(new Error(
        "devin-devkit not found on PATH. Install it (uv tool install devin-devkit) " +
        "or set devinDevkit.executable."));
      resolve({ code: err ? err.code : 0, stdout, stderr });
    });
  });
}

const parseVersion = (text) => {
  const m = /(\d+)\.(\d+)\.(\d+)/.exec(String(text || ""));
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
};

// "compatible" | "too-old" | "too-new" | "unknown"
function cliCompatStatus(version) {
  const v = Array.isArray(version) ? version : parseVersion(version);
  if (!v) return "unknown";
  const [a, b] = COMPATIBLE_CLI.min, [c, d] = COMPATIBLE_CLI.maxExclusive;
  if (v[0] < a || (v[0] === a && v[1] < b)) return "too-old";
  if (v[0] > c || (v[0] === c && v[1] >= d)) return "too-new";
  return "compatible";
}

// Warn once when the installed CLI is detectably out of range. Older CLIs
// lack --version (exit 2): that stays "unknown" and silent — never blocks.
async function checkCliCompat() {
  if (compatWarned) return;
  compatWarned = true;
  try {
    const { code, stdout } = await runDevkit(["--version"]);
    const s = code === 0 ? cliCompatStatus(stdout) : "unknown";
    if (s === "too-old" || s === "too-new") {
      vscode.window.showWarningMessage(`devin-devkit ${stdout.trim()} is outside the ` +
        `supported range ${pkgRange()} — the extension may misread this CLI.`);
    }
  } catch { /* undetectable — never block */ }
}

// `update --json` prints a trailing "Dry run only." note after the JSON —
// extract the object leniently instead of failing the parse.
function extractJson(stdout) {
  const start = stdout.indexOf("{"), end = stdout.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("devin-devkit did not return JSON");
  return JSON.parse(stdout.slice(start, end + 1));
}

// Non-zero exit + no JSON = the CLI failed before planning — surface stderr.
function requirePayload(code, stdout, stderr, what) {
  if (code !== 0 && !String(stdout).trim()) throw new Error(
    `devin-devkit ${what} exited ${code}: ${String(stderr).trim() || "no output"}`);
}

const countActions = (plan, action) =>
  ((plan && plan.actions) || []).filter((a) => a && a.action === action).length;
const countGated = (plan) =>
  ((plan && plan.actions) || []).filter((a) => a && GATED_ACTIONS.has(a.action)).length;

function statusBadge(plan) {
  const updates = countActions(plan, "update");
  const gated = countGated(plan);
  const warn = new vscode.ThemeColor("statusBarItem.warningBackground");
  if (updates > 0) return { text: `$(cloud-download) devkit: ${updates} update${updates === 1 ? "" : "s"}`, bg: warn };
  if (gated > 0) return { text: `$(warning) devkit: ${gated} blocked`, bg: warn };
  return { text: "$(pass) devkit: current", bg: undefined };
}

const render = (text, tooltip, bg) => { // bg must be reset, not left stale
  statusBar.text = text;
  statusBar.tooltip = tooltip;
  statusBar.backgroundColor = bg;
  statusBar.show();
};

async function status() {
  const seq = ++statusSeq;
  render("$(sync~spin) devkit: checking", "devin-devkit outdated --json");
  try {
    const { code, stdout, stderr } = await runDevkit(["outdated", "--json"]);
    requirePayload(code, stdout, stderr, "outdated");
    const plan = extractJson(stdout);
    if (seq !== statusSeq) return plan;
    const badge = statusBadge(plan);
    render(badge.text,
      `devin-devkit — registry v${plan.registry_version || "?"}; ` +
      `${countActions(plan, "update")} update(s), ${countGated(plan)} blocked, ` +
      `${countActions(plan, "current")} current`, badge.bg);
    return plan;
  } catch (e) {
    if (seq !== statusSeq) return null;
    render("$(error) devkit: unavailable", e.message);
    vscode.window.showErrorMessage(e.message);
    return null;
  }
}

async function showDoc(language, content) {
  const doc = await vscode.workspace.openTextDocument({ language });
  const editor = await vscode.window.showTextDocument(doc, { preview: true });
  await editor.edit((b) => b.insert(new vscode.Position(0, 0), content));
}

// stderr can carry the newer-registry hint — keep both streams so a stale
// bundled catalog can't look identical to a current one.
const joinStreams = (stdout, stderr) =>
  [String(stdout).trimEnd(), String(stderr).trim()].filter(Boolean).join("\n\n");

async function runTextCommand(args) {
  const { code, stdout, stderr } = await runDevkit(args);
  if (code !== 0 && !stdout) {
    return void vscode.window.showErrorMessage(`devin-devkit ${args[0]} exited ${code}: ${stderr}`);
  }
  await showDoc("plaintext", joinStreams(stdout, stderr) || "(no output)");
}

const profiles = () => runTextCommand(["profiles"]);
const listTools = () => runTextCommand(["list"]);

const parseProfileNames = (text) =>
  text.split("\n").map((l) => /^([A-Za-z0-9_-]+):/.exec(l)).filter(Boolean).map((m) => m[1]);

async function previewPlan(args, what) {
  const { code, stdout, stderr } = await runDevkit(args);
  try {
    requirePayload(code, stdout, stderr, what);
    const plan = extractJson(stdout);
    if ((plan.errors || []).length) vscode.window.showWarningMessage(
      `devin-devkit: ${what} plan has ${plan.errors.length} blocking error(s) — see the plan.`);
    await showDoc("json", JSON.stringify(plan, null, 2));
  } catch (e) {
    vscode.window.showErrorMessage(e.message);
  }
}

async function previewInstall() {
  const { stdout } = await runDevkit(["profiles"]);
  const names = parseProfileNames(stdout);
  if (!names.length) return vscode.window.showErrorMessage("devin-devkit profiles: no profiles found");
  const picked = await vscode.window.showQuickPick(names, {
    placeHolder: "Profile to preview (dry run only)" });
  if (picked) await previewPlan(["install", picked, "--json"], `install ${picked}`);
}

const previewUpdate = () => previewPlan(["update", "--json"], "update");

function activate(context) {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusBar.command = "devin-devkit.status";
  render("$(tools) devkit", "Click to check for outdated Devin tools");
  const cmds = {
    "devin-devkit.status": status, "devin-devkit.profiles": profiles,
    "devin-devkit.list": listTools, "devin-devkit.previewInstall": previewInstall,
    "devin-devkit.previewUpdate": previewUpdate,
  };
  context.subscriptions.push(statusBar,
    ...Object.entries(cmds).map(([id, fn]) => vscode.commands.registerCommand(id, fn)));
  checkCliCompat();
  if (vscode.workspace.getConfiguration("devinDevkit").get("checkOnStartup", false)) status();
}

function deactivate() {}

module.exports = { activate, deactivate };
// Test-only surface — pure internals reachable without the editor.
module.exports.__internals__ = {
  COMPATIBLE_CLI, GATED_ACTIONS, parseVersion, cliCompatStatus, checkCliCompat,
  extractJson, requirePayload, countActions, countGated, statusBadge, parseProfileNames, joinStreams,
};
