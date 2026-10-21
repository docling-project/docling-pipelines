# backend/document-classes-api Specification

## Purpose

The document-classes-api capability is the REST API surface for retrieving document type definitions bundled with the repository. It exposes a single read-only endpoint that returns all document classes so the UI can populate document-class selectors dynamically without hard-coding values. Document class definitions are read from JSON schema files in `src/docpipe/core/document_classes/`. The service instance is cached for the process lifetime.

## Requirements

### Requirement: List all document classes
`GET /api/v1/document_classes` SHALL return a list of `DocumentClassItem` objects, one per valid document class JSON file found in the document classes directory. Each item SHALL contain `document_type` and `document_description`. Malformed or incomplete JSON files SHALL be skipped with a WARNING log and SHALL NOT cause the endpoint to fail.

#### Scenario: All valid document classes returned
- **WHEN** `GET /api/v1/document_classes` is called
- **THEN** the response is 200 with a list of `DocumentClassItem` objects, one per valid document class file

#### Scenario: Malformed JSON files skipped without error
- **WHEN** the document classes directory contains a malformed JSON file alongside valid files
- **THEN** the response is 200 with only the valid document classes; no 500 is returned

### Requirement: Directory scan failure returns 500
When the document classes directory cannot be scanned (e.g. permissions error or missing path), the endpoint SHALL return 500.

#### Scenario: Directory scan failure returns 500
- **WHEN** the document classes directory is inaccessible at request time
- **THEN** the response is 500 with an `ErrorResponse`
