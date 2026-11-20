# Tasks

## 1. Repository Review

- [ ] 1.1 Inspect existing LLM adapters, operator implementations, shared constants, and sample flows; record the specific reuse points in the implementation changes.
- [ ] 1.2 Inspect the current PR diff and maintainer comments; verify the planned changes cover each requested item without unrelated modifications.

## 2. Translation Implementation

- [ ] 2.1 Review the translation service and reuse existing provider adapters and configuration; run the service tests to verify supported-provider behavior.
- [ ] 2.2 Review operator orchestration and registry integration; run operator tests to verify registration and document-data preservation.
- [ ] 2.3 Verify empty-content handling, chunk ordering, language metadata, and per-document failure isolation with targeted tests.

## 3. Sample Flow and Documentation

- [ ] 3.1 Integrate the LiteLLM translation example into a suitable existing sample flow and validate its JSON structure and referenced operators.
- [ ] 3.2 Update operator documentation and the operator reference to match the implemented behavior; verify documented configuration and usage against the code.

## 4. Verification and Pull Request

- [ ] 4.1 Run targeted translation tests and relevant repository checks; resolve failures and record the results.
- [ ] 4.2 Review the final diff to confirm constants are reused appropriately and no unnecessary architecture or files remain.
- [ ] 4.3 Complete the PR template, resolve review comments, and verify DCO, commit-signing, and required CI checks before requesting review.

## Workflow follow-up

- Archive the OpenSpec change after implementation and review requirements are satisfied.
- Verify the archived change and keep the PR branch limited to intended project changes.