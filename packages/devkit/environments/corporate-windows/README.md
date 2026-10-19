```text
CORPORATE WINDOWS · DEVIN ECOSYSTEM · LOCAL RUNTIME
local runtime is the source of truth
```

# Devin Ecosystem — Corporate Windows

Restricted Windows execution that is intentionally self-contained.

## Runtime

- 100% local execution;
- no Devin VM;
- no QwenPaw;
- no Slack dependency;
- no external workload delegation;
- no external compute dependency;
- unsupported tools require an explicit registry reason.

Runtime is 100% local; `install`/`update` download each tool's pinned spec
from the package index (PyPI or npm) or a GitHub archive, and `outdated`/
`update` also fetch the remote registry manifest. See the
[Corporate Windows guide](../../README.corporate-windows.md).

## Install

```powershell
devin-devkit install <profile> --environment corporate-windows
```

See the [Corporate Windows guide](../../README.corporate-windows.md) and the [registry-generated compatibility matrix](../../COMPATIBILITY.md).
