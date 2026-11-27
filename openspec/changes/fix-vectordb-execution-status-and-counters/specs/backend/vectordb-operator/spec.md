# Spec Delta

## MODIFIED Requirements

### Requirement: Batch document indexing and error isolation
The operator SHALL index documents in batches according to configured batch size, aggregating chunk-level failures and associating them with their parent documents. A parent document SHALL be identified by its `id` column value, or by its document ID column value when `id` is missing or empty, and SHALL be recorded once in `failed_docs` regardless of how many of its chunks failed.

#### Scenario: Partial chunk indexing failure
- **WHEN** specific chunks fail during bulk indexing for some documents while other documents index fully
- **THEN** the parent documents of the failed chunks are recorded in `failed_docs` and the other documents are counted in `processed_docs`

#### Scenario: Multiple failed chunks of one document
- **WHEN** several chunks of the same document fail
- **THEN** the document is recorded once in `failed_docs` and `failed_docs_count` is incremented once

#### Scenario: Failed document identity matches the document id
- **WHEN** a failed document's `id` differs from its document ID column value
- **THEN** `failed_docs` records the `id` value, so the document is not also reported as completed

## ADDED Requirements

### Requirement: Indexing outcome status and document counters
After chunk indexing, the operator SHALL set `node_status` from the document outcome and SHALL keep the document counters consistent with the documents in scope. A document with any failed chunk SHALL NOT be counted in `processed_docs`, and `processed_docs`, `failed_docs_count` and `skipped_docs_count` SHALL add up to the number of documents in scope.

#### Scenario: All chunks indexed
- **WHEN** every chunk of every document is indexed
- **THEN** `node_status` is `Completed` and `failed_docs_count` is 0

#### Scenario: Some documents fail
- **WHEN** some documents have failed chunks and others are fully indexed
- **THEN** `node_status` is `CompletedWithErrors`

#### Scenario: All chunks fail to index
- **WHEN** every chunk of every document fails during bulk indexing
- **THEN** `node_status` is `Failed`, `processed_docs` is 0, `chunks_indexed_successfully` is 0, and each document is recorded once in `failed_docs`

#### Scenario: Skipped document is not processed
- **WHEN** a row without a document ID is skipped while the other documents index successfully
- **THEN** the skipped row is not counted in `processed_docs` and `node_status` is `CompletedWithWarnings`
