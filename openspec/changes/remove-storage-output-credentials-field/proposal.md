# Proposal

## Why

The StorageOutput panel has a free-form Credentials JSON field next to the per-provider fields. Every credential attribute
(S3 keys, SharePoint client secret, Box and Google Drive credential paths) is already exposed and editable inside
`provider_config`, so the extra field is redundant. If a user fills both, the hidden `credentials` value silently
overrides the visible `provider_config` value at runtime.

## What Changes

- Remove the Credentials field from the StorageOutput panel.
- When the panel opens a node with a non-empty `destination_config.credentials` object, move its values into
  `provider_config` and remove the `credentials` key. Non-blank `credentials` values win over `provider_config`
  (same as the backend merge); blank values are ignored. For Box, `credentials_json_path` is written as
  `credentials_path`.
- Stop writing an empty `credentials` object when the provider changes.

Layer: frontend-only.

## Non-goals

- No backend change. `StorageOutputOperator` keeps accepting `credentials` and merging it with `provider_config`,
  so flows that are never opened in the UI, and API/CLI flows, behave as before.
- No change to the `credentials` operator metadata attribute or its secret-field masking.
- No migration of whole-object vault reference strings.

## Capabilities

### New Capabilities
None

### Modified Capabilities
- `frontend/properties-panel`: the StorageOutput requirement gains scenarios for credentials living only in provider
  fields and for legacy credentials migration.

## Impact

- `frontend/src/components/PropertiesPanel/CustomPanels/StorageOutput/` (panel, messages, and a new migration
  helper), `frontend/src/i18n/messages_en.json`, and a unit test for the migration helper.
- Carbon: removes one `VaultInput` (multiline) usage; no new components.
