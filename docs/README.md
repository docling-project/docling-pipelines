# Docling Pipelines Documentation

Welcome to the Docling Pipelines documentation! This guide will help you navigate our comprehensive documentation and find exactly what you need.

## 📚 Documentation Book

The [Docling-pipelines Book](book/site/docling-pipelines/1.0/index.html) is a 12-chapter guide covering architecture, installation, flow authoring, document processing, vector storage, LLM integration, deployment, and more. It is authored in AsciiDoc and built with Antora into a static website (hosted on GitHub Pages) and a PDF.

## 🚀 Getting Started

**New to Docling Pipelines?** Start here:

- **[Quick Start Guide](../QUICKSTART.md)** - Get your first pipeline running in 5 minutes
- **[Complete Setup Guide](../USER_GUIDE_PIPELINE_SETUP.md)** - Detailed installation and configuration
- **[Troubleshooting Guide](../TROUBLESHOOTING.md)** - Solutions to common issues

## 📖 Guides

Task-oriented guides to help you accomplish specific goals:

### Core Guides
- **[Flow Authoring Format](guides/FLOW_AUTHORING_FORMAT.md)** - Learn the simplified flow authoring format
- **[Flow Configuration Guide](guides/FLOW_CONFIGURATION_GUIDE.md)** - Complete flow configuration reference
- **[Python API Guide](guides/PYTHON_API_GUIDE.md)** - Use Docling Pipelines programmatically

### Developer Guides
- **[Create Connector Guide](guides/CREATE_CONNECTOR_GUIDE.md)** - Build custom data source connectors
- **[Custom Operators Guide](guides/CUSTOM_OPERATORS_GUIDE.md)** - Create your own operators
- **[External Operator Integration](guides/EXTERNAL_OPERATOR_INTEGRATION.md)** - Integrate external operators
- **[Testing Standards](guides/TESTING_STANDARDS.md)** - Coverage requirements, test organisation, fixtures, and naming conventions

### Advanced Topics
- **[Advanced Configuration](guides/ADVANCED_CONFIGURATION.md)** - Production deployment and optimization
- **[Event Streaming Guide](guides/EVENT_STREAMING_GUIDE.md)** - Kafka event-driven execution and routing-key mappings
- **[Telemetry Setup](guides/TELEMETRY_SETUP.md)** - OpenTelemetry distributed tracing and metrics
- **[OpenLineage Integration](integrations/openlineage/OPENLINEAGE_GUIDE.md)** - Data lineage events for flow and operator runs, viewable in Marquez
- **[Job Report Generation](guides/JOB_REPORT_GENERATION.md)** - Automated per-run CSV job reports
- **[Security Best Practices](guides/SECURITY_BEST_PRACTICES.md)** - Credential management, authentication, ACL, and production hardening
- **[Unified LLM Architecture](guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md)** - LLM integration patterns
- **[Document Libraries](guides/USER_GUIDE_DOCUMENT_LIBRARIES.md)** - Managing document collections
- **[Document Class Utils](guides/DOCUMENT_CLASS_UTILS.md)** - Document schema utilities
- **[Vault Integration](guides/VAULT_INTEGRATION_GUIDE.md)** - HashiCorp Vault secret resolution via `vault://` URIs
- **[UI User Guide](guides/UI_USER_GUIDE.md)** - Using the React frontend

### Best Practices
- **[Logging Best Practices](guides/LOGGING_BEST_PRACTICES.md)** - Security-first logging, sensitive data handling, and NFR Point 12 compliance

## ⚙️ Operator Configurations

Configuration examples and patterns for all operators:

### Core Pipeline Operators
- **[IngestSource](operators/ingest/ingest_source_readme.md)** - Ingest documents from local filesystem or external sources (S3, SharePoint, etc.)
- **[Extract](operators/extract/extract_operator_readme.md)** - Extract text and entities from documents
- **[Chunker](operators/functional/chunker_readme.md)** - Split documents into chunks
- **[Embeddings](operators/functional/embeddings_readme.md)** - Generate vector embeddings
- **[VectorDB](operators/vectordb/)** - Store vectors in OpenSearch or Milvus
- **[StorageOutput](operators/storage/storage_output_readme.md)** - Write documents to a file destination (filesystem, etc.)

### All Operator Configurations
Browse the complete list of operator configuration examples in the [operators/](operators/) directory.

## 📚 Reference

Quick lookup documentation for parameters and APIs:

- **[Global Configuration Reference](reference/GLOBAL_CONFIG.md)** - Flow-level configuration parameters
- **[Operator Reference](reference/OPERATORS.md)** - Complete operator parameter specifications
- **[Document Schemas](reference/DOCUMENT_SCHEMAS.md)** - Document class schema definitions

## 🌐 REST API

Documentation for the Docling Pipelines REST API server:

- **[REST API Server](api/REST_API_SERVER.md)** - Server setup, all endpoints, authentication, and security overview
- **[Document Retrieval API](api/ACL_DOCUMENT_RETRIEVAL.md)** - ACL-based document retrieval endpoints
- **[OAuth2 Authentication](api/OAUTH2_AUTHENTICATION.md)** - OAuth2 and OIDC authentication setup

## 🔌 Integrations

Integration-specific documentation:

- **[OpenLineage](integrations/openlineage/OPENLINEAGE_GUIDE.md)** - Data lineage tracking via the OpenLineage standard
- **[OpenSearch](integrations/opensearch/)** - Vector storage with OpenSearch
  - [Quick Start](integrations/opensearch/OPENSEARCH_QUICKSTART.md)
  - [Environment Setup](integrations/opensearch/ENVIRONMENT_SETUP.md)
  - [Schema Templates](integrations/opensearch/SCHEMA_TEMPLATES.md)
- **[Milvus](integrations/milvus/)** - Vector storage with Milvus
- **[Prefect](integrations/prefect/)** - Distributed execution with Prefect
  - [Distributed Execution Guide](integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md)

## 🛠️ Contributing

Resources for contributors:

- **[Contributing Guide](../CONTRIBUTING.md)** - How to contribute to Docling Pipelines
- **[Documentation Style Guide](guides/DOCUMENTATION_STYLE_GUIDE.md)** - Formatting, Mermaid, and writing conventions for all contributors

## 🔬 Internals

Internal documentation for maintainers:

- **[Metadata Aggregation Strategy](internals/NODE_METADATA_AGGREGATION_STRATEGY.md)** - Metadata aggregation in micro-batching
- **[Document Libraries Architecture](internals/DOCUMENT_LIBRARIES_ARCHITECTURE.md)** - Document library system design
- **[Unified Asset Architecture](internals/UNIFIED_ASSET_ARCHITECTURE.md)** - Complete reference for the common asset layer: domain models, ports, adapters, factories, and service wiring

## 🚀 Deployment

Deployment guides for production environments:

- **[Docker Compose Deployment](deployment/DOCKER_COMPOSE.md)** - Run Docling Pipelines locally or in containers with Docker Compose
- **[OpenShift Deployment](deployment/OPENSHIFT.md)** - Deploy Docling Pipelines on OpenShift

## 💡 Architecture

Understand how Docling Pipelines works:

- **[Architecture Overview](../ARCHITECTURE.md)** - System design and operator catalog

## 📋 Documentation Organization

Our documentation is organized by user journey:

```
docs/
├── guides/              # How-to guides (task-oriented)
├── operators/           # Operator configuration examples
├── reference/           # Parameter and API lookups
├── api/                 # REST API documentation
├── integrations/        # Integration-specific docs (OpenLineage, OpenSearch, Milvus, Prefect, Vault)
├── internals/           # Internal maintainer docs
└── deployment/          # Deployment guides
```

**Note:** Comprehensive operator documentation (architecture, implementation details) is located in the source code directories at `src/docpipe/core/operators/*/README.md`.

## 🔍 Finding What You Need

**I want to...**

- **Get started quickly** → [Quick Start Guide](../QUICKSTART.md)
- **Set up my environment** → [Complete Setup Guide](../USER_GUIDE_PIPELINE_SETUP.md)
- **Write my first flow** → [Flow Authoring Format](guides/FLOW_AUTHORING_FORMAT.md)
- **Look up a parameter** → [Global Config Reference](reference/GLOBAL_CONFIG.md) or [Operator Reference](reference/OPERATORS.md)
- **See operator config examples** → [Operator Configs Directory](operators/)
- **Understand operator internals** → Check `src/docpipe/core/operators/*/README.md` in source code
- **Use the Python API** → [Python API Guide](guides/PYTHON_API_GUIDE.md)
- **Use the REST API** → [REST API Server](api/REST_API_SERVER.md)
- **Set up OAuth2 authentication** → [OAuth2 Authentication Guide](api/OAUTH2_AUTHENTICATION.md)
- **Create a custom connector** → [Create Connector Guide](guides/CREATE_CONNECTOR_GUIDE.md)
- **Track data lineage** → [OpenLineage Integration Guide](integrations/openlineage/OPENLINEAGE_GUIDE.md)
- **Secure my deployment** → [Security Best Practices](guides/SECURITY_BEST_PRACTICES.md)
- **Deploy to production** → [Advanced Configuration](guides/ADVANCED_CONFIGURATION.md)
- **Troubleshoot an issue** → [Troubleshooting Guide](../TROUBLESHOOTING.md)
- **Contribute code** → [Contributing Guide](../CONTRIBUTING.md)

## 📞 Need Help?

- Check the [Troubleshooting Guide](../TROUBLESHOOTING.md) for common issues
- Review the [Architecture Overview](../ARCHITECTURE.md) to understand system design
- Browse [operator configuration examples](operators/) for usage patterns
- Check existing GitHub issues or create a new one

---

**Happy data processing! 🚀**
