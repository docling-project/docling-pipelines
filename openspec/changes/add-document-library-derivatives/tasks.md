# Tasks

Prerequisite: `add-document-set-data-card` is implemented, so the card records `derivative_store`, `feature_mappings`,
`embeddings[].provider`, `add_sparse_vector`, entity store location, and the three-state `propagate_source_acls`.

## 1. Domain

- [ ] 1.1 [backend] Add derivative dataclasses in `core/assets/derivatives/domain/models/derivative.py` (`DocumentSetDerivative`, `VectorStoreDerivative`, `EntityTableDerivative` incl. `database_path`, `EmbeddingSpec`, `ColumnMapping`, `CorrelationDetail`, `DerivativeConflict`, `AclState`) with no framework imports
- [ ] 1.2 [backend] Add `DerivativeResolverPort` (`list_for_library`, `get_for_document_set`) and `DataCardSourcePort` (`get_card`, `get_document_set_name`, `list_document_set_ids`) ABCs in `domain/ports/`
- [ ] 1.3 [backend] Add `ErrorCode.DERIVATIVE_INVALID_BOOKMARK` and `DerivativeInvalidBookmarkException` (400)

## 2. Resolution

- [ ] 2.1 [backend] Implement `DerivativeResolution` as `@staticmethod`, keyword-only functions: latest run per flow, union and de-duplication, newest wins
- [ ] 2.2 [backend] Implement conflict detection (`embedding_model`, `embedding_dimension`) carrying provider and kind only
- [ ] 2.3 [backend] Implement embedding pairing (by `feature_mappings`, else nearest preceding `embeddings` entry, else null)
- [ ] 2.4 [backend] Implement `column_mapping` from explicit mapping items only (no defaults, no embedding `feature` fallback) and `correlatable`
- [ ] 2.5 [backend] Implement entity table resolution (`retrievable` false for `:memory:`, no table names) and `correlation_details` with rule `id-prefix`
- [ ] 2.6 [backend] Implement `acl_state` and fail-closed `acl_protected`; pass `purpose`, `summary`, `language` through
- [ ] 2.7 [backend] Unit tests: no card, metadata ignored, older run ignored, two flows, same store twice, conflicts, each pairing rule, null mappings, embedding-after-document-set flow, in-memory and Postgres entity stores, three ACL states, enterprise-shaped card with missing fields

## 3. Query service and adapter

- [ ] 3.1 [backend] Implement `DerivativeQueryService` (implements `DerivativeResolverPort`; raises `DocumentSetNotFoundException` and `DocumentLibraryNotFoundException`; keeps library order)
- [ ] 3.2 [backend] Implement the `DataCardSourcePort` adapter over `DataCardService`, `DocumentSetService`, and `DocumentLibraryService`
- [ ] 3.3 [backend] Implement bookmark encode and decode (urlsafe base64 JSON `{"o", "v"}`) and offset pagination
- [ ] 3.4 [backend] Wire the providers in `api/dependencies.py`; the application layer imports no adapter
- [ ] 3.5 [backend] Unit tests for the query service with a fake `DataCardSourcePort`, including bookmark edge cases

## 4. REST

- [ ] 4.1 [backend] Add DTOs and `derivative_mapper.py` built from an explicit field list (no path, host, or credential fields)
- [ ] 4.2 [backend] Add `GET /document-sets/{document_set_id}/derivatives`
- [ ] 4.3 [backend] Add `GET /document-libraries/{library_id}/derivatives` with `limit`, `bookmark`, and tolerated `container_id` / `container_type`
- [ ] 4.4 [backend] Change `GET /document-libraries/{library_id}/document-sets` so `is_derivative_available` comes from the resolver and `propagate_source_acls` from the card, falling back to metadata only when the card value is null
- [ ] 4.5 [backend] API tests: 200 for both routes, no card, 404 for both, three pages, invalid bookmark, bookmark beyond the end, limit bounds (400 `validation_error`), 401 when auth is enabled, container parameters ignored, listing fields
- [ ] 4.6 [backend] Redaction test that feeds cards with `${VAR}`, `vault://`, password-like, and path-like values into every derivative field and asserts none reaches the response, including no `database_path`

## 5. Docs

- [ ] 5.1 [backend] Document both routes in `docs/api/REST_API_SERVER.md`
- [ ] 5.2 [backend] Update the two `is_derivative_available` examples in `docs/guides/USER_GUIDE_DOCUMENT_LIBRARIES.md`
- [ ] 5.3 [backend] Add a pointer to the derivatives view in `docs/guides/DOCUMENT_SET_DATA_CARD.md`

## 6. Validation

- [ ] 6.1 [backend] `uv run ruff check --fix .`
- [ ] 6.2 [backend] `uv run mypy .`
- [ ] 6.3 [backend] `uv run pytest tests/unit -m "unit and not integration"`
- [ ] 6.4 [backend] `openspec validate add-document-library-derivatives --strict`
