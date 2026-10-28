"""
NLTK Data Manager

This module handles NLTK data downloads with SSL certificate bypass capabilities.
It provides a thread-safe, scoped approach to downloading NLTK packages when
SSL certificate verification fails in restricted environments.

Key Features:
- Thread-safe downloads using locks
- Automatic SSL retry on certificate errors
- Scoped monkey-patching with guaranteed cleanup
- No global side effects on urllib or other code
"""

import ssl
import sys
import threading
from functools import wraps
from pathlib import Path

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Thread lock to prevent concurrent NLTK downloads
# This ensures only one thread can download NLTK data at a time
_nltk_lock = threading.Lock()


class UnverifiedNLTKDownloader:
    """
    A custom NLTK downloader that can bypass SSL verification when needed.

    This class provides a clean, encapsulated way to download NLTK packages
    without SSL verification. The SSL bypass is scoped to the download operation
    and automatically restored afterward, ensuring no global side effects.

    Why Monkey-Patching:
    ----
    NLTK doesn't provide any method to inject SSL context (no override points, no parameters).
    NLTK caches SSL context at import time, so changing ssl._create_default_https_context
    doesn't work. The only solution is to temporarily replace nltk.downloader.urlopen.

    Safety:
    - Scoped to download call only (~1-2 seconds)
    - Restored via finally block (guaranteed cleanup)
    - Thread-safe with _nltk_lock
    - No global side effects

    Attributes:
        download_dir: Directory where NLTK data will be downloaded
        ssl_context: Unverified SSL context for bypassing certificate checks
        downloader: The underlying NLTK Downloader instance
    """

    def __init__(self, download_dir: str):
        """
        Initialize the downloader with an unverified SSL context.

        Args:
            download_dir: Path to directory where NLTK data should be downloaded
        """
        from nltk.downloader import Downloader

        self.download_dir = download_dir
        # Intentional SSL bypass for restricted environments
        # This is only used as a fallback when standard SSL verification fails.
        # The primary download attempt (line 158) uses full SSL verification.
        # This fallback is necessary for environments with corporate proxies/firewalls
        # that interfere with SSL certificate chains.
        self.ssl_context = ssl._create_unverified_context()  # NOSONAR  # nosec B323 — intentional fallback for corporate proxy environments; only used when standard SSL fails

        self.downloader = Downloader(download_dir=download_dir)

    def download(self, package_id: str, quiet: bool = False) -> bool:
        """
        Download an NLTK package without SSL verification.

        This method temporarily patches nltk.downloader.urlopen to use an unverified
        SSL context, performs the download, and then restores the original function.
        The patch is scoped to this method call only and has no global side effects.

        Args:
            package_id: The NLTK package to download (e.g., 'punkt_tab')
            quiet: Whether to suppress download progress output

        Returns:
            True if download succeeded, False otherwise

        Note:
            Monkey-patch is necessary because NLTK has no SSL context override mechanism.
            Scoped to this call only: save original → patch → download → restore (finally block)
        """
        from urllib.request import urlopen as original_urlopen

        # Create a wrapper that injects our unverified SSL context
        @wraps(original_urlopen)
        def urlopen_no_ssl_verify(url, *args, **kwargs):
            """Wrapper that forces unverified SSL context for this request only."""
            kwargs["context"] = self.ssl_context
            return original_urlopen(url, *args, **kwargs)  # nosec B310 — intentional SSL fallback used only when standard SSL fails; scoped to nltk downloader only

        # Perform scoped monkey-patch with guaranteed cleanup
        import nltk.downloader

        original_urlopen_ref = nltk.downloader.urlopen
        try:
            # Temporarily replace nltk's urlopen with our SSL-bypassing version
            nltk.downloader.urlopen = urlopen_no_ssl_verify  # type: ignore
            return self.downloader.download(package_id, quiet=quiet)
        finally:
            # ALWAYS restore the original function, even if download fails
            # This ensures no global side effects
            nltk.downloader.urlopen = original_urlopen_ref  # type: ignore


def ensure_nltk_data(package_id: str = "punkt_tab") -> None:
    """
    Ensure NLTK data package is downloaded to the venv's nltk_data directory.

    This function handles the complete lifecycle of NLTK data management:
    1. Sets up the NLTK data path in the virtual environment
    2. Checks if the package already exists (early exit if found)
    3. Attempts standard download with SSL verification
    4. Falls back to SSL-bypassed download if certificate errors occur
    5. Verifies the data is available after download

    The function is thread-safe and handles SSL certificate errors gracefully,
    making it suitable for use in restricted corporate environments.

    Args:
        package_id: The NLTK package to ensure is downloaded (default: 'punkt_tab')

    Raises:
        RuntimeError: If download fails after all retry attempts

    Note:
        This function uses a thread lock to prevent concurrent downloads,
        which could cause race conditions or duplicate downloads.
    """
    # Imported lazily so that importing this module (via the operator registry) does not load nltk.
    import nltk

    venv_nltk_data = Path(sys.prefix) / "nltk_data"

    # Use thread lock to prevent concurrent downloads
    with _nltk_lock:
        # Step 1: Setup NLTK data path
        # Prepend venv path so it's checked first
        if str(venv_nltk_data) not in nltk.data.path:
            nltk.data.path.insert(0, str(venv_nltk_data))

        # Step 2: Early exit if package already exists
        try:
            nltk.data.find(f"tokenizers/{package_id}")
            logger.debug("NLTK %s data already available", package_id)
            return
        except LookupError:
            # Package not found, proceed with download
            venv_nltk_data.mkdir(exist_ok=True, parents=True)
            logger.info("NLTK %s not found. Downloading to %s...", package_id, venv_nltk_data)

        # Step 3: Try standard download with SSL verification first
        try:
            result = nltk.download(package_id, download_dir=str(venv_nltk_data), quiet=False)
            if not result:
                raise ConnectionError(f"NLTK download of {package_id} returned False")
            logger.info("Successfully downloaded NLTK %s data to %s", package_id, venv_nltk_data)

        except (ssl.SSLError, ConnectionError) as e:
            # Step 4: SSL or connection errors - retry with SSL bypass
            # ConnectionError is raised when nltk.download() returns False (SSL failure)
            # ssl.SSLError is raised directly by urllib on SSL issues
            logger.warning(
                "Initial NLTK download failed (%s). Retrying without SSL verification...",
                e,
            )

            try:
                # Use our custom downloader that bypasses SSL verification
                downloader = UnverifiedNLTKDownloader(download_dir=str(venv_nltk_data))
                success = downloader.download(package_id, quiet=False)

                if not success:
                    raise RuntimeError(f"NLTK download of {package_id} returned False even without SSL verification")

                logger.info(
                    "Successfully downloaded NLTK %s data to %s (SSL bypassed)",
                    package_id,
                    venv_nltk_data,
                )

            except Exception as final_err:
                # All retry attempts failed
                logger.error("Critical NLTK download failure: %s", final_err)
                logger.info("Manual fix: python -m nltk.downloader %s -d %s", package_id, venv_nltk_data)
                raise RuntimeError(f"Failed to download NLTK {package_id} data: {final_err}") from final_err

        except Exception as e:
            # Step 5: Non-SSL/network error - don't retry, just fail with helpful message
            logger.error("Unexpected error during NLTK download: %s", e)
            logger.info("Manual fix: python -m nltk.downloader %s -d %s", package_id, venv_nltk_data)
            raise

        # Step 6: Final verification that data is now available
        try:
            nltk.data.find(f"tokenizers/{package_id}")
            logger.debug("Verified NLTK %s data is now available", package_id)
        except LookupError as e:
            logger.error("NLTK %s data missing after download attempt", package_id)
            logger.info("Manual fix: python -m nltk.downloader %s -d %s", package_id, venv_nltk_data)
            raise RuntimeError(f"NLTK {package_id} data verification failed after download") from e
