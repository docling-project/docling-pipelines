# Spec Delta

## ADDED Requirements

### Requirement: Startup validation uses detection validation
At operator startup, each PII or HAP provider SHALL be validated through its detection validation, and the validation result SHALL report the `detection` context. This SHALL hold for providers backed by an adapter that also supports inference or embeddings, including `watsonx`. Invalid configuration SHALL stop execution before any document is processed.

#### Scenario: WatsonX validation reports the detection context
- **WHEN** a flow configures `pii_and_hap` with a `watsonx` provider and the operator validates it at startup
- **THEN** the validation result has `context` set to `detection`

#### Scenario: WatsonX configuration error
- **WHEN** the `watsonx` provider configuration has no `api_key`
- **THEN** startup fails with an error naming the missing `api_key` and no document is processed

### Requirement: WatsonX detection contacts the service only when detecting
Creating or validating the `watsonx` provider SHALL NOT call the WatsonX detection API or request an IAM token. The first call to the service SHALL happen when text is first submitted for detection.

#### Scenario: Provider created and validated
- **WHEN** a `watsonx` provider is created and validated and no text has been submitted
- **THEN** no IAM token request and no detection request are made

### Requirement: WatsonX credential refresh after authentication failure
After a WatsonX detection request fails with HTTP 401 or 403, the next detection request SHALL obtain a new IAM token. A failure with any other status or a network error SHALL NOT discard the token. Otherwise the IAM token SHALL be reused across detection requests.

#### Scenario: Authentication failure
- **WHEN** a detection request fails with HTTP 401 and a second request is then made
- **THEN** the second request uses a newly obtained IAM token

#### Scenario: Other failure
- **WHEN** a detection request fails with HTTP 500 and a second request is then made
- **THEN** the second request reuses the previous IAM token

#### Scenario: Repeated detection
- **WHEN** several detection requests succeed in a row
- **THEN** one IAM token request is made for all of them
