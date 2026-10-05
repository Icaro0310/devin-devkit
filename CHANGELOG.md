# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Registry-backed profile installer with `qa`, `evaluation`, `security`, `memory`, `agent`, `operations`, `full`, and `all` selections.
- Dry-run by default; `--apply` is required to install. Python tools use isolated `uv` environments; the Node bridge uses npm and requires Node.js 20+.
- Preflight checks for supported OS, managers, Node version, Git source prerequisites, and command collisions. Existing commands are never overwritten.
- Bundled manifest generated from `devin-powerups/registry.json`; private entries are excluded, GitHub sources are pinned to commit SHAs, and source-only services are marked manual.
- Windows and Linux install guides; macOS is planned and explicitly unverified.
