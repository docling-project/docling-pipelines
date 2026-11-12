# Vector Database Synchronization

When documents are split into chunks and embedded, each chunk receives a unique primary key.
Vector database operators must correlate parent document IDs with individual chunk identifiers.
This enables bulk deletion and purging of orphan embeddings when documents are modified or removed.
