# Spec Delta

## MODIFIED Requirements

### Requirement: Third-party error text is sanitized
Every exception that can carry a secret value SHALL be sanitized before its text reaches a log, a node or job message, run metadata, or a REST response. Configuration-model validation errors SHALL be rendered without input values, and errors from client, HTTP, and database libraries SHALL be reduced to a fixed category and the config key path. This applies to every ACL operator exception site that writes to a log, to a raised exception message, or to run-metadata `reason`, on both the `fail_on_error` true and false paths, and not only to adapter initialization. Sanitization SHALL consider the whole cause and context graph of the exception, not only its outermost type: every `__cause__` and `__context__` branch and every `ExceptionGroup` member, at any depth. Sensitivity detection SHALL report an exception as sensitive whenever the formatted traceback of that exception would print the text of a classified link.

#### Scenario: Validation error on a resolved field
- **WHEN** an adapter configuration model rejects a resolved value, for example an S3 `endpoint_url` that lacks a scheme
- **THEN** the recorded reason names the config key and the constraint and does not contain the value

#### Scenario: Client connection failure
- **WHEN** a connection fails after credentials were resolved from Vault
- **THEN** the reported error and the run metadata do not contain the credential, a derived `user:password` string, or a URL carrying credentials

#### Scenario: Job-level message
- **WHEN** a node fails and the orchestrator stores the error as the job message
- **THEN** the stored message has passed through the sanitizer and contains no secret value

#### Scenario: ACL per-document failure reason
- **WHEN** an ACL extraction for one document raises an exception whose text carries a credential or an input value
- **THEN** the failed-document `reason` recorded in run metadata and the log record for that document contain the sanitized text and do not contain the raw exception text

#### Scenario: Sensitive link shadowed or deep in the chain
- **WHEN** an exception has a `ValidationError` reachable only through `__context__` while `__cause__` is another exception, or reachable only at a depth greater than ten links, or inside an `ExceptionGroup` member
- **THEN** the sanitizer reports the exception as sensitive and `sanitize_exception` output does not contain the rejected input or the exception text of that link

#### Scenario: Unclassified link between the wrapper and a classified link
- **WHEN** a wrapper exception whose message embeds a secret is chained to a classified exception, which is in turn chained to an unclassified exception carrying the same secret text
- **THEN** `sanitize_exception` output, the ACL log records, the raised wrapper message and its stand-in cause do not contain the secret, and a message that only partially copies the secret is reduced to the fixed category
