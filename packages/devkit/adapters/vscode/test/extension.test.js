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
    getConfiguration: () => ({ get: (k, d) => d }),
    openTextDocument: () => Promise.resolve({}),
  },
  commands: { registerCommand: () => ({ dispose() {} }) },
};

const Module = require("module");
const origRequire = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === "vscode") return vscodeStub;
  return origRequire.apply(this, arguments);
};

const { __internals__ } = require("../extension.js");
const test = require("node:test");
const assert = require("node:assert");

test("statusBadge renders update/blocked/current counts", () => {
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
  assert.strictEqual(
    badge(plan([{ action: "blocked" }])).text,
    "$(warning) devkit: 1 blocked",
  );
  assert.strictEqual(badge(plan([{ action: "current" }])).text, "$(pass) devkit: current");
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

test("parseProfileNames reads the profiles table", () => {
  const names = __internals__.parseProfileNames(
    "qa: QA tools — linters\nmemory: Memory stack — brain + store\n\n(agent): alias\n",
  );
  assert.deepStrictEqual(names, ["qa", "memory"]);
  assert.deepStrictEqual(__internals__.parseProfileNames(""), []);
});

test("countActions counts matching plan actions only", () => {
  const count = __internals__.countActions;
  const plan = { actions: [{ action: "update" }, { action: "current" }, null, { action: "update" }] };
  assert.strictEqual(count(plan, "update"), 2);
  assert.strictEqual(count(plan, "blocked"), 0);
  assert.strictEqual(count(null, "update"), 0);
});
