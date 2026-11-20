# Spec Delta

## ADDED Requirements

### Requirement: Isolated worker is spawned with an allowlisted environment
The environment supplied when spawning a custom-operator worker under `custom_operators.isolation: process` SHALL contain only the allowlisted variables plus the variables the parent sets to operate the worker, and none of those SHALL carry a secret. Variables the operating system or the Python runtime add to a started process are outside this guarantee.

#### Scenario: Spawn environment is exact
- **WHEN** the parent builds the environment for a worker
- **THEN** it contains only allowlisted names present in the parent environment plus the parent-set control variables

#### Scenario: Credential variables in the parent are still dropped
- **WHEN** the parent environment holds credential-like variables outside the allowlist
- **THEN** the worker's environment does not contain them

### Requirement: Isolated worker does not auto-load a .env file
A custom-operator worker SHALL NOT load a `.env` file, from the repository root or any other location, as a side effect of importing application modules, so no dotenv-derived variable appears in its environment.

#### Scenario: Discoverable .env with a credential
- **WHEN** a `.env` file that defines a credential-like variable is discoverable from the application source tree and a worker is started
- **THEN** the worker's environment does not contain that variable or its value

### Requirement: Application processes keep loading .env
Unless dotenv loading is explicitly disabled (for example with `PYTHON_DOTENV_DISABLED=1`), processes that are not isolated workers (REST API, command line, `DocpipeFlowManager`, Prefect workers) SHALL continue to load a discoverable `.env` file at start-up without overriding variables already set in the process environment.

#### Scenario: Application process with a .env
- **WHEN** the application starts outside an isolated worker, dotenv loading is not disabled, and a `.env` file is discoverable
- **THEN** its variables are available to application configuration, and a variable already set in the environment keeps its existing value

#### Scenario: Application opt-out is honored
- **WHEN** an application process starts with `PYTHON_DOTENV_DISABLED=1`
- **THEN** no `.env` file is loaded

### Requirement: Documentation states the limit of the guarantee
The secrets guide SHALL state that the isolated worker does not load `.env`, and that a file readable by the worker's operating-system user can still be read by explicit access, which a distinct worker user and restricted file permissions address.

#### Scenario: Guide read
- **WHEN** the secrets guide section on isolation is read
- **THEN** it names `.env` loading, the worker environment guarantee and the file-permission precondition
