# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for Ollama embeddings adapter."""

from unittest.mock import MagicMock

from langchain_core.embeddings import Embeddings

from docpipe.integrations.ollama.embeddings import OllamaClientEmbeddings


class TestOllamaClientEmbeddings:
    """Test suite for OllamaClientEmbeddings adapter."""

    def test_implements_langchain_embeddings_interface(self):
        mock_client = MagicMock()
        adapter = OllamaClientEmbeddings(client=mock_client)
        assert adapter.client is mock_client
        assert isinstance(adapter, Embeddings)

    def test_embed_documents_single_and_multiple(self):
        mock_client = MagicMock()
        mock_client.generate_embeddings.side_effect = lambda text: [float(len(text)), 1.0, 2.0]

        adapter = OllamaClientEmbeddings(client=mock_client)
        texts = ["hello", "world", "testing"]
        results = adapter.embed_documents(texts)

        assert len(results) == 3
        assert results[0] == [5.0, 1.0, 2.0]
        assert results[1] == [5.0, 1.0, 2.0]
        assert results[2] == [7.0, 1.0, 2.0]
        assert mock_client.generate_embeddings.call_count == 3

    def test_embed_documents_empty_list(self):
        mock_client = MagicMock()
        adapter = OllamaClientEmbeddings(client=mock_client)
        results = adapter.embed_documents([])

        assert results == []
        mock_client.generate_embeddings.assert_not_called()

    def test_embed_query(self):
        mock_client = MagicMock()
        mock_client.generate_embeddings.return_value = [0.1, 0.2, 0.3, 0.4]

        adapter = OllamaClientEmbeddings(client=mock_client)
        result = adapter.embed_query("search query")

        assert result == [0.1, 0.2, 0.3, 0.4]
        mock_client.generate_embeddings.assert_called_once_with("search query")
