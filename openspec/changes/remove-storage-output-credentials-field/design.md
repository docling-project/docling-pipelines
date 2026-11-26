# Design

## Component hierarchy

```text
StorageOutputPanelBody
├── Mode dropdown
├── Provider dropdown
├── Per-provider provider_config field groups
│   (Defined JSX per provider; definition, required flag and defaults come from the operator metadata provider schema)
├── [removed] Credentials field
└── Output format / output structure (unchanged)
```

## Decisions

- **Rendering stays provider-specific.** Only the Credentials field is removed; provider field groups and their
  metadata-driven definitions and defaults are untouched.
- **Migrate on open, persist on save.** The panel updates `destination_config` through the canvas controller when it
  opens. Cancelling the panel discards the update, so nothing is lost; saving persists it.
- **Pure, separately testable migration.** The migration is a pure function of the destination config. It returns the
  migrated config, or nothing when there is no non-empty object-valued `credentials` block (including a vault reference
  string). This keeps it unit-testable without Elyra.
- **Merge rule matches the backend.** The backend builds `{**provider_config, **credentials}`, so non-blank
  `credentials` values win. Blank values (`null`, empty or whitespace string) are skipped so seeded `null` defaults in
  `provider_config` cannot erase real values.
- **Box alias.** Older backends read only `credentials_json_path`; the panel and metadata use `credentials_path`, so the
  migration renames the key for provider `box`.
- **Key removed, not emptied.** The result omits `credentials`; the backend treats it as optional (default `{}`).

## Risks

- A user who edits an old flow and saves loses nothing: values move to visible fields. Flows never opened in the UI
  keep working through the unchanged backend merge.
- No redux slice or API client call is involved.
