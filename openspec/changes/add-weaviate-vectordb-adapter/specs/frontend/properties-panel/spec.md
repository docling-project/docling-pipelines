# Spec Delta

## MODIFIED Requirements

### Requirement: VectorDB feature mapping and backend configuration
The VectorDB custom panel SHALL support database backend selection (OpenSearch / Milvus / Weaviate), index/collection naming, and a feature mapping tearsheet that manages embeddings-to-field bindings and calls the feature enrichment endpoint. The provider list SHALL come from operator metadata. Each provider SHALL be rendered with its own connection, authentication, naming, and similarity configuration; an unknown provider MUST NOT silently render another provider's fields. For Weaviate the panel SHALL provide custom and Weaviate Cloud connection controls, authentication-method-specific masked credential inputs, a collection-name rule, a distance metric selector without an engine selector, and a capability-driven BM25 option. Invalid Weaviate connection or credential configuration SHALL block opening the feature-mapping tearsheet and enrichment. Every new user-facing string SHALL be localizable, and every new control SHALL be keyboard operable with accessible labels and error messages. OpenSearch and Milvus behavior SHALL be unchanged.

#### Scenario: Backend selection displays relevant configuration fields
- **WHEN** the user selects "OpenSearch" or "Milvus" as the vector database provider
- **THEN** provider-specific connection and index settings are displayed

#### Scenario: Feature mapping tearsheet manages embedding field bindings
- **WHEN** the user opens the feature mapping tearsheet
- **THEN** upstream embedding features and document metadata can be mapped to vector database payload fields

#### Scenario: Weaviate offered when the backend lists it
- **WHEN** operator metadata lists `weaviate` among the `provider_config` providers
- **THEN** the provider dropdown offers "Weaviate" together with the other listed providers, and selecting it displays Weaviate connection, authentication, and collection settings rather than the OpenSearch settings

#### Scenario: Provider list fallback unchanged
- **WHEN** operator metadata does not include any provider information
- **THEN** the provider dropdown offers only OpenSearch and Milvus

#### Scenario: Custom versus cloud connection
- **WHEN** the user selects the Weaviate "custom" connection type
- **THEN** host, HTTP port, HTTP TLS, gRPC host, gRPC port, and gRPC TLS controls are displayed and the cluster URL control is not
- **AND WHEN** the user selects the "cloud" connection type
- **THEN** only the cluster URL control is displayed, and the saved `provider_config` no longer contains any custom-connection key

#### Scenario: gRPC settings inherit from HTTP
- **WHEN** the user leaves the gRPC host empty and the gRPC TLS control on "Same as HTTP"
- **THEN** the saved `provider_config` contains neither `grpc_host` nor `grpc_secure`, so the backend inherits the HTTP values
- **AND WHEN** the user enters a gRPC host or chooses an explicit gRPC TLS setting
- **THEN** the saved `provider_config` contains exactly that value

#### Scenario: Authentication method changes credential fields
- **WHEN** the user selects the Weaviate authentication method "API key", "Bearer token", or "Username and password"
- **THEN** only the credential inputs of that method are displayed, each masked by default and offering the same Vault toggle as the OpenSearch credential inputs
- **AND WHEN** the user switches to another method
- **THEN** the previous method's credentials are removed from the saved `provider_config` in the same update that writes the new `auth_type`

#### Scenario: Credentials accept literals, environment references, and Vault references
- **WHEN** the user enters a literal value, `$WEAVIATE_API_KEY`, or `${WEAVIATE_API_KEY}` in a credential input, or turns on the Vault toggle and enters a provider and path
- **THEN** the value is stored unchanged (a Vault reference is stored with the `vault://` prefix) and satisfies the required-credential check

#### Scenario: Empty Vault reference blocked
- **WHEN** a credential is `vault://` with no provider and path after the prefix, for example after the user turns the Vault toggle on and enters nothing
- **THEN** an inline error is displayed on that field, the feature-mapping tearsheet is not opened, enrichment is not requested, and keyboard focus moves to that field

#### Scenario: Required connection and credential fields
- **WHEN** a Weaviate field required for the current connection type or authentication method is empty or invalid, such as a missing host, a port outside 1-65535, a missing cluster URL, or a missing credential
- **THEN** an inline error message is displayed on that field, attached to it for assistive technology, and the feature-mapping tearsheet is not opened

#### Scenario: Authenticated plaintext connection blocked
- **WHEN** the Weaviate connection type is custom, the authentication method is not "none", and the HTTP TLS setting is off or the effective gRPC TLS setting is off
- **THEN** an error alert explains that both HTTP and gRPC must use TLS when authentication is configured, the controls involved are marked invalid, and the feature-mapping tearsheet is not opened and enrichment is not requested

#### Scenario: Blocked open moves focus
- **WHEN** the user activates "Add / Edit feature mappings" while the Weaviate configuration is invalid
- **THEN** keyboard focus moves to the first invalid field and its error is announced

#### Scenario: Advanced JSON preserved
- **WHEN** the user has entered additional keys in the Advanced `provider_config` JSON and then changes the connection type or authentication method
- **THEN** only the keys belonging to the inactive mode or method are removed, and all other keys remain

#### Scenario: Index parameters stay in Advanced JSON
- **WHEN** a Weaviate node's `provider_config` contains `index_type` or `index_parameters`
- **THEN** both keys remain visible and editable in the Advanced JSON, are preserved when the node is saved and reopened, and are omitted from enrichment requests

#### Scenario: Collection name rule for Weaviate
- **WHEN** the user enters a new Weaviate collection name in the tearsheet
- **THEN** the names below are accepted or rejected as listed, each rejection shows the Weaviate naming message, saving is blocked while the name is invalid, and the input placeholder is a valid example name

| Collection name | Result |
|---|---|
| `DocumentChunks` | accepted |
| `Docs_2025` | accepted |
| `A` | accepted |
| `documentChunks` | rejected |
| `2Docs` | rejected |
| `Doc-Chunks` | rejected |
| `Doc Chunks` | rejected |
| (empty) | rejected |

#### Scenario: Distance metric without engine selector
- **WHEN** the tearsheet is opened for a Weaviate node
- **THEN** a distance metric selector offers the metrics the backend publishes (cosine, dot, l2-squared, manhattan, hamming), no engine selector is displayed, and the selected metric is saved as `distance_metric`
- **AND WHEN** an existing collection reports a stored metric
- **THEN** that metric is selected and shown read-only, including `l2-squared`, and an unrecognized value is shown unlabeled rather than hidden

#### Scenario: BM25 option driven by provider capability
- **WHEN** the tearsheet is opened for a provider that supports sparse retrieval and the selected resource is supported
- **THEN** a BM25 checkbox is displayed, labeled as BM25 keyword retrieval rather than stored sparse vectors for Weaviate
- **AND WHEN** the provider does not support sparse retrieval
- **THEN** the checkbox is not displayed

#### Scenario: BM25 option for an eligible unsupported collection
- **WHEN** a Weaviate node's selected collection is reported unsupported with `sparse_eligible` true and BM25 is unchecked
- **THEN** the unsupported reason and the BM25 checkbox are both displayed, and checking it re-requests enrichment, which then reports the collection as supported

#### Scenario: BM25 option hidden for an ineligible collection
- **WHEN** the selected collection is reported unsupported and `sparse_eligible` is not true
- **THEN** only the unsupported state is displayed and the BM25 checkbox is not

#### Scenario: Saved BM25 state preserved
- **WHEN** a node was saved with BM25 enabled and the user reopens the tearsheet
- **THEN** the checkbox is checked, and toggling it re-requests enrichment with the new setting while discarding any superseded response

#### Scenario: Enrichment states for Weaviate
- **WHEN** the tearsheet requests enrichment for a Weaviate node
- **THEN** a loading indicator is shown while the request is pending, an empty list of collections shows an empty state, and a collection reported as unsupported shows the unsupported state with its reason
- **AND** closing the tearsheet before the response arrives cancels the update without error

#### Scenario: Enrichment failure shown
- **WHEN** the enrichment response carries `is_docpipe_supported_resource.error`, or the enrichment request throws
- **THEN** an error message with that reason is displayed, distinct from the empty-collections state, and the node is not shown as an unsupported collection

#### Scenario: Keyboard operation and focus
- **WHEN** the user operates the panel and the tearsheet with the keyboard only
- **THEN** every new control is reachable in visual order, dropdowns operate with arrow keys and Enter, the credential visibility toggle is operable, the tearsheet keeps focus inside while open, and Escape closes it

#### Scenario: Localized strings
- **WHEN** the panel renders a new Weaviate label, helper text, option label, or error message
- **THEN** the text comes from the localization catalogue, which is generated by the message-extraction script rather than edited by hand

#### Scenario: OpenSearch and Milvus unchanged
- **WHEN** the user opens a node with provider OpenSearch or Milvus, configures it, and saves it
- **THEN** the displayed fields, the engine and similarity controls, the sparse option (Milvus only), the Advanced JSON handling, and the saved `provider_config` are the same as before this change
