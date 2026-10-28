# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Ollama Embeddings Adapter for LangChain Integration.

Provides an adapter class that makes OllamaClient compatible with LangChain's
Embeddings interface, enabling seamless integration with LangChain components
like SemanticChunker while maintaining consistency with the project's existing
Ollama infrastructure.
"""

from langchain_core.embeddings import Embeddings

from docpipe.integrations.ollama.client import OllamaClient


class OllamaClientEmbeddings(Embeddings):
    """
    Adapter to make OllamaClient compatible with LangChain's Embeddings interface.

    This adapter allows the project's OllamaClient to be used with LangChain components
    like SemanticChunker, ensuring consistency across the codebase and reusing the
    existing Ollama integration infrastructure.

    Attributes:
        client: The OllamaClient instance used for generating embeddings

    Example:
        >>> from docpipe.integrations.ollama.client import OllamaClient
        >>> from docpipe.integrations.ollama.embeddings import OllamaClientEmbeddings
        >>>
        >>> ollama_client = OllamaClient(model_name="nomic-embed-text")
        >>> embeddings = OllamaClientEmbeddings(ollama_client)
        >>>
        >>> # Use with LangChain components
        >>> from langchain_experimental.text_splitter import SemanticChunker
        >>> chunker = SemanticChunker(embeddings=embeddings)
    """

    def __init__(self, client: OllamaClient):
        """
        Initialize the adapter with an OllamaClient instance.

        Args:
            client: OllamaClient instance configured with an embedding model
        """
        self.client = client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple documents.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (list of floats) for each text
        """
        return [self.client.generate_embeddings(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """
        Generate embedding for a single query text.

        Args:
            text: Text string to embed

        Returns:
            Embedding vector as list of floats
        """
        return self.client.generate_embeddings(text)
