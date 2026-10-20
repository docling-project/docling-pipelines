# Design

## Current behavior

Module inspection records `package.operators.ClassName`, while `PackageAdapter.load_operator()` imports that entire
string as a module. The shared validator and loader then scan operator classes and choose the first one in sorted member
order, independently of `OperatorInfo.name`.

## Proposed behavior

Module inspection records `package.operators:ClassName`, matching entry point paths. The adapter imports the module
portion and continues returning a module through `OperatorSourcePort`. Shared validation and extraction resolve
`OperatorInfo.name` on that module, require a locally defined concrete `AbstractOperator` subclass, and apply the
existing operator contract to that same class. Missing or invalid named targets fail with actionable diagnostics.
If a locally defined class is exported only through an alias, the `module:Class` suffix identifies the module attribute
and `OperatorInfo.name` retains the class's actual name; both must resolve to the same class object.
For metadata with an empty name, retain the previous first locally defined operator selection and its multiple-class
warning. The `OperatorInfo` dataclass permits an empty name, so this protects third-party source adapters that only
identify a module; repository discovery paths populate `name`. Plain module paths with a populated name remain valid
and resolve that name. A named target does not fall back to another class.

## Boundaries and trade-offs

The package adapter is an infrastructure adapter; the shared loader is application orchestration and the validator is
its contract check. No domain model or port shape changes. The explicit-name rule prevents a stale entry point or
metadata mismatch from loading a different class. Legacy unnamed metadata remains permissive for callers that only
identify a module. Imported classes are excluded, as they already are during module inspection.

## Risks and mitigation

- Class aliases and stale metadata: verify that the resolved class is defined in the loaded module and has the named
  identity, allowing an alias in the module path only when it resolves to that same class; otherwise report a failure.
- Entry points: test locally defined classes from a real installed distribution with `docpipe.operators` metadata,
  including a module with multiple classes. Imported re-exports already fail shared module validation and are outside
  the supported behavior being preserved.
- Backward compatibility: test an unnamed `OperatorInfo`, a named plain module path, and filesystem/S3 class metadata.
- Import/cache behavior: use the installed-package test harness so tests exercise real Python imports.
