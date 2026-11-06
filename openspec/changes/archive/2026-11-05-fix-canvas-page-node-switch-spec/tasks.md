# Tasks

## 1. Spec Correction

- [x] 1.1 [frontend] Review the `REMOVED` "Node properties panel" and `ADDED` "Node properties panel lifecycle" requirements in `specs/frontend/canvas-page/spec.md` against `frontend/src/pages/Canvas/Canvas.tsx` and `frontend/src/components/PropertiesPanel/CommonPropertiesWrapper.tsx`. Verify the text matches the code and the observed UI behavior.
- [x] 1.2 [frontend] Run `openspec validate fix-canvas-page-node-switch-spec --strict` and resolve any reported issues.
- [x] 1.3 [frontend] After review, run `openspec archive fix-canvas-page-node-switch-spec` to update `openspec/specs/frontend/canvas-page/spec.md`.
