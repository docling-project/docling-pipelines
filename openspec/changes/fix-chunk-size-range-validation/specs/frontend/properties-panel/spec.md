## ADDED Requirements

### Requirement: Chunker chunk size range validation
The Chunker panel SHALL validate chunk size against the range of the selected chunk type (Simple: 500-5000 characters, Hybrid: 100-2048 tokens), skip validation for Semantic, and show the localized range message inline while the value is out of range. It SHALL revalidate when chunk size or chunk type changes.

#### Scenario: Value below the minimum
- **WHEN** the chunk type is Simple and the chunk size is 499
- **THEN** the chunk size input is invalid and shows "Range allowed: 500-5000"

#### Scenario: Value above the maximum
- **WHEN** the chunk type is Hybrid and the chunk size is 2049
- **THEN** the chunk size input is invalid and shows "Range allowed: 100-2048"

#### Scenario: Boundary values are accepted
- **WHEN** the chunk size equals the minimum or the maximum of the selected chunk type
- **THEN** no validation message is shown

#### Scenario: Error clears on valid input
- **WHEN** the user replaces an out-of-range chunk size with a value inside the range
- **THEN** the inline validation message is removed

#### Scenario: Switching chunk type revalidates
- **WHEN** the chunk size is 3000 and the user switches the chunk type from Simple to Hybrid
- **THEN** the chunk size input becomes invalid and shows "Range allowed: 100-2048"
- **AND WHEN** the user switches back to Simple
- **THEN** the validation message is removed

#### Scenario: Semantic chunking ignores chunk size
- **WHEN** the chunk type is Semantic and a stored chunk size is outside the Simple and Hybrid ranges
- **THEN** no chunk size validation is applied and Save is not blocked by it

### Requirement: Save blocked while chunk size is invalid
The Save button SHALL be disabled while the Chunker chunk size is outside the range for the selected chunk type, in addition to the existing required-parameter gating. Save SHALL be enabled again once the value is valid and no required parameter is missing.

#### Scenario: Save disabled for out-of-range chunk size
- **WHEN** the chunk size is outside the supported range for the selected chunk type
- **THEN** the Save button is disabled

#### Scenario: Save enabled after correction
- **WHEN** the user corrects the chunk size to a value inside the supported range
- **THEN** the Save button is enabled, provided no required parameter is missing

#### Scenario: Save state follows chunk type changes
- **WHEN** the user switches the chunk type so the existing chunk size falls outside (or inside) the new range
- **THEN** the Save button is disabled (or enabled) accordingly
