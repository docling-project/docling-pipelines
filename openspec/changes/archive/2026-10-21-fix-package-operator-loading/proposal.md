# Proposal

## Why

Installed packages without `docpipe.operators` entry points can be discovered by module inspection, but the discovered
`module_path` appends a class name as though it were a Python module. Loading then fails. When a module defines several
operators, validation and extraction choose the first class alphabetically instead of the class named by discovery.

## What Changes

- Record module-inspected package operators using the supported `module:Class` path.
- Validate and load the class identified by `OperatorInfo.name` when that name is supplied, including modules with
  multiple operator classes.
- Reject stale or invalid named metadata with a useful error instead of silently substituting another class.
- Keep module-only paths loadable. For third-party adapters that supply an empty class name, retain first-class selection
  as a compatibility fallback; repository adapters supply class names and will use exact selection.
- Cover real installed-package imports, entry points, multiple classes, invalid metadata, and legacy loading.

## Capabilities

### New Capabilities

- `backend/package-operator-loading`: Discovery and loading of custom operators from installed packages and other
  operator sources with class-specific metadata.

### Modified Capabilities

None. Existing backend specs cover REST operator management and flow execution, not operator-source class resolution.

## Impact

Backend-only. The affected code is the package adapter and shared operator validator/loader, so named operators from
filesystem and S3 sources also gain exact class selection. Existing locally defined entry-point classes and plain module
paths remain supported. No REST route, operator implementation, storage adapter, frontend route, BFF route, or Redux
slice changes. No new dependency or public API shape change is proposed.

## Non-goals

- Change entry point registration or the priority of one discovery source over another.
- Import arbitrary class names outside the discovered module.
- Refactor unrelated adapters or change how short-name conflicts are resolved.
