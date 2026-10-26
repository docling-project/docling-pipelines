# Environment Configuration

Copy the example env file and edit it with your connection details:

```bash
cp .env.example .env
```

## Environment Variable Reference

### Connection

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENSEARCH_HOST` | string | `localhost` | OpenSearch server hostname or IP |
| `OPENSEARCH_PORT` | integer | `9200` | OpenSearch server port |
| `OPENSEARCH_USE_SSL` | boolean | `false` | Enable SSL/TLS connection |
| `OPENSEARCH_VERIFY_CERTS` | boolean | `false` | Verify SSL certificates |

### Authentication

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENSEARCH_USERNAME` | string | — | Username for authentication |
| `OPENSEARCH_PASSWORD` | string | — | Password for authentication |
| `OPENSEARCH_AWS_AUTH` | boolean | `false` | Use AWS IAM authentication |
| `OPENSEARCH_AWS_REGION` | string | `us-east-1` | AWS region (when using AWS auth) |

### Engine

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENSEARCH_ENGINE` | string | `faiss` | KNN engine (`faiss`, `lucene`, `nmslib`) |
| `OPENSEARCH_ALGORITHM` | string | `hnsw` | Search algorithm (`hnsw`, `ivf`) |
| `OPENSEARCH_SPACE_TYPE` | string | `l2` | Distance metric (`l2`, `cosine`, `inner_product`) |
| `OPENSEARCH_VECTOR_DIMENSION` | integer | `384` | Vector embedding dimension |

### Index & Performance

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENSEARCH_INDEX_NAME` | string | `docpipe_test` | Name of the OpenSearch index |
| `OPENSEARCH_DOC_ID_COLUMN` | string | `doc_id_hash` | Column name for document IDs |
| `OPENSEARCH_EMBEDDINGS_COLUMN` | string | `embeddings` | Column name for vector embeddings |
| `OPENSEARCH_BATCH_SIZE` | integer | `100` | Documents per batch |
