# Migration Guide Template: vX.Y → vA.B

> **Copy this template** to `docs/guides/MIGRATION_GUIDE_vA_B.md` and replace all placeholders.
> Delete this notice when the guide is complete.

---

## Overview

This guide describes how to upgrade from `docling-pipelines` **vX.Y** to **vA.B**.

**Upgrade complexity**: Low / Medium / High _(choose one)_

**Estimated time**: < 30 minutes / 1–2 hours / Half a day _(choose one)_

---

## Breaking Changes Summary

| # | Area | What changed | Replacement |
|---|------|-------------|-------------|
| 1 | Operator / API / Flow JSON / CLI | Short description | New feature / API |
| 2 | … | … | … |

---

## Prerequisites

- `docling-pipelines` vX.Y (the version you are upgrading **from**)
- Python 3.12 or later
- `uv` package manager

---

## Step-by-Step Upgrade Instructions

### Step 1: Update the package

```bash
uv pip install "docling-pipelines==A.B.0"
```

### Step 2: Address breaking change #1 — `<short title>`

**What changed:**

Describe the change concisely. Include the motivation if it helps users understand.

**Before (vX.Y):**

```python
# Python API example showing old usage
from docpipe.operators import OldOperator

op = OldOperator(old_param="value")
```

```json
// Flow JSON example showing old field name
{
  "type": "OldOperator",
  "params": {
    "old_param": "value"
  }
}
```

**After (vA.B):**

```python
from docpipe.operators import NewOperator

op = NewOperator(new_param="value")
```

```json
{
  "type": "NewOperator",
  "params": {
    "new_param": "value"
  }
}
```

**Automated migration (if available):**

```bash
# Run migration script from the repo root
python scripts/migrate_vX_Y_to_vA_B.py --flow-dir ./my_flows
```

---

### Step 3: Address breaking change #2 — `<short title>`

_(Repeat the same structure for every breaking change.)_

---

## Automated Migration Script

If a migration script is available, document it here:

```bash
python scripts/migrate_vX_Y_to_vA_B.py [OPTIONS]

Options:
  --flow-dir PATH   Directory containing flow JSON files to migrate (default: .)
  --dry-run         Print changes without writing files
  --backup          Create .bak copies of modified files before overwriting
```

---

## Deprecated Features Removed in This Release

The following features were deprecated in vX.Y and are now removed:

| Feature | Deprecated in | Replacement |
|---------|--------------|-------------|
| `OldOperator` | vX.Y | `NewOperator` |
| `old_param` flow field | vX.Y | `new_param` |

---

## Known Issues and Caveats

- List any known limitations of this upgrade path.
- List any edge cases that the automated script does not handle.

---

## Getting Help

If you encounter problems during migration:

1. Check the [Troubleshooting Guide](../../TROUBLESHOOTING.md).
2. Search [GitHub Issues](https://github.com/docling-project/docling-pipelines/issues).
3. Open a new issue with the label `migration` if your problem is not already tracked.
