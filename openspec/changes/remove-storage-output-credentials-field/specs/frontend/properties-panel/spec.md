## MODIFIED Requirements

### Requirement: StorageOutput multi-provider backend configuration
The StorageOutput panel SHALL dynamically render connection and credential fields tailored to the selected storage provider (Filesystem, S3, Box, SharePoint, Google Drive), enforcing required credentials before enabling panel save.

#### Scenario: Provider change renders appropriate backend fields
- **WHEN** the user switches between storage providers (e.g. Filesystem to S3)
- **THEN** the panel updates the configuration form with the provider's specific connection and bucket parameters

#### Scenario: Credentials are edited only in provider fields
- **WHEN** the user configures a storage provider
- **THEN** the panel renders no separate Credentials field and the provider's credential inputs write to `destination_config.provider_config`

#### Scenario: Legacy credentials migrate into provider fields on open
- **WHEN** the panel opens a node whose `destination_config.credentials` is a non-empty object
- **THEN** each non-blank value is copied into `provider_config`, replacing the same key there
- **AND** a Box `credentials_json_path` is written as `credentials_path`
- **AND** the `credentials` key is removed from the node parameters once the user saves

#### Scenario: Cancelling keeps the stored credentials
- **WHEN** the user closes the panel without saving after the migration ran
- **THEN** the saved node parameters, including `credentials`, are unchanged
