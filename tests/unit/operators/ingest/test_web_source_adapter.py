#!/usr/bin/env python3

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from docpipe.core.operators.ingest.adapters.outbound.sources.web.adapter import (
    WebPageSourceAdapter,
)
from docpipe.core.operators.ingest.adapters.outbound.sources.web.config import (
    WebPageSourceConfig,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.utils.core.docpipe_utils import generate_hex_digest


async def collect_async(async_gen):
    """Helper to collect async generator results."""
    return [item async for item in async_gen]


class TestWebPageSourceConfig:
    """Test suite for WebPageSourceConfig validation."""

    def test_valid_config_with_single_url(self):
        """Test creating config with a single valid URL."""
        config = WebPageSourceConfig(
            urls=["https://example.com"],
            max_depth=2,
            prevent_outside=True,
            exclude_patterns=["/admin", "/login"],
            timeout=30,
        )
        assert config.urls == ["https://example.com"]
        assert config.max_depth == 2
        assert config.prevent_outside is True
        assert config.exclude_patterns == ["/admin", "/login"]
        assert config.timeout == 30

    def test_valid_config_with_multiple_urls(self):
        """Test creating config with multiple valid URLs."""
        config = WebPageSourceConfig(
            urls=["https://example.com", "https://test.com"],
            max_depth=1,
        )
        assert len(config.urls) == 2
        assert "https://example.com" in config.urls
        assert "https://test.com" in config.urls

    def test_url_validation_requires_http_protocol(self):
        """Test that URLs must start with http:// or https://."""
        with pytest.raises(ValueError, match="URL must start with http:// or https://"):
            WebPageSourceConfig(urls=["example.com"])

    def test_url_validation_rejects_empty_strings(self):
        """Test that empty URL strings are rejected."""
        with pytest.raises(ValueError, match="URLs cannot be empty strings"):
            WebPageSourceConfig(urls=[""])

    def test_url_validation_requires_at_least_one_url(self):
        """Test that at least one URL must be provided."""
        with pytest.raises(ValidationError, match="at least 1 item"):
            WebPageSourceConfig(urls=[])

    def test_url_validation_strips_whitespace(self):
        """Test that URLs are stripped of whitespace."""
        config = WebPageSourceConfig(urls=["  https://example.com  "])
        assert config.urls == ["https://example.com"]

    def test_max_depth_validation_rejects_negative(self):
        """Test that negative max_depth is rejected."""
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            WebPageSourceConfig(urls=["https://example.com"], max_depth=-1)

    def test_max_depth_validation_rejects_excessive(self):
        """Test that max_depth > 10 is rejected."""
        with pytest.raises(ValidationError, match="less than or equal to 10"):
            WebPageSourceConfig(urls=["https://example.com"], max_depth=11)

    def test_max_depth_allows_zero(self):
        """Test that max_depth=0 is allowed (no recursion)."""
        config = WebPageSourceConfig(urls=["https://example.com"], max_depth=0)
        assert config.max_depth == 0

    def test_timeout_validation_rejects_zero(self):
        """Test that timeout must be at least 1 second."""
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            WebPageSourceConfig(urls=["https://example.com"], timeout=0)

    def test_timeout_validation_rejects_excessive(self):
        """Test that timeout > 300 seconds is rejected."""
        with pytest.raises(ValidationError, match="less than or equal to 300"):
            WebPageSourceConfig(urls=["https://example.com"], timeout=301)

    def test_exclude_patterns_strips_whitespace(self):
        """Test that exclude patterns are stripped of whitespace."""
        config = WebPageSourceConfig(
            urls=["https://example.com"],
            exclude_patterns=["  /admin  ", "/login", "  "],
        )
        assert config.exclude_patterns == ["/admin", "/login"]

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = WebPageSourceConfig(urls=["https://example.com"])
        assert config.max_depth == 2
        assert config.prevent_outside is True
        assert config.exclude_patterns == []
        assert config.timeout == 30
        assert config.extractor is None


class TestWebPageSourceAdapter:
    """Test suite for WebPageSourceAdapter."""

    def make_config(self, *, urls=None, **kwargs):
        """Helper to create a test config."""
        if urls is None:
            urls = ["https://example.com"]
        return WebPageSourceConfig(urls=urls, **kwargs)

    def test_adapter_registration(self):
        """Test that adapter is registered with correct metadata."""
        adapter = WebPageSourceAdapter()
        assert adapter.SOURCE_NAME == "web"
        assert adapter.SOURCE_DISPLAY_NAME == "Web Pages"
        assert adapter.SOURCE_DESCRIPTION == "Ingests web pages recursively using URL crawling"
        assert adapter.SOURCE_VERSION == "1.0.0"

    def test_get_config_schema(self):
        """Test that get_config_schema returns correct config class."""
        adapter = WebPageSourceAdapter()
        schema = adapter.get_config_schema()
        assert schema.__name__ == "WebPageSourceConfig"

    def test_build_config_from_params_with_urls_list(self):
        """Test building config from operator params with URLs list."""
        adapter = WebPageSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "urls": ["https://example.com", "https://test.com"],
                "max_depth": 3,
                "prevent_outside": False,
                "exclude_patterns": ["/admin"],
                "timeout": 60,
            },
        )

        assert type(config).__name__ == "WebPageSourceConfig"
        assert config.urls == ["https://example.com", "https://test.com"]
        assert config.max_depth == 3
        assert config.prevent_outside is False
        assert config.exclude_patterns == ["/admin"]
        assert config.timeout == 60

    def test_build_config_from_params_with_single_url_fallback(self):
        """Test building config with single URL for backward compatibility."""
        adapter = WebPageSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "url": "https://example.com",
                "max_depth": 1,
            },
        )

        assert type(config).__name__ == "WebPageSourceConfig"
        assert config.urls == ["https://example.com"]
        assert config.max_depth == 1

    def test_build_config_from_params_with_defaults(self):
        """Test building config uses default values when not specified."""
        adapter = WebPageSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"urls": ["https://example.com"]},
        )

        assert config.max_depth == 2
        assert config.prevent_outside is True
        assert config.exclude_patterns == []
        assert config.timeout == 30

    def test_generate_doc_id_is_deterministic(self):
        """Test that document ID generation is deterministic."""
        url = "https://example.com/page"

        id1 = generate_hex_digest(text=url)
        id2 = generate_hex_digest(text=url)

        assert id1 == id2
        assert len(id1) == 64  # SHA-256 produces 64 hex characters

    def test_generate_doc_id_differs_for_different_urls(self):
        """Test that different URLs produce different document IDs."""
        id1 = generate_hex_digest(text="https://example.com/page1")
        id2 = generate_hex_digest(text="https://example.com/page2")

        assert id1 != id2

    def test_fetch_documents_success(self):
        """Test successful document fetching from web pages."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        # Mock LangChain document
        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "<html><body>Test content</body></html>"
        mock_lc_doc.metadata = {
            "source": "https://example.com/page1",
            "title": "Test Page",
            "depth": 0,
        }

        # Mock RecursiveUrlLoader
        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.name == "Test Page"
        assert doc.content == b"<html><body>Test content</body></html>"
        assert doc.source_url == "https://example.com/page1"
        assert doc.metadata["content_type"] == "text/html"
        assert doc.metadata["depth"] == 0
        assert doc.metadata["url"] == "https://example.com/page1"

    def test_fetch_documents_multiple_urls(self):
        """Test fetching documents from multiple URLs."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com", "https://test.com"])

        # Mock documents for each URL
        mock_doc1 = Mock()
        mock_doc1.page_content = "Content 1"
        mock_doc1.metadata = {"source": "https://example.com", "title": "Page 1"}

        mock_doc2 = Mock()
        mock_doc2.page_content = "Content 2"
        mock_doc2.metadata = {"source": "https://test.com", "title": "Page 2"}

        # Mock loader to return different docs for each URL
        mock_loader = Mock()
        mock_loader.load.side_effect = [[mock_doc1], [mock_doc2]]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 2
        assert docs[0].name == "Page 1"
        assert docs[1].name == "Page 2"

    def test_fetch_documents_with_exclusions(self):
        """Test that exclude_patterns are passed to RecursiveUrlLoader."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(exclude_patterns=["/admin", "/login"])

        mock_loader = Mock()
        mock_loader.load.return_value = []

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ) as mock_loader_class,
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        # Verify RecursiveUrlLoader was called with exclude_dirs
        mock_loader_class.assert_called_once()
        call_kwargs = mock_loader_class.call_args[1]
        assert call_kwargs["exclude_dirs"] == ["/admin", "/login"]

    def test_fetch_documents_passes_prevent_outside_parameter(self):
        """Test that prevent_outside parameter is passed correctly."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(prevent_outside=False)

        mock_loader = Mock()
        mock_loader.load.return_value = []

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ) as mock_loader_class,
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        # Verify prevent_outside was passed
        call_kwargs = mock_loader_class.call_args[1]
        assert call_kwargs["prevent_outside"] is False

    def test_fetch_documents_passes_timeout_parameter(self):
        """Test that timeout parameter is passed correctly."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(timeout=60)

        mock_loader = Mock()
        mock_loader.load.return_value = []

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ) as mock_loader_class,
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        # Verify timeout was passed
        call_kwargs = mock_loader_class.call_args[1]
        assert call_kwargs["timeout"] == 60

    def test_fetch_documents_handles_missing_title(self):
        """Test that documents without title use URL fallback."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "Content"
        mock_lc_doc.metadata = {"source": "https://example.com/page/index.html"}

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert docs[0].name == "index.html"

    def test_fetch_documents_continues_on_page_error(self):
        """Test that processing continues when a single page fails."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        # First doc succeeds, second fails during processing
        mock_doc1 = Mock()
        mock_doc1.page_content = "Content 1"
        mock_doc1.metadata = {"source": "https://example.com/page1"}

        mock_doc2 = Mock()
        mock_doc2.page_content = "Content 2"
        # Simulate error by making metadata access fail
        mock_doc2.metadata = Mock(side_effect=Exception("Metadata error"))

        mock_doc3 = Mock()
        mock_doc3.page_content = "Content 3"
        mock_doc3.metadata = {"source": "https://example.com/page3"}

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_doc1, mock_doc2, mock_doc3]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        # Should get 2 docs (first and third), skipping the failed one
        assert len(docs) == 2

    def test_fetch_documents_continues_on_url_error(self):
        """Test that processing continues when a URL fails to crawl."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com", "https://test.com"])

        mock_doc = Mock()
        mock_doc.page_content = "Content"
        mock_doc.metadata = {"source": "https://test.com"}

        mock_loader = Mock()
        # First URL fails, second succeeds
        mock_loader.load.side_effect = [Exception("Crawl failed"), [mock_doc]]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        # Should get 1 doc from the second URL
        assert len(docs) == 1
        assert docs[0].source_url == "https://test.com"

    def test_fetch_documents_raises_import_error(self):
        """Test that DocpipeException is raised when langchain_community is not installed."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        # Mock the import to fail at module level
        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                side_effect=ImportError("No module named 'langchain_community'"),
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            # The adapter should raise DocpipeException when import fails
            with pytest.raises(DocpipeException) as exc_info:
                asyncio.run(collect_async(adapter.fetch_documents(config=config)))

            assert "LangChain community dependencies not installed" in str(exc_info.value)

    def test_test_connection_success(self):
        """Test successful connection test."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock(return_value=None)

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is True
        assert "Successfully connected to all 1 URL(s)" in message
        assert "https://example.com" in message
        assert "Status: 200" in message

    def test_test_connection_multiple_urls_all_success(self):
        """Test connection test with multiple URLs all succeeding."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com", "https://test.com"])

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock(return_value=None)

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is True
        assert "Successfully connected to all 2 URL(s)" in message

    def test_test_connection_partial_success(self):
        """Test connection test with some URLs failing."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com", "https://test.com"])

        async def mock_head(url, **kwargs):
            if "test.com" in url:
                import httpx

                raise httpx.ConnectError("Connection failed")
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock(return_value=None)
            return mock_response

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is True  # Partial success still returns True
        assert "Connected to 1/2 URL(s)" in message
        assert "example.com" in message
        assert "test.com" in message

    def test_test_connection_all_failure(self):
        """Test connection test with all URLs failing."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        async def mock_head(url, **kwargs):
            import httpx

            raise httpx.ConnectError("Connection failed")

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "Failed to connect to all URL(s)" in message
        assert "Connection failed" in message

    def test_test_connection_timeout(self):
        """Test connection test handling timeout."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(timeout=5)

        async def mock_head(url, **kwargs):
            import httpx

            raise httpx.TimeoutException("Timeout")

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "Timeout after 5s" in message

    def test_test_connection_http_error(self):
        """Test connection test handling HTTP errors."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        async def mock_head(url, **kwargs):
            import httpx

            mock_response = Mock()
            mock_response.status_code = 404
            raise httpx.HTTPStatusError("404 Not Found", request=Mock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "HTTP error" in message

    def test_test_connection_no_urls(self):
        """Test connection test with no URLs provided."""
        adapter = WebPageSourceAdapter()

        # Create a mock config that bypasses validation
        mock_config = Mock(spec=WebPageSourceConfig)
        mock_config.urls = []

        success, message = asyncio.run(adapter.test_connection(config=mock_config))

        assert success is False
        assert message == "No URLs provided"

    def test_document_conversion_includes_all_metadata(self):
        """Test that document conversion includes all expected metadata fields."""
        adapter = WebPageSourceAdapter()
        config = self.make_config()

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "Test content"
        mock_lc_doc.metadata = {
            "source": "https://example.com/page",
            "title": "Test",
            "depth": 2,
        }

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        doc = docs[0]
        assert doc.metadata["content_type"] == "text/html"
        assert doc.metadata["file_size"] == len(b"Test content")
        assert doc.metadata["depth"] == 2
        assert doc.metadata["url"] == "https://example.com/page"
        assert doc.modified_time is None  # Web pages don't have reliable modified time

    def test_fetch_documents_extension_is_html_when_server_returns_text_html(self):
        """Regression: page title like 'Introduction to HTML 4' must not overwrite
        extension — the adapter uses HEAD detection, not the title."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://www.w3.org/TR/html401/intro/intro.html"])

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "<html><body>Hello</body></html>"
        mock_lc_doc.metadata = {
            "source": "https://www.w3.org/TR/html401/intro/intro.html",
            "title": "Introduction to HTML 4",  # no file extension in title
            "depth": 0,
        }

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        assert docs[0].extension == ".html"

    def test_fetch_documents_extension_is_html_for_bare_url_path(self):
        """Regression: URLs without a file extension in the path (e.g. /overview)
        produce extension='.html' when the server returns text/html."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://docs.example.com/overview"])

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "<html><body>Overview</body></html>"
        mock_lc_doc.metadata = {
            "source": "https://docs.example.com/overview",
            "title": "Overview",
            "depth": 0,
        }

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        assert docs[0].extension == ".html"

    def test_fetch_documents_extension_is_html_when_title_is_missing(self):
        """Regression: when no title is present the name falls back to the last URL
        segment — extension is still determined by HEAD, not the URL path."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com/"])

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "<html><body>Home</body></html>"
        mock_lc_doc.metadata = {
            "source": "https://example.com/",
            # no 'title' key — name falls back to "index"
            "depth": 0,
        }

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        assert docs[0].extension == ".html"

    def test_fetch_documents_extension_pdf_for_pdf_url(self):
        """HEAD request returning application/pdf must produce extension='.pdf',
        regardless of the page title."""
        adapter = WebPageSourceAdapter()
        config = self.make_config(urls=["https://example.com/report.pdf"])

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "%PDF-1.4 binary"
        mock_lc_doc.metadata = {
            "source": "https://example.com/report.pdf",
            "title": "My PDF Guide",
            "depth": 0,
        }

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ),
            patch.object(adapter, "_detect_extension", return_value=(".pdf", "application/pdf")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        assert docs[0].extension == ".pdf"
        assert docs[0].metadata["content_type"] == "application/pdf"


_ADAPTER_MODULE = "docpipe.core.operators.ingest.adapters.outbound.sources.web.adapter"


class TestWebPageSourceAdapterFetchBinaryContent:
    """Test fetch_binary_content on WebPageSourceAdapter."""

    def test_fetch_binary_content_success(self):
        """Test successful binary content download."""
        adapter = WebPageSourceAdapter()

        mock_response = Mock()
        mock_response.content = b"<html>page</html>"

        with patch.object(adapter._download_client, "call_rest", return_value=mock_response):
            result = adapter.fetch_binary_content(
                source_id="https://example.com/page",
                provider_config={},
            )

        assert result == b"<html>page</html>"

    def test_fetch_binary_content_uses_timeout_from_params(self):
        """Test that timeout is read from provider_config."""
        adapter = WebPageSourceAdapter()

        mock_response = Mock()
        mock_response.content = b"data"

        with patch.object(adapter._download_client, "call_rest", return_value=mock_response) as mock_call:
            adapter.fetch_binary_content(
                source_id="https://example.com/file",
                provider_config={"timeout": 10},
            )

        call_kwargs = mock_call.call_args[1]
        assert call_kwargs["timeout"] == 10

    def test_fetch_binary_content_default_timeout(self):
        """Test that default timeout of 30 is used when not in provider_config."""
        adapter = WebPageSourceAdapter()

        mock_response = Mock()
        mock_response.content = b"data"

        with patch.object(adapter._download_client, "call_rest", return_value=mock_response) as mock_call:
            adapter.fetch_binary_content(
                source_id="https://example.com/file",
                provider_config={},
            )

        call_kwargs = mock_call.call_args[1]
        assert call_kwargs["timeout"] == 30

    def test_fetch_binary_content_returns_none_on_timeout(self):
        """Test that a timeout error returns None."""
        adapter = WebPageSourceAdapter()

        with patch.object(adapter._download_client, "call_rest", side_effect=ExternalServiceError("timed out")):
            result = adapter.fetch_binary_content(
                source_id="https://example.com/page",
                provider_config={},
            )

        assert result is None

    def test_fetch_binary_content_returns_none_on_connection_error(self):
        """Test that a connection error returns None."""
        adapter = WebPageSourceAdapter()

        with patch.object(
            adapter._download_client,
            "call_rest",
            side_effect=ExternalServiceError("connection refused"),
        ):
            result = adapter.fetch_binary_content(
                source_id="https://example.com/page",
                provider_config={},
            )

        assert result is None

    def test_fetch_binary_content_returns_none_on_http_error(self):
        """Test that an HTTP error returns None."""
        adapter = WebPageSourceAdapter()

        with patch.object(
            adapter._download_client,
            "call_rest",
            side_effect=ExternalServiceError("404 Not Found"),
        ):
            result = adapter.fetch_binary_content(
                source_id="https://example.com/page",
                provider_config={},
            )

        assert result is None

    def test_fetch_binary_content_returns_none_on_unexpected_exception(self):
        """Test that an unexpected exception returns None."""
        adapter = WebPageSourceAdapter()

        with patch.object(adapter._download_client, "call_rest", side_effect=RuntimeError("disk full")):
            result = adapter.fetch_binary_content(
                source_id="https://example.com/page",
                provider_config={},
            )

        assert result is None


class TestWebPageTestConnectionEdgeCases:
    """Test uncovered branches in test_connection."""

    def test_test_connection_generic_http_error(self):
        """Test that a generic httpx.HTTPError (not status or connect) is handled."""
        import httpx

        adapter = WebPageSourceAdapter()
        config = WebPageSourceConfig(urls=["https://example.com"])

        async def mock_head(url, **kwargs):
            raise httpx.HTTPError("generic http error")

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "HTTP error" in message

    def test_test_connection_generic_exception_per_url(self):
        """Test that a generic exception for a single URL is caught and reported."""
        adapter = WebPageSourceAdapter()
        config = WebPageSourceConfig(urls=["https://example.com"])

        async def mock_head(url, **kwargs):
            raise ValueError("unexpected")

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "Error" in message

    def test_test_connection_client_creation_failure(self):
        """Test that failure to create the AsyncClient returns False."""
        adapter = WebPageSourceAdapter()
        config = WebPageSourceConfig(urls=["https://example.com"])

        with patch("httpx.AsyncClient", side_effect=RuntimeError("ssl error")):
            success, message = asyncio.run(adapter.test_connection(config=config))

        assert success is False
        assert "Failed to create HTTP client" in message


class TestDetectExtension:
    """Unit tests for the _detect_extension instance method on WebPageSourceAdapter."""

    def test_pdf_content_type_returns_pdf_extension(self):
        """application/pdf Content-Type must produce ('.pdf', 'application/pdf')."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/doc.pdf", timeout=10)

        assert extension == ".pdf"
        assert content_type == "application/pdf"

    def test_text_html_content_type_returns_html_extension(self):
        """text/html Content-Type must produce ('.html', 'text/html')."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/page", timeout=10)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_text_plain_content_type_returns_txt_extension(self):
        """text/plain Content-Type must produce ('.txt', 'text/plain')."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/plain"}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/notes.txt", timeout=10)

        assert extension == ".txt"
        assert content_type == "text/plain"

    def test_unknown_content_type_falls_back_to_html(self):
        """An unrecognised Content-Type must fall back to ('.html', 'text/html')."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/octet-stream"}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/binary", timeout=10)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_missing_content_type_header_falls_back_to_html(self):
        """Absent Content-Type header must fall back to ('.html', 'text/html')."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/page", timeout=10)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_405_method_not_allowed_falls_back_to_html(self):
        """A 405 response must silently fall back to ('.html', 'text/html') without reading Content-Type."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 405
        mock_response.headers = {}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/page", timeout=10)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_connection_error_falls_back_to_html(self):
        """A network-level error during HEAD must silently fall back to ('.html', 'text/html')."""
        adapter = WebPageSourceAdapter()

        with patch.object(adapter._rest_client, "call_rest", side_effect=ExternalServiceError("refused")):
            extension, content_type = adapter._detect_extension(url="https://example.com/page", timeout=10)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_timeout_falls_back_to_html(self):
        """A timeout during HEAD must silently fall back to ('.html', 'text/html')."""
        adapter = WebPageSourceAdapter()

        with patch.object(adapter._rest_client, "call_rest", side_effect=ExternalServiceError("timed out")):
            extension, content_type = adapter._detect_extension(url="https://example.com/page", timeout=5)

        assert extension == ".html"
        assert content_type == "text/html"

    def test_content_type_with_charset_param_is_parsed_correctly(self):
        """Content-Type with a charset param must still map to the correct extension
        after stripping the parameter."""
        adapter = WebPageSourceAdapter()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf; name=doc.pdf"}

        with patch.object(adapter._rest_client, "call_rest", return_value=mock_response):
            extension, content_type = adapter._detect_extension(url="https://example.com/doc.pdf", timeout=10)

        assert extension == ".pdf"
        assert content_type == "application/pdf"


class TestWebPageFetchDocumentsEdgeCases:
    """Test remaining uncovered branches in fetch_documents."""

    def test_fetch_documents_empty_exclude_patterns_passes_none(self):
        """Test that empty exclude_patterns passes None to RecursiveUrlLoader."""
        adapter = WebPageSourceAdapter()
        config = WebPageSourceConfig(urls=["https://example.com"], exclude_patterns=[])

        mock_loader = Mock()
        mock_loader.load.return_value = []

        with (
            patch(
                "langchain_community.document_loaders.RecursiveUrlLoader",
                return_value=mock_loader,
            ) as mock_loader_class,
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        call_kwargs = mock_loader_class.call_args[1]
        assert call_kwargs["exclude_dirs"] is None

    def test_fetch_documents_missing_source_in_metadata_falls_back_to_url(self):
        """Test that when 'source' key is absent from metadata, the crawl URL is used."""
        adapter = WebPageSourceAdapter()
        config = WebPageSourceConfig(urls=["https://example.com"])

        mock_lc_doc = Mock()
        mock_lc_doc.page_content = "content"
        # No 'source' key — metadata.get("source", url) should fall back to the crawl URL
        mock_lc_doc.metadata = {"title": "No Source Page", "depth": 1}

        mock_loader = Mock()
        mock_loader.load.return_value = [mock_lc_doc]

        with (
            patch("langchain_community.document_loaders.RecursiveUrlLoader", return_value=mock_loader),
            patch.object(adapter, "_detect_extension", return_value=(".html", "text/html")),
        ):
            docs = asyncio.run(collect_async(adapter.fetch_documents(config=config)))

        assert len(docs) == 1
        assert docs[0].source_url == "https://example.com"

    def test_build_config_no_urls_and_no_url_produces_empty_list_error(self):
        """Test that when neither 'urls' nor 'url' is in provider_config, validation fails."""
        adapter = WebPageSourceAdapter()

        with pytest.raises(ValidationError):
            adapter.build_config_from_operator_params(
                provider_config={},
            )
