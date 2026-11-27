# Design

## Context

- `FlowService.create_flow` rejects duplicates via `self._repository.exists_by_name(name=...)` and raises
  `FlowAlreadyExistsException`, which the flows routes map to 409 with code `conflict`.
- `update_flow` (PUT) and `partial_update_flow` (PATCH) had no such check.
- `exists_by_name` compares names exactly and is not scoped to a project, so uniqueness is global in the backend.

## Decisions

### D1: Shared backend helper, skipped on unchanged name
`FlowService._ensure_name_available_on_rename(existing, new_name)` returns immediately when `new_name` is `None`
(PATCH without a name) or equals the stored name; otherwise it raises `FlowAlreadyExistsException` if
`exists_by_name` is true. It runs after the ownership check and before any field is applied, so a rejected rename
leaves the stored flow untouched. Alternative considered: a repository-level unique constraint; rejected because the
local, DuckDB and Postgres asset repositories share one port and `create_flow` already enforces uniqueness in the
service.

### D2: Frontend check is advisory, backend decides
The client compares the trimmed, case-insensitive name against flows in the same project only. The backend rule is
exact-match and global, so a name used only in another project is not flagged client-side; if the backend rejects it,
the 409 is shown through the same inline error. Duplicate detection is active only when the caller passes
`duplicateNameMessage`, keeping `EditDetailsModal` reusable for other entities.

### D3: Sibling names from the backend
The Redux flow map may hold only the current flow after a deep link or refresh. `useSiblingFlowNames` fetches
`getFlowsByProjectId` while the modal is open and merges the result with store names; a failed fetch falls back to the
store, and the 409 fallback still covers the gap.
