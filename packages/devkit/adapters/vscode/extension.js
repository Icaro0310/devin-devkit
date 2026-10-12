"use strict";

// Thin adapter: the extension shells out to `devin-devkit` and renders the
// result — no install/update logic is reimplemented here. Read-only by
// construction: the mutating flags of the CLI (the apply/force switches on
// install and update) are never passed, so every plan shown is a dry run.

const vscode = require("vscode");
const cp = require("child_process");

let statusBar;
// Monotonic counter — a slow check finishing late must not overwrite a
// newer verdict already rendered on the status bar.
let statusSeq = 0;

// Contract with the CLI JSON payloads (outdated/install/update plans).
// Keep in sync with the "devin-devkit-cli" range in package.json —
// test/cli-contract.test.js asserts it.
const COMPATIBLE_CLI = { min: [0, 1], maxExclusive: [0, 2] };

function config() {
  const c = vscode.workspace.getConfiguration("devinDevkit");
  return { executable: c.get("executable", "devin-devkit") };
}

// Runs the CLI once and resolves {code, stdout, stderr}. Never throws on a
// non-zero exit — `install <p> --json` exits 2 when the plan is blocked,
// which is a renderable result, not an error.
function runDevkit(args) {
  const { executable } = config();
  return new Promise((resolve, reject) => {
    cp.execFile(
      executable,
      args,
      { timeout: 120000, maxBuffer: 8 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if (err && err.killed) {
          reject(new Error("devin-devkit timed out after 120s"));
          return;
        }
        if (err && err.code === "ENOENT") {
          reject(
            new Error(
              "devin-devkit not found on PATH. Install it (uv tool install devin-devkit) " +
              "or set devinDevkit.executable.",
            ),
          );
          return;
        }
        resolve({ code: err ? err.code : 0, stdout, stderr });
      },
    );
  });
}

// `update --json` prints a trailing "Dry run only." note after the JSON —
// extract the object leniently instead of failing the parse.
function extractJson(stdout) {
  const start = stdout.indexOf("{");
  const end = stdout.lastIndexOf("}");
  if (start < 0 || end <= start) {
    throw new Error("devin-devkit did not return JSON — see output channel");
  }
  return JSON.parse(stdout.slice(start, end + 1));
}

function countActions(plan, action) {
  return ((plan && plan.actions) || []).filter((a) => a && a.action === action).length;
}

function statusBadge(plan) {
  const updates = countActions(plan, "update");
  const blocked = countActions(plan, "blocked");
  const warn = new vscode.ThemeColor("statusBarItem.warningBackground");
  if (updates > 0) {
    return { text: `$(cloud-download) devkit: ${updates} update${updates === 1 ? "" : "s"}`, bg: warn };
  }
  if (blocked > 0) {
    return { text: `$(warning) devkit: ${blocked} blocked`, bg: warn };
  }
  return { text: "$(pass) devkit: current", bg: undefined };
}

async function status() {
  const seq = ++statusSeq;
  statusBar.text = "$(sync~spin) devkit: checking";
  statusBar.show();
  try {
    const { code, stdout, stderr } = await runDevkit(["outdated", "--json"]);
    const plan = extractJson(stdout);
    if (seq !== statusSeq) return plan;
    const badge = statusBadge(plan);
    statusBar.text = badge.text;
    statusBar.backgroundColor = badge.bg;
    statusBar.tooltip =
      `devin-devkit — registry v${plan.registry_version || "?"}; ` +
      `${countActions(plan, "update")} update(s), ${countActions(plan, "blocked")} blocked, ` +
      `${countActions(plan, "current")} current`;
    statusBar.show();
    return plan;
  } catch (e) {
    if (seq === statusSeq) {
      statusBar.text = "$(error) devkit: unavailable";
      statusBar.tooltip = e.message;
      statusBar.show();
      vscode.window.showErrorMessage(e.message);
    }
    return null;
  }
}

async function showDoc(language, content) {
  const doc = await vscode.workspace.openTextDocument({ language });
  const editor = await vscode.window.showTextDocument(doc, { preview: true });
  await editor.edit((b) => b.insert(new vscode.Position(0, 0), content));
}

async function runTextCommand(args) {
  const { code, stdout, stderr } = await runDevkit(args);
  if (code !== 0 && !stdout) {
    vscode.window.showErrorMessage(`devin-devkit ${args[0]} exited ${code}: ${stderr}`);
    return;
  }
  await showDoc("plaintext", stdout || stderr);
}

const profiles = () => runTextCommand(["profiles"]);
const listTools = () => runTextCommand(["list"]);

function parseProfileNames(profilesText) {
  const names = [];
  for (const line of profilesText.split("\n")) {
    const m = /^([A-Za-z0-9_-]+):/.exec(line);
    if (m) names.push(m[1]);
  }
  return names;
}

async function previewInstall() {
  const list = await runDevkit(["profiles"]);
  const names = parseProfileNames(list.stdout);
  if (!names.length) {
    vscode.window.showErrorMessage(`devin-devkit profiles: no profiles found (exit ${list.code})`);
    return;
  }
  const picked = await vscode.window.showQuickPick(names, {
    placeHolder: "Profile to preview (dry run only)",
  });
  if (!picked) return;
  const { code, stdout, stderr } = await runDevkit(["install", picked, "--json"]);
  if (!stdout.trim()) {
    vscode.window.showErrorMessage(`devin-devkit install ${picked} exited ${code}: ${stderr}`);
    return;
  }
  const plan = extractJson(stdout);
  if ((plan.errors || []).length) {
    vscode.window.showWarningMessage(
      `devin-devkit: plan for "${picked}" has ${plan.errors.length} blocking error(s) — see the plan.`,
    );
  }
  await showDoc("json", JSON.stringify(plan, null, 2));
}

async function previewUpdate() {
  const { stdout } = await runDevkit(["update", "--json"]);
  const plan = extractJson(stdout);
  await showDoc("json", JSON.stringify(plan, null, 2));
}

function activate(context) {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusBar.command = "devin-devkit.status";
  statusBar.text = "$(tools) devkit";
  statusBar.tooltip = "Click to check for outdated Devin tools";
  statusBar.show();

  context.subscriptions.push(
    statusBar,
    vscode.commands.registerCommand("devin-devkit.status", status),
    vscode.commands.registerCommand("devin-devkit.profiles", profiles),
    vscode.commands.registerCommand("devin-devkit.list", listTools),
    vscode.commands.registerCommand("devin-devkit.previewInstall", previewInstall),
    vscode.commands.registerCommand("devin-devkit.previewUpdate", previewUpdate),
  );

  if (vscode.workspace.getConfiguration("devinDevkit").get("checkOnStartup", false)) {
    status();
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
// Test-only surface — pure internals reachable without the editor.
module.exports.__internals__ = {
  COMPATIBLE_CLI, extractJson, countActions, statusBadge, parseProfileNames,
};
