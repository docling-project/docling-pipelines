# Proposal

## Why

`POST /api/v1/flows` rejects a duplicate flow name with 409, but renaming an existing flow through `PUT` or `PATCH`
does not. The "Edit flow details" modal can therefore produce two flows with the same name, which the create path
already forbids.

## What Changes

- `PUT /api/v1/flows/{flow_id}` and `PATCH /api/v1/flows/{flow_id}` apply the same name-uniqueness rule as `POST` and
  return 409 (`errors[0].code = "conflict"`) when the flow is renamed to a name another flow already uses. The check is
  skipped when the name is unchanged, so saving without a rename never fails.
- `EditDetailsModal` (used by the flow detail page, the canvas page and the project detail page) validates the name
  against sibling flows on blur and on save, shows the existing `nameDuplicate` inline error, and does not call
  `PATCH` for a client-detected duplicate. A 409 from the backend is shown through the same inline error.
- Canvas and project detail pages no longer show the generic "failed to save" toast for a 409.
- A `useSiblingFlowNames` hook fetches the project's flows while the modal is open so the check works on a deep link
  or refresh, when the store only holds the current flow.

## Impact

- Capabilities: `backend/flows-api`, `frontend/flow-detail-page`, `frontend/canvas-page`, `frontend/project-detail-page`.
- Behavior change: a rename that previously succeeded (creating a duplicate name) now fails with 409.
- No change to request/response schemas; 409 and `ErrorResponse` already exist for `POST`.
