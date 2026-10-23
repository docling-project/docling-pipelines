"""Test script for Web Page source adapter."""

import asyncio
import logging
import os
import sys
from pathlib import Path

from docpipe.core.operators.ingest.adapters.outbound.sources.web.adapter import (
    WebPageSourceAdapter,
    WebPageSourceConfig,
)

# Load environment variables from .env file in connectors directory
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from {env_path}")
except ImportError:
    print("python-dotenv not installed. Install with: pip install python-dotenv")
    print("Or set environment variables manually.")

# Add the backend directory to Python path
backend_path = Path(__file__).parent.parent.parent / "src" / "docpipe_app" / "backend"
sys.path.insert(0, str(backend_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def test_web_adapter():
    """Test the Web Page source adapter with single URL."""
    # Get configuration from environment
    urls_str = os.getenv("WEB_TEST_URLS", "https://example.com,https://www.iana.org/domains/reserved")
    urls = [url.strip() for url in urls_str.split(",")]
    max_depth = int(os.getenv("WEB_TEST_MAX_DEPTH", "1"))
    timeout = int(os.getenv("WEB_TEST_TIMEOUT", "30"))

    # Initialize adapter
    adapter = WebPageSourceAdapter()

    # Test configuration with single URL (use first URL from list)
    config = WebPageSourceConfig(
        urls=[urls[0]],
        max_depth=max_depth,
        exclude_patterns=[],
        timeout=timeout,
    )

    logger.info("Testing Web Page adapter with single URL...")
    logger.info("Configuration: %s", config)

    # Test connection
    logger.info("\n=== Testing Connection ===")
    success, message = await adapter.test_connection(config=config)
    logger.info("Connection test: %s", "Success" if success else "Failed")
    logger.info("Message: %s", message)

    if not success:
        logger.error("Connection test failed. Exiting.")
        return

    # Fetch documents
    logger.info("\n=== Fetching Documents ===")
    doc_count = 0
    async for document in adapter.fetch_documents(config=config):
        doc_count += 1
        logger.info("\nDocument %s:", doc_count)
        logger.info("  ID: %s", document.id)
        logger.info("  Name: %s", document.name)
        logger.info("  Source URL: %s", document.source_url)
        logger.info("  Content size: %s bytes", len(document.content))
        logger.info("  Metadata: %s", document.metadata)

        # Limit output for testing
        if doc_count >= 3:
            logger.info("\n(Limiting output to first 3 documents)")
            break

    logger.info("\n=== Summary ===")
    logger.info("Total documents fetched: %s", doc_count)


async def test_multiple_urls():
    """Test the Web Page source adapter with multiple URLs."""
    # Get configuration from environment
    urls_str = os.getenv("WEB_TEST_URLS", "https://example.com,https://www.iana.org/domains/reserved")
    urls = [url.strip() for url in urls_str.split(",")]
    max_depth = int(os.getenv("WEB_TEST_MAX_DEPTH", "1"))
    timeout = int(os.getenv("WEB_TEST_TIMEOUT", "30"))

    # Initialize adapter
    adapter = WebPageSourceAdapter()

    # Test configuration with multiple URLs
    config = WebPageSourceConfig(
        urls=urls,
        max_depth=max_depth,
        exclude_patterns=[],
        timeout=timeout,
    )

    logger.info("\n=== Testing Multiple URLs ===")
    logger.info("Configuration: %s", config)

    # Test connection
    logger.info("\n=== Testing Connection for Multiple URLs ===")
    success, message = await adapter.test_connection(config=config)
    logger.info("Connection test: %s", "Success" if success else "Failed")
    logger.info("Message:\n%s", message)

    if not success:
        logger.error("Connection test failed. Exiting.")
        return

    # Fetch documents
    logger.info("\n=== Fetching Documents from Multiple URLs ===")
    doc_count = 0
    url_counts = {}

    async for document in adapter.fetch_documents(config=config):
        doc_count += 1
        source_url = document.source_url

        # Track documents per URL
        base_url = source_url.split("/")[2] if "/" in source_url else source_url
        url_counts[base_url] = url_counts.get(base_url, 0) + 1

        logger.info("\nDocument %s:", doc_count)
        logger.info("  ID: %s", document.id)
        logger.info("  Name: %s", document.name)
        logger.info("  Source URL: %s", document.source_url)
        logger.info("  Content size: %s bytes", len(document.content))

        # Limit output for testing
        if doc_count >= 5:
            logger.info("\n(Limiting output to first 5 documents)")
            break

    logger.info("\n=== Summary ===")
    logger.info("Total documents fetched: %s", doc_count)
    logger.info("Documents per URL: %s", url_counts)


async def test_build_config():
    """Test building config from operator parameters."""
    # Get configuration from environment
    urls_str = os.getenv("WEB_TEST_URLS", "https://example.com,https://www.iana.org")
    urls = [url.strip() for url in urls_str.split(",")]
    max_depth = int(os.getenv("WEB_TEST_MAX_DEPTH", "2"))
    timeout = int(os.getenv("WEB_TEST_TIMEOUT", "60"))

    adapter = WebPageSourceAdapter()

    logger.info("\n=== Testing Config Builder ===")

    # Simulate operator parameters
    provider_config = {
        "urls": urls,
        "max_depth": max_depth,
        "exclude_patterns": ["/admin", "/login"],
        "timeout": timeout,
    }

    # Build config
    config = adapter.build_config_from_operator_params(
        provider_config=provider_config,
        included_extensions=None,  # Not used for web
    )

    logger.info("Built config: %s", config)
    logger.info("Config type: %s", type(config))

    # Verify config
    assert config.urls == urls
    assert config.max_depth == max_depth
    assert config.exclude_patterns == ["/admin", "/login"]
    assert config.timeout == timeout

    logger.info("Config builder test passed")


async def test_metadata():
    """Test adapter metadata."""
    adapter = WebPageSourceAdapter()

    logger.info("\n=== Testing Adapter Metadata ===")

    metadata = adapter.get_metadata()
    logger.info("Adapter metadata: %s", metadata)

    assert metadata["name"] == "web"
    assert metadata["display_name"] == "Web Pages"
    assert metadata["version"] == "1.0.0"

    logger.info("Metadata test passed")


async def main():
    """Run all tests."""
    try:
        await test_metadata()
        await test_build_config()
        await test_web_adapter()
        await test_multiple_urls()
        logger.info("\nAll tests completed successfully!")
    except Exception as e:
        logger.exception("\nTest failed with error: %s", e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
