# Spec Delta

## ADDED Requirements

### Requirement: Custom operator changes require administrator
Creating, updating and deleting custom operators SHALL require the `admin` role, because an upload runs arbitrary code in the pipeline runtime. Listing and reading operators SHALL remain available to any authenticated caller.

#### Scenario: Editor upload refused
- **WHEN** an editor posts a valid `.py` operator to `POST /api/v1/custom_operators`
- **THEN** the response is 403 and the operator is not stored

#### Scenario: Editor update and delete refused
- **WHEN** an editor calls `PATCH` or `DELETE` on a custom operator
- **THEN** the response is 403

#### Scenario: Viewer can list
- **WHEN** a viewer calls `GET /api/v1/custom_operators`
- **THEN** the response is 200

#### Scenario: Admin upload allowed
- **WHEN** an admin posts a valid operator
- **THEN** the response is 201
