"""Web page source adapter using LangChain's RecursiveUrlLoader."""

from typing import Any, AsyncGenerator

import httpx
from pydantic import BaseModel

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.factories.source_factory import register_source_adapter
from docpipe.core.operators.ingest.adapters.outbound.sources.web.config import WebPageSourceConfig
from docpipe.core.operators.ingest.domain.models import Document
from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort
from docpipe.exceptions.docpipe_exceptions import DocpipeException, ExternalServiceError
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.utils.core.docpipe_utils import generate_hex_digest
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_CONTENT_TYPE_TO_EXTENSION: dict[str, str] = {
    OperatorConstants.MimeTypes.PDF: OperatorConstants.FileExtensions.EXT_PDF,
    OperatorConstants.MimeTypes.HTML: OperatorConstants.FileExtensions.EXT_HTML,
    OperatorConstants.MimeTypes.PLAIN: OperatorConstants.FileExtensions.EXT_TXT,
}


@register_source_adapter
class WebPageSourceAdapter(DocumentSourcePort):
    """
    Adapter for ingesting web pages recursively using LangChain's RecursiveUrlLoader.

    This adapter wraps LangChain's RecursiveUrlLoader to crawl web pages starting
    from a given URL and following links up to a specified depth.

    Features:
    - Recursive URL crawling with configurable depth
    - URL pattern exclusion for filtering unwanted pages
    - Configurable request timeout
    - Automatic HTML content extraction
    - Custom extractor support for specialized parsing

    Benefits:
    - Battle-tested by LangChain community
    - Automatic link discovery and traversal
    - Built-in error handling for failed requests
    - Simpler than manual web scraping implementation
    """

    def __init__(self) -> None:
        self._rest_client = RestClient(
            config=RestClientConfig(retry_max_attempts=1),
        )
        self._download_client = RestClient(
            config=RestClientConfig(),
        )

    def _detect_extension(self, *, url: str, timeout: int) -> tuple[str, str]:
        """Issue a HEAD request to detect the file extension and MIME type from the Content-Type header.

        Returns a (extension, content_type) tuple.
        Falls back to ('.html', 'text/html') on any error or unrecognised content type so that
        RecursiveUrlLoader can still process the document.
        """
        _default = (OperatorConstants.FileExtensions.EXT_HTML, OperatorConstants.MimeTypes.HTML)
        try:
            response = self._rest_client.call_rest(
                method=RestMethod.HEAD,
                url=url,
                expected_status_codes=[200, 405],
                timeout=timeout,
            )
            if response.status_code == 405:
                return _default
            content_type = response.headers.get("Content-Type", OperatorConstants.MimeTypes.HTML).split(";")[0].strip()
            extension = _CONTENT_TYPE_TO_EXTENSION.get(content_type, OperatorConstants.FileExtensions.EXT_HTML)
            # If content_type was not in the map, normalise it to the HTML fallback too
            resolved_content_type = (
                content_type if content_type in _CONTENT_TYPE_TO_EXTENSION else OperatorConstants.MimeTypes.HTML
            )
            return extension, resolved_content_type
        except Exception:
            return _default

    # Metadata for connector discovery
    SOURCE_NAME = "web"
    SOURCE_DISPLAY_NAME = "Web Pages"
    SOURCE_DESCRIPTION = "Ingests web pages recursively using URL crawling"
    SOURCE_VERSION = "1.0.0"

    async def fetch_documents(self, config: WebPageSourceConfig) -> AsyncGenerator[Document, None]:
        """
        Fetch documents from web pages using RecursiveUrlLoader.

        Args:
            config: Validated web page configuration

        Yields:
            Document: Domain documents from web pages

        Raises:
            DocpipeException: If langchain_community is not installed or crawling fails
        """
        # Iterate through all URLs
        for url in config.urls:
            logger.info("Starting web crawl from %s with max_depth=%s", url, config.max_depth)

            try:
                # Imported lazily: langchain_community.document_loaders transitively loads
                # langchain_text_splitters, which pulls in torch/transformers/spacy/nltk.
                from langchain_community.document_loaders import RecursiveUrlLoader

                # Create LangChain loader with configuration
                # Note: RecursiveUrlLoader is synchronous
                loader = RecursiveUrlLoader(
                    url=url,
                    max_depth=config.max_depth,
                    extractor=lambda x: x,  # Default extractor returns raw HTML
                    prevent_outside=config.prevent_outside,  # Control external link following
                    use_async=False,  # Use synchronous requests
                    timeout=config.timeout,
                    # Note: exclude_dirs parameter filters URL paths
                    exclude_dirs=config.exclude_patterns if config.exclude_patterns else None,
                )

                # Load documents (synchronous operation from LangChain)
                langchain_docs = loader.load()
                logger.info("Successfully crawled %s pages from %s", len(langchain_docs), url)

                # Convert LangChain documents to domain documents
                for lc_doc in langchain_docs:
                    # Extract metadata first for error handling
                    metadata = lc_doc.metadata
                    source_url = metadata.get("source", url)

                    try:
                        # Generate unique document ID from URL
                        doc_id = generate_hex_digest(text=source_url)

                        # Extract title from metadata or use URL as fallback
                        doc_name = metadata.get("title", source_url.split("/")[-1] or "index")

                        # Convert page_content (string) to bytes
                        # Store HTML content as bytes for consistency with other adapters
                        content = lc_doc.page_content.encode("utf-8")

                        # Detect extension and MIME type via HEAD request
                        extension, content_type = self._detect_extension(url=source_url, timeout=config.timeout)

                        # Create domain document
                        document = Document(
                            id=doc_id,
                            name=doc_name,
                            content=content,
                            source_url=source_url,
                            modified_time=None,  # Web pages don't have reliable modified time
                            extension=extension,
                            metadata={
                                "content_type": content_type,
                                "file_size": len(content),
                                "depth": metadata.get("depth", 0),
                                "url": source_url,
                            },
                        )
                        yield document
                    except Exception as e:
                        # Log warning but continue processing other pages
                        logger.warning("Failed to process page %s: %s", source_url, e)
                        continue
            except ImportError as e:
                raise DocpipeException(
                    "LangChain community dependencies not installed. Install with: pip install langchain-community"
                ) from e
            except Exception as e:
                # Log error for this URL but continue with other URLs
                logger.error("Failed to crawl %s: %s", url, e)
                continue

    async def test_connection(self, config: WebPageSourceConfig) -> tuple[bool, str]:
        """
        Test web page connection by checking URL accessibility.

        Args:
            config: Validated web page configuration

        Returns:
            Tuple[bool, str]: (success, message)
        """

        if not config.urls:
            return False, "No URLs provided"

        # Test all URLs
        results = []
        failed_urls = []

        try:
            async with httpx.AsyncClient(
                timeout=config.timeout,
                follow_redirects=True,
            ) as client:
                for url in config.urls:
                    try:
                        # Test URL accessibility with a simple HEAD request
                        response = await client.head(url)
                        response.raise_for_status()
                        results.append(f"[OK] {url} (Status: {response.status_code})")
                    except httpx.TimeoutException:
                        failed_urls.append(f"[FAIL] {url} (Timeout after {config.timeout}s)")
                    except httpx.ConnectError:
                        failed_urls.append(f"[FAIL] {url} (Connection failed)")
                    except httpx.HTTPStatusError as e:
                        failed_urls.append(f"[FAIL] {url} (HTTP error: {e.response.status_code})")
                    except httpx.HTTPError as e:
                        failed_urls.append(f"[FAIL] {url} (HTTP error: {e})")
                    except Exception as e:
                        failed_urls.append(f"[FAIL] {url} (Error: {e!s})")
        except Exception as e:
            # Handle client creation errors
            return False, f"Failed to create HTTP client: {e!s}"

        # Determine overall success
        if not failed_urls:
            return True, f"Successfully connected to all {len(config.urls)} URL(s):\n" + "\n".join(results)
        if results:
            # Partial success
            all_results = results + failed_urls
            return True, f"Connected to {len(results)}/{len(config.urls)} URL(s):\n" + "\n".join(all_results)
        # All failed
        return False, "Failed to connect to all URL(s):\n" + "\n".join(failed_urls)

    def get_config_schema(self) -> type[BaseModel]:
        """
        Get the configuration schema for this adapter.

        Returns:
            type[BaseModel]: The Pydantic configuration model
        """
        return WebPageSourceConfig

    def fetch_binary_content(
        self,
        *,
        source_id: str,
        provider_config: dict[str, Any],
    ) -> bytes | None:
        """
        Fetch binary content for a specific URL via HTTP download.

        Args:
            source_id: URL to download
            provider_config: All provider-specific parameters (timeout, etc.)

        Returns:
            Binary content as bytes, or None if download fails
        """
        timeout = provider_config.get("timeout", 30)

        try:
            logger.info("Downloading binary content from URL: %s", source_id)

            response = self._download_client.call_rest(
                method=RestMethod.GET,
                url=source_id,
                timeout=timeout,
            )

            content = response.content
            logger.info("Successfully downloaded %s bytes from %s", len(content), source_id)
            return content

        except ExternalServiceError as e:
            logger.error("Failed to download from %s: %s", source_id, e)
            return None
        except Exception as e:
            logger.exception("Unexpected error downloading from %s: %s", source_id, e)
            return None

    def build_config_from_operator_params(
        self,
        *,
        provider_config: dict,
        included_extensions: list[str] | None = None,
        max_files: int | None = None,
    ) -> BaseModel:
        """
        Build web page configuration from operator parameters.

        Args:
            provider_config: All provider-specific parameters.
            included_extensions: Not used for web.
            max_files: Not used for web.

        Returns:
            WebPageSourceConfig: Validated configuration object

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Support both "urls" (list) and "url" (single) keys
        urls = provider_config.get("urls")
        if urls is None:
            url = provider_config.get("url")
            urls = [url] if url else []

        config_dict = {
            "urls": urls,
            "max_depth": provider_config.get("max_depth", 2),
            "prevent_outside": provider_config.get("prevent_outside", True),
            "exclude_patterns": provider_config.get("exclude_patterns", []),
            "timeout": provider_config.get("timeout", 30),
            "extractor": provider_config.get("extractor"),
        }

        return WebPageSourceConfig(**config_dict)
