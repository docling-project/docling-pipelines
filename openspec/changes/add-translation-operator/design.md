# Design

## Context

See `proposal.md` for motivation and `specs/document-translation/spec.md` for required behavior. The existing pipeline already provides LLM adapter infrastructure and an operator registry. The design should build on these facilities and follow established operator and sample-flow conventions.

## Goals / Non-Goals

**Goals:**
- Keep translation provider-agnostic by reusing existing LLM adapters.
- Preserve established document data and pipeline error-handling conventions.
- Minimize new abstractions, configuration, and constants.
- Integrate the LiteLLM example into an existing sample flow where appropriate.

**Non-Goals:**
- Introducing a new provider framework or dependency.
- Refactoring unrelated operators or sample flows.
- Expanding translation behavior beyond the approved specification.

## Decisions

### Reuse existing adapter infrastructure

Use existing LLM adapter interfaces and provider configuration for translation. Add provider-specific logic only where existing abstractions cannot support the requirement.

**Alternative considered:** Create a separate provider abstraction. Rejected because it risks duplicating existing infrastructure and increasing maintenance.

### Keep the architecture minimal

Separate translation service logic from operator orchestration only where this matches existing project conventions and provides a clear testing benefit. Avoid extra layers or interfaces without a demonstrated need.

**Alternative considered:** Introduce a broader hexagonal architecture with additional ports and adapters. Rejected unless repository conventions or concrete requirements justify it.

### Reuse constants and configuration

Inspect existing constants, defaults, and configuration patterns before introducing new values. Reuse shared definitions where their meanings match; define translation-specific constants only when necessary.

**Alternative considered:** Define all translation values locally. Rejected where equivalent shared definitions already exist.

### Integrate with an existing sample flow

Place the LiteLLM translation example into the most suitable existing sample flow and follow its conventions. Avoid maintaining a separate translation-only flow unless the existing flows cannot demonstrate the feature clearly.

**Alternative considered:** Keep a standalone translation flow. Rejected to align with maintainer feedback and reduce duplication.

### Test through existing project conventions

Add or update tests for successful translation, provider errors, empty content, chunk ordering, document-data preservation, and batch failure isolation. Reuse existing fixtures and mocking patterns.

## Risks / Trade-offs

- **Adapter behavior differs by provider** → Use existing adapter contracts and test relevant failure paths.
- **Chunking changes output order or content** → Test ordered reconstruction of translated chunks.
- **Failure handling hides useful diagnostics** → Preserve actionable error information while allowing unrelated documents to continue.
- **Sample-flow integration causes regressions** → Validate the modified flow and keep unrelated changes out of scope.
- **New abstractions duplicate existing code** → Review current operators and adapters before adding architecture.

## Migration Plan

1. Finalize the specification and design before implementation review.
2. Inspect existing adapters, constants, operators, and sample flows.
3. Make the smallest implementation changes that satisfy the specification.
4. Run targeted translation tests and relevant repository checks.
5. Update documentation and the existing sample flow.
6. Address DCO, commit-signing, PR-template, and CI requirements before requesting review again.

Rollback consists of reverting the translation-related changes if they cause regressions; no data migration is expected.

## Open Questions

None that should block implementation planning. Resolve implementation details by following existing repository conventions and the approved specification.