# Spec Delta

## Purpose

Milvus query-time collection loading and query failure reporting for the `vectordb` operator's Milvus adapter. It defines when the adapter loads a collection before querying it, and how a failed query is reported, so that stale-chunk and soft-delete cleanup cannot mistake a failure for an empty result. The operator-level cleanup contract lives in `backend/vectordb-operator`; this delta adds the Milvus adapter's guarantees it depends on.

## ADDED Requirements

### Requirement: Milvus collection loaded before queries
The Milvus adapter SHALL load a collection that is not `Loaded` before querying it, SHALL NOT load one that already is, and SHALL NOT query a collection that does not exist. It SHALL re-check the state only when a query fails on a previously cached state.

#### Scenario: Reopened collection loaded before query
- **WHEN** a query is issued against a collection whose state is `NotLoad`, for example after the collection is reopened in a new process
- **THEN** the adapter loads the collection and then runs the query, and the query returns the matching records

#### Scenario: Already loaded collection not reloaded
- **WHEN** a query is issued against a collection whose state is `Loaded`
- **THEN** the adapter runs the query without issuing a load

#### Scenario: Repeated queries check load state once
- **WHEN** several queries are issued through the same adapter instance after a successful load
- **THEN** the load state is checked once and no further load is issued

#### Scenario: Missing collection returns empty without querying
- **WHEN** a query is issued against a collection that does not exist
- **THEN** the adapter returns an empty result and does not issue the query

#### Scenario: Collection released while the adapter is in use
- **WHEN** another client releases a collection after the adapter has queried it, and the adapter queries it again
- **THEN** the adapter loads the collection again and the query returns the matching records

#### Scenario: Collection dropped while the adapter is in use
- **WHEN** another client drops a collection after the adapter has queried it, and the adapter queries it again
- **THEN** the adapter returns an empty result without raising

#### Scenario: Collection recreated while the adapter is in use
- **WHEN** another client drops and recreates a collection after the adapter has queried it, and the adapter queries it again
- **THEN** the adapter loads the new collection and the query returns its records

#### Scenario: Genuine failure on a loaded collection is not retried
- **WHEN** a query fails while the collection is still `Loaded`, or its load state cannot be read
- **THEN** the adapter raises the query failure without issuing the query a second time

### Requirement: Milvus query failures are surfaced
The Milvus adapter SHALL raise a `DocpipeException` with status 500 and error code `OPERATOR_EXECUTION_FAILED` when a collection cannot be loaded, or when a query against an existing collection fails. The adapter MUST NOT convert these failures into an empty result, because an empty result is a valid outcome of a successful query that matched no records. The exception SHALL chain the original error.

#### Scenario: Load failure raises
- **WHEN** `load_collection` fails for an existing collection
- **THEN** the adapter raises a `DocpipeException` with status 500 and error code `OPERATOR_EXECUTION_FAILED`, the query is not issued, and the original error is chained

#### Scenario: Load state read failure raises
- **WHEN** the collection load state cannot be read
- **THEN** the adapter raises a `DocpipeException` with status 500 and error code `OPERATOR_EXECUTION_FAILED` and does not issue the query

#### Scenario: Query failure raises rather than returning empty
- **WHEN** a document query against a loaded collection fails
- **THEN** the adapter raises a `DocpipeException` with status 500 and error code `OPERATOR_EXECUTION_FAILED` instead of returning an empty list

#### Scenario: Successful query with no matches is empty
- **WHEN** a document query against a loaded collection succeeds but matches no records
- **THEN** the adapter returns an empty list without raising

#### Scenario: Partial chunk lookup is never returned
- **WHEN** the chunk primary key lookup for one of several file IDs fails
- **THEN** the adapter raises a `DocpipeException` and does not return the chunk primary keys found for the other file IDs

### Requirement: Milvus Lite query loading
The Milvus adapter SHALL apply the collection loading and query failure requirements to Milvus Lite (`auth_type: "lite"`) collections, using the same load and query calls it uses for server deployments.

#### Scenario: Lite collection reopened from disk
- **WHEN** a Milvus Lite database file containing a collection is reopened by a new process and a query is issued against that collection
- **THEN** the adapter loads the collection before the query and the query returns the matching records

#### Scenario: Lite collection not yet created
- **WHEN** a Milvus Lite database is opened and the configured collection does not exist
- **THEN** stale-chunk and soft-delete lookups return an empty result without failing
