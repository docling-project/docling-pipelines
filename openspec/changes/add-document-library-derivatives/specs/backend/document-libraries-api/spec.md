# Spec Delta

## MODIFIED Requirements

### Requirement: List document sets in a library
`GET /api/v1/document-libraries/{library_id}/document-sets` SHALL return a `DocumentSetsRetrieved` response containing metadata for all document sets associated with the library, or an empty list if none are linked. Each entry SHALL report `is_derivative_available` and `propagate_source_acls` from the document set's data card.

#### Scenario: Document set metadata returned for each associated set
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` is called for a library with associated sets
- **THEN** the response is 200 with full metadata for each document set including document counts

#### Scenario: Library with no associations returns empty array
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` is called for a library with no sets
- **THEN** the response is 200 with an empty `document_sets` array

#### Scenario: documents field is null for sets with no stored documents
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` includes a set with `total_documents = 0`
- **THEN** the `documents` field for that entry is `null`

#### Scenario: Unknown library returns 404
- **WHEN** `GET /api/v1/document-libraries/{unknown_id}/document-sets` is called
- **THEN** the response is 404

#### Scenario: Derivative availability from the card
- **WHEN** a listed document set resolves to at least one vector store or entity table
- **THEN** its entry has `is_derivative_available` true, and false when it resolves to none

#### Scenario: Metadata no longer decides availability
- **WHEN** a document set's user-owned `metadata` sets `is_derivative_available` to true and its card lists no stores
- **THEN** its entry has `is_derivative_available` false

#### Scenario: ACL propagation from the card
- **WHEN** a listed document set's card has `propagate_source_acls` true or false
- **THEN** its entry reports that value

#### Scenario: ACL propagation fallback
- **WHEN** a listed document set's card has `propagate_source_acls` null and its `metadata` holds a boolean `propagate_source_acls`
- **THEN** its entry reports the metadata value, and `null` when the metadata has none
