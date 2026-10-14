"use strict";

// Minimal vscode stub injected before requiring the extension — enough for
// the pure rendering paths to run outside the editor.
const vscodeStub = {
  ThemeColor: class {
    constructor(id) {
      this.id = id;
    }
  },
  StatusBarAlignment: { Left: 1, Right: 2 },
  Position: class {
    constructor(line, ch) {
      this.line = line;
      this.character = ch;
    }
  },
  window: {
    createStatusBarItem: () => ({ show() {}, hide() {} }),
    showWarningMessage: () => Promise.resolve(),
    showErrorMessage: () => Promise.resolve(),
    showQuickPick: () => Promise.resolve(undefined),
    showTextDocument: () => Promise.resolve({ edit: async () => true }),
  },
  workspace: {
    isTrusted: true,
    workspaceFolders: [{ uri: { fsPath: "/repo" } }],
    getConfiguration: () => ({ get: (k, d) => (k in settings ? settings[k] : d) }),
    openTextDocument: () => Promise.resolve({}),
  },
  commands: { registerCommand: () => ({ dispose() {} }) },
};

const cpCalls = []; // { exe, args, opts } — every spawn the extension attempts
const cpStub = {
  execFile: (exe, args, opts, cb) => {
    cpCalls.push({ exe, args, opts });
    cb(null, "1.0.0", "");
  },
};
let settings = {};

const Module = require("module");
const origRequire = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === "vscode") return vscodeStub;
  if (id === "child_process") return cpStub;
  return origRequire.apply(this, arguments);
};

const ext = require("../extension.js");
const { __internals__ } = ext;
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

test("statusBadge renders update counts with warning color", () => {
  const badge = __internals__.statusBadge;
  const plan = (actions) => ({ actions });
  assert.strictEqual(badge(plan([])).text, "$(pass) devkit: current");
  assert.strictEqual(
    badge(plan([{ action: "update" }, { action: "update" }])).text,
    "$(cloud-download) devkit: 2 updates",
  );
  assert.strictEqual(
    badge(plan([{ action: "update" }])).bg.id,
    "statusBarItem.warningBackground",
  );
});

test("statusBadge treats gated actions as blocked, never current", () => {
  const badge = __internals__.statusBadge;
  const plan = (actions) => ({ actions });
  for (const action of ["blocked", "environment-blocked", "unsupported"]) {
    const b = badge(plan([{ action }]));
    assert.strictEqual(b.text, "$(warning) devkit: 1 blocked", action);
    assert.strictEqual(b.bg.id, "statusBarItem.warningBackground", action);
  }
  const mixed = badge(plan([{ action: "environment-blocked" }, { action: "unsupported" }]));
  assert.strictEqual(mixed.text, "$(warning) devkit: 2 blocked");
  // not-installed/unmanaged carry no verdict — they don't gate the badge.
  assert.strictEqual(badge(plan([{ action: "not-installed" }])).text, "$(pass) devkit: current");
  assert.strictEqual(badge(plan([{ action: "unmanaged" }])).text, "$(pass) devkit: current");
  assert.strictEqual(badge({}).text, "$(pass) devkit: current");
});

test("extractJson tolerates the trailing dry-run note", () => {
  const ex = __internals__.extractJson;
  const plan = { actions: [{ action: "update" }], registry_version: 24 };
  const withNote = `${JSON.stringify(plan)}\nDry run only. Re-run with --apply to update.\n`;
  assert.deepStrictEqual(ex(withNote), plan);
  assert.deepStrictEqual(ex(JSON.stringify(plan)), plan);
  assert.throws(() => ex("not json at all"), /did not return JSON/);
});

test("requirePayload surfaces the CLI's own stderr on failure", () => {
  const req = __internals__.requirePayload;
  assert.throws(
    () => req(2, "", "error: cannot fetch remote manifest: boom", "outdated"),
    /outdated exited 2: error: cannot fetch remote manifest: boom/,
  );
  assert.throws(() => req(1, "  ", "", "update"), /update exited 1: no output/);
  // Blocked install plans exit 2 WITH json stdout — must not throw.
  assert.doesNotThrow(() => req(2, '{"errors":["x"],"actions":[]}', "", "install qa"));
  assert.doesNotThrow(() => req(0, "{}", "", "outdated"));
});

test("joinStreams keeps the stderr hint alongside stdout", () => {
  const join = __internals__.joinStreams;
  assert.strictEqual(join("listing\n", ""), "listing");
  assert.strictEqual(
    join("listing\n", "registry v24 is available\n"),
    "listing\n\nregistry v24 is available",
  );
  assert.strictEqual(join("", "hint only"), "hint only");
});

test("parseVersion extracts the first semver-looking token", () => {
  const pv = __internals__.parseVersion;
  assert.deepStrictEqual(pv("devin-devkit 0.1.0"), [0, 1, 0]);
  assert.deepStrictEqual(pv("1.2.3"), [1, 2, 3]);
  assert.strictEqual(pv(""), null);
  assert.strictEqual(pv("no version"), null);
});

test("cliCompatStatus compares against COMPATIBLE_CLI bounds", () => {
  const cs = __internals__.cliCompatStatus;
  assert.strictEqual(cs("0.1.0"), "compatible");
  assert.strictEqual(cs("0.1.7"), "compatible");
  assert.strictEqual(cs("0.0.9"), "too-old");
  assert.strictEqual(cs("0.2.0"), "too-new");
  assert.strictEqual(cs("1.0.0"), "too-new");
  assert.strictEqual(cs("garbage"), "unknown");
  assert.strictEqual(cs([0, 1, 0]), "compatible");
});

test("parseProfileNames reads the profiles table", () => {
  const names = __internals__.parseProfileNames(
    "qa: QA tools — linters\nmemory: Memory stack — brain + store\n\n(agent): alias\n",
  );
  assert.deepStrictEqual(names, ["qa", "memory"]);
  assert.deepStrictEqual(__internals__.parseProfileNames(""), []);
});

test("countActions/countGated count matching plan actions only", () => {
  const { countActions, countGated } = __internals__;
  const plan = { actions: [
    { action: "update" }, { action: "current" }, null,
    { action: "environment-blocked" }, { action: "unsupported" },
  ] };
  assert.strictEqual(countActions(plan, "update"), 1);
  assert.strictEqual(countGated(plan), 2);
  assert.strictEqual(countActions(null, "update"), 0);
  assert.strictEqual(countGated(undefined), 0);
});

test("manifest declares limited untrusted-workspace support", () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"),
  );
  const uw = manifest.capabilities.untrustedWorkspaces;
  assert.strictEqual(uw.supported, "limited");
  assert.deepStrictEqual(uw.restrictedConfigurations.sort(), [
    "devinDevkit.checkOnStartup",
    "devinDevkit.executable",
  ]);
});

test("activate never spawns the CLI in an untrusted workspace", async () => {
  settings = { checkOnStartup: true };
  vscodeStub.workspace.isTrusted = false;
  cpCalls.length = 0;
  ext.activate({ subscriptions: [] });
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(cpCalls.length, 0);
  vscodeStub.workspace.isTrusted = true;
  ext.activate({ subscriptions: [] });
  await new Promise((r) => setImmediate(r));
  assert.ok(cpCalls.length >= 1);
  settings = {};
});
