# Spec Delta

## ADDED Requirements

### Requirement: VectorDB Qdrant provider configuration
When operator metadata lists `qdrant` as a provider, the VectorDB custom panel SHALL offer it and SHALL render Qdrant's own connection, authentication, naming, and similarity configuration; it MUST NOT render another provider's fields for Qdrant. The panel SHALL provide a URL or host-and-port connection choice, an HTTPS setting for host connections, the gRPC port and preference, the request timeout, a masked API key input, a collection-name rule, a distance metric selector without an engine selector, and a capability-driven BM25 option. An API key over a non-HTTPS connection, or another invalid Qdrant setting, SHALL block opening the feature-mapping tearsheet and enrichment. Every new user-facing string SHALL be localizable, and every new control SHALL be keyboard operable with accessible labels and error messages. The behavior of the other providers SHALL be unchanged.

#### Scenario: Qdrant offered when the backend lists it
- **WHEN** operator metadata lists `qdrant` among the `provider_config` providers
- **THEN** the provider dropdown offers "Qdrant" together with the other listed providers, and selecting it displays Qdrant connection, authentication, and collection settings rather than the OpenSearch settings

#### Scenario: Provider list fallback unchanged
- **WHEN** operator metadata provides no `provider_config` providers
- **THEN** the provider dropdown keeps its existing fallback list, which does not include Qdrant

#### Scenario: URL versus host and port
- **WHEN** the user switches the Qdrant connection from "URL" to "Host and port", or back
- **THEN** only the fields of the chosen mode are shown, and the inactive mode's keys are removed from the saved `provider_config` in one change, while every other key remains

#### Scenario: API key accepts literals, environment references, and Vault references
- **WHEN** the user enters the Qdrant API key
- **THEN** the input is masked, accepts a literal value or a `$VAR` / `${VAR}` reference, and offers the existing Vault toggle for a `vault://` reference

#### Scenario: Empty Vault reference blocked
- **WHEN** the API key's Vault toggle is on and the reference is empty
- **THEN** an inline error names the API key field, and opening the tearsheet and running enrichment are blocked

#### Scenario: API key over HTTP blocked
- **WHEN** an API key is set and the connection is an `http://` URL, or host mode with HTTPS turned off
- **THEN** an inline error states that an API key requires an HTTPS connection, and opening the feature-mapping tearsheet and running enrichment are blocked until it is fixed

#### Scenario: Invalid connection settings blocked
- **WHEN** the URL is empty in URL mode, or a port is outside 1 to 65535
- **THEN** an inline error names the field, and opening the tearsheet and running enrichment are blocked

#### Scenario: Blocked open moves focus
- **WHEN** the user tries to open the tearsheet while a Qdrant setting is invalid
- **THEN** focus moves to the first invalid field and its error is announced to assistive technology

#### Scenario: Collection name rule for Qdrant
- **WHEN** the user enters a collection name in the tearsheet
- **THEN** names that break the server rule (empty, more than 255 characters, containing `/`, `\`, `:`, `*`, `?`, or a control character, or equal to `.` or `..`) show an inline error, and the placeholder shows a valid example

#### Scenario: Distance metric without engine selector
- **WHEN** the provider is Qdrant
- **THEN** the tearsheet offers the distance metrics Cosine, Dot, Euclid, and Manhattan, defaulting to Cosine, and shows no engine selector

#### Scenario: BM25 option driven by provider capability
- **WHEN** the provider is Qdrant and the collection name is new, or names an existing collection that enrichment reports with `sparse_eligible: true`
- **THEN** the tearsheet shows the BM25 option, and turning it on saves the top-level `add_sparse_vector` as true

#### Scenario: BM25 option for an eligible unsupported collection
- **WHEN** enrichment reports the selected collection as `supported: false` with `sparse_eligible: true`
- **THEN** the BM25 option is shown with a note that turning it on makes the collection usable

#### Scenario: BM25 option hidden for an ineligible collection
- **WHEN** enrichment reports the selected existing collection with `sparse_eligible: false`
- **THEN** the BM25 option is not shown, because the collection cannot be written in sparse mode

#### Scenario: Saved BM25 state preserved
- **WHEN** a node with `add_sparse_vector` true is reopened
- **THEN** the BM25 option is shown as on

#### Scenario: Enrichment failure shown
- **WHEN** enrichment returns an `error` inside `is_docpipe_supported_resource`
- **THEN** the tearsheet shows that error in an inline notification instead of an empty collection list

#### Scenario: Index parameters stay in Advanced JSON
- **WHEN** the user sets HNSW `index_parameters` in the Advanced JSON field, saves, and reopens the node
- **THEN** the value is still shown in Advanced JSON unchanged, and it is not sent in enrichment requests

#### Scenario: Advanced JSON preserved
- **WHEN** the user changes a Qdrant connection field through its control
- **THEN** other keys entered through Advanced JSON are kept

#### Scenario: Keyboard operation and focus
- **WHEN** the user operates the Qdrant controls with the keyboard only
- **THEN** every control is reachable and operable in a logical order, each has an accessible label, and each inline error is associated with its field

#### Scenario: Localized strings
- **WHEN** the Qdrant controls are rendered
- **THEN** every new label, error, and note comes from the message catalogue

#### Scenario: Other providers unchanged
- **WHEN** the provider is OpenSearch, Milvus, or Weaviate
- **THEN** the panel and tearsheet behave exactly as before this change
