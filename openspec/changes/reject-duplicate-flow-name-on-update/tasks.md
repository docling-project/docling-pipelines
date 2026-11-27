# Tasks

## 1. Backend

- [x] 1.1 Add `FlowService._ensure_name_available_on_rename` and call it from `update_flow` and `partial_update_flow`; verify `tests/unit/core/assets_management/application/services/test_flow_service.py` covers rename to a duplicate, rename to a unique name, unchanged name, and PATCH without a name.
- [x] 1.2 Verify `tests/unit/api/routes/test_flows_routes.py` covers `PUT` rename to an existing name returning 409.

## 2. Frontend

- [x] 2.1 Add `isConflictError` in `frontend/src/utils/httpErrors.ts`; verify `httpErrors.test.ts`.
- [x] 2.2 Add `existingNames` / `duplicateNameMessage` to `EditDetailsModal` with blur, save and 409 handling; verify `EditDetailsModal.test.tsx`.
- [x] 2.3 Add `useSiblingFlowNames` and wire it into `FlowDetail` and `Canvas`; wire `FlowsTable` from its rows; verify `FlowDetail.test.tsx` and `FlowsTable.test.tsx`.
- [x] 2.4 Suppress the generic failure toast on a 409 in `Canvas` and `ProjectDetail`; verify `ProjectDetail.test.tsx`.

## 3. Spec hand-off

- [x] 3.1 Run `openspec validate reject-duplicate-flow-name-on-update --strict`.
- [ ] 3.2 After review and passing tests, run `openspec archive reject-duplicate-flow-name-on-update`.
