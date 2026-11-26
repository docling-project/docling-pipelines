# Spec Delta

## ADDED Requirements

### Requirement: Startup validation uses detection validation
At operator startup, each PII or HAP provider SHALL be validated through its detection validation, and the validation result SHALL report the `detection` context and list configuration errors on failure. This SHALL hold for providers backed by an adapter that also supports inference or embeddings, including `watsonx`.

#### Scenario: WatsonX validation reports the detection context
- **WHEN** a flow configures `pii_and_hap` with a `watsonx` provider and the operator validates it at startup
- **THEN** the validation result has `context` set to `detection`

#### Scenario: WatsonX configuration error
- **WHEN** the `watsonx` provider configuration has no `api_key`
- **THEN** validation fails with an error naming the missing `api_key`

### Requirement: WatsonX detection contacts the service only when detecting
Creating or validating the `watsonx` provider SHALL NOT call the WatsonX detection API or request an IAM token. The first call to the service SHALL happen when text is first submitted for detection.

#### Scenario: Provider created and validated
- **WHEN** a `watsonx` provider is created and validated and no text has been submitted
- **THEN** no IAM token request and no detection request are made

### Requirement: WatsonX authentication token lifecycle
WatsonX detection requests SHALL use cached IAM tokens managed by the token manager, which auto-refreshes tokens before expiration and reuses valid tokens across detection requests.

#### Scenario: Repeated detection
- **WHEN** several detection requests succeed within the token validity period
- **THEN** one IAM token request is made for all of them

#### Scenario: Token auto-refresh before expiry
- **WHEN** a detection request is made with an expired or expiring token
- **THEN** a new IAM token is obtained automatically
