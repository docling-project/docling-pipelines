# OpenSpec in Docling Pipelines

This directory contains the behavioral specifications for **Docling Pipelines** using [OpenSpec](https://openspec.dev).

OpenSpec establishes a single source of truth for the observable capabilities of the system across the Python backend engine and the React frontend.

---

## Directory Layout

```
openspec/
├── config.yaml          # Project context, naming rules, and validation configuration
├── specs/               # Canonical, archived specifications (single source of truth)
│   ├── backend/         # Python API endpoints, execution engine, and operator specs
│   └── frontend/        # React pages, panels, canvases, and state slice specs
└── changes/             # Active and archived change proposals
    ├── archive/         # Historical completed changes
    └── <change-name>/   # Active changes in progress (proposal, design, tasks, spec deltas)
```

---

## Spec-Driven Workflow

Whenever adding a feature, modifying API behaviors, or altering frontend contracts:

### 1. Check Existing Specs
```bash
openspec list --specs
```

### 2. Propose a Change
```bash
openspec new change <descriptive-name>
```
This generates an active change folder under `openspec/changes/<descriptive-name>/`.
Fill in the following artifacts:
- `proposal.md` — What problem this solves, what capabilities are added/modified, and non-goals.
- `design.md` — Technical design, architectural decisions, and trade-offs.
- `specs/<capability-path>/spec.md` — Behavioral contracts using `### Requirement:` and `#### Scenario:` WHEN/THEN blocks.
- `tasks.md` — Implementation breakdown checklist.

### 3. Validate Strictly
```bash
openspec validate <change-name> --strict
```
Ensure all schema rules, formatting requirements, and requirement headers pass validation.

### 4. Implement & Test
Develop the code and run test suites:
```bash
# Python backend
uv run pytest -v

# Frontend
cd frontend && npm run lint && npm run build
```

### 5. Archive Completed Change
```bash
openspec archive <change-name>
```
Archiving automatically merges the spec deltas into canonical specs under `openspec/specs/` and records the change in `openspec/changes/archive/`.

---

## Specification Rules & Standards

- **Capabilities, not Components:** Write specs for user-facing or integration capabilities rather than 1:1 component file mirrors.
- **Language:** Use normative keywords (`SHALL`, `MUST`) for requirement contracts.
- **Scenarios:** Every requirement must have at least one testable scenario using exactly `#### Scenario:` (4 hashtags) and `- **WHEN** ...` / `- **THEN** ...`.
- **Never edit canonical specs directly:** Always modify `openspec/specs/` via `openspec archive`.
