"use strict";

// Contract guard: the CLI-version pin in package.json, the COMPATIBLE_CLI
// bounds in extension.js, and the real devin-devkit version must agree —
// and the adapter must stay read-only (no apply/force args anywhere).

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ADAPTER = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ADAPTER, "package.json"), "utf8"));
const src = fs.readFileSync(path.join(ADAPTER, "extension.js"), "utf8");

// packages/devkit/pyproject.toml is the source of truth for the CLI version.
const pyproject = fs.readFileSync(
  path.join(ADAPTER, "..", "..", "pyproject.toml"),
  "utf8",
);
const realVersion = /^version\s*=\s*"([^"]+)"/m.exec(pyproject)[1];

function parseRange(range) {
  const m = /^>=(\d+)\.(\d+)\.(\d+),<(\d+)\.(\d+)\.(\d+)$/.exec(range);
  assert.ok(m, `pin "${range}" must be a ">=x.y.z,<x.y.z" range`);
  return {
    min: [Number(m[1]), Number(m[2])],
    maxExclusive: [Number(m[4]), Number(m[5])],
  };
}

test("package.json pins the devin-devkit CLI range", () => {
  assert.ok(pkg["devin-devkit-cli"], "missing devin-devkit-cli field");
  parseRange(pkg["devin-devkit-cli"]);
});

test("COMPATIBLE_CLI matches the package.json pin", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-devkit-cli"]);
  const m = /COMPATIBLE_CLI\s*=\s*\{\s*min:\s*\[(\d+),\s*(\d+)\],\s*maxExclusive:\s*\[(\d+),\s*(\d+)\]/.exec(src);
  assert.ok(m, "COMPATIBLE_CLI bounds not found in extension.js");
  assert.deepStrictEqual([Number(m[1]), Number(m[2])], min);
  assert.deepStrictEqual([Number(m[3]), Number(m[4])], maxExclusive);
});

test("the real devin-devkit version falls inside the pinned range", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-devkit-cli"]);
  const [maj, minr] = realVersion.split(".").map(Number);
  const geMin = maj > min[0] || (maj === min[0] && minr >= min[1]);
  const ltMax = maj < maxExclusive[0] || (maj === maxExclusive[0] && minr < maxExclusive[1]);
  assert.ok(geMin && ltMax, `devin-devkit ${realVersion} outside ${pkg["devin-devkit-cli"]}`);
});

test("adapter never passes mutating CLI flags", () => {
  // Every CLI invocation in extension.js is a literal args array; scan all
  // of them plus the whole source for the apply/force switches.
  assert.ok(!/--apply|--force/.test(src), "mutating flag found in extension.js");
  const argArrays = src.matchAll(/\[\s*"([a-z-]+)"(?:\s*,[^\]]*)?\]/gs);
  const FORBIDDEN = new Set(["new", "resume", "prompt", "intake"]);
  for (const m of argArrays) {
    assert.ok(!FORBIDDEN.has(m[1]), `forbidden subcommand "${m[1]}" reached the CLI`);
  }
});
