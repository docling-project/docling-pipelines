# Spec Delta

## ADDED Requirements

### Requirement: Milvus dense mode unmapped content fallback
In dense vector mode, when the collection's content field is unmapped and `content` is available for vector DB, the Milvus adapter SHALL populate the content field from `content` if it fits within the 65,535 UTF-8 byte limit. If explicitly mapped, this fallback SHALL be skipped; if over-limit, the text SHALL be omitted with a warning.

#### Scenario: Dense mode with unmapped content within limit
- **WHEN** a dense-mode Milvus node processes documents without an explicit feature mapping targeting the collection's content field, and `content` is within 65,535 UTF-8 bytes
- **THEN** each document is indexed with its `content` text populated in the collection's content field alongside its vector embeddings

#### Scenario: Dense mode with explicit feature mapping targeting content
- **WHEN** a feature mapping explicitly targets the collection's content field
- **THEN** the automatic content fallback is skipped and the mapped feature's value is used

#### Scenario: Dense mode with unmapped content exceeding VARCHAR limit
- **WHEN** unmapped `content` text exceeds 65,535 UTF-8 bytes
- **THEN** the content field is left empty for that document with a warning logged, and the document is still indexed with its vector embeddings without failing

#### Scenario: Content feature unavailable for vector DB
- **WHEN** the `content` feature in `available_features` has `available_for_vector_db` set to `false`
- **THEN** the unmapped content fallback is not applied and the content field remains empty

### Requirement: Milvus per-row isolation of oversized VARCHAR values
The Milvus adapter SHALL validate the UTF-8 byte length of all `VARCHAR` fields against the 65,535 byte limit before batch insertion. When a row contains an explicitly mapped `VARCHAR` field exceeding this limit, the adapter SHALL reject only that row before batch submission, record it in `failed_docs`, and retain all other rows in the batch for insertion.

#### Scenario: Explicitly mapped over-limit text rejects only that row
- **WHEN** a batch contains a document whose explicitly mapped `content` or `VARCHAR` field exceeds 65,535 UTF-8 bytes alongside valid documents
- **THEN** the oversized document is rejected before insertion and recorded in `failed_docs` with its chunk ID and reason, while valid documents in the batch are inserted successfully

#### Scenario: Multi-byte text measured in UTF-8 bytes
- **WHEN** a document's `VARCHAR` field contains multi-byte characters that exceed 65,535 UTF-8 bytes even if the character count is below 65,535
- **THEN** the document is identified as oversized based on UTF-8 byte length and handled according to the VARCHAR length policy

#### Scenario: Non-VARCHAR fields bypass VARCHAR length check
- **WHEN** a document contains large text in a field mapped to a non-VARCHAR data type such as `JSON`
- **THEN** the field is not checked against the 65,535 UTF-8 byte `VARCHAR` limit and the document is batched normally
