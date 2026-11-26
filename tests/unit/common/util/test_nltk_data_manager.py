# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for NLTK Data Manager
"""

import ssl
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import nltk
import pytest

from docpipe.utils.infrastructure.nltk_data_manager import (
    UnverifiedNLTKDownloader,
    ensure_nltk_data,
)


class TestUnverifiedNLTKDownloader:
    """Test suite for UnverifiedNLTKDownloader class"""

    def test_downloader_initialization(self, tmp_path):
        """Test that downloader initializes correctly"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        assert downloader.download_dir == download_dir
        assert downloader.ssl_context is not None
        assert isinstance(downloader.ssl_context, ssl.SSLContext)
        assert downloader.downloader is not None

    def test_ssl_context_is_unverified(self, tmp_path):
        """Test that SSL context is configured to not verify certificates"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        # Unverified context should have check_hostname=False
        assert downloader.ssl_context.check_hostname is False
        # Unverified context should have verify_mode=CERT_NONE
        assert downloader.ssl_context.verify_mode == ssl.CERT_NONE

    @patch("nltk.downloader.Downloader.download")
    def test_download_success(self, mock_download, tmp_path):
        """Test successful download with SSL bypass"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        # Mock successful download
        mock_download.return_value = True

        result = downloader.download("punkt_tab", quiet=True)

        assert result is True
        mock_download.assert_called_once_with("punkt_tab", quiet=True)

    @patch("nltk.downloader.Downloader.download")
    def test_download_failure(self, mock_download, tmp_path):
        """Test download failure handling"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        # Mock failed download
        mock_download.return_value = False

        result = downloader.download("punkt_tab", quiet=True)

        assert result is False

    @patch("nltk.downloader.Downloader.download")
    def test_download_with_exception(self, mock_download, tmp_path):
        """Test that exceptions during download are propagated"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        # Mock download that raises exception
        mock_download.side_effect = RuntimeError("Download failed")

        with pytest.raises(RuntimeError, match="Download failed"):
            downloader.download("punkt_tab", quiet=True)

    @patch("nltk.downloader.urlopen")
    @patch("nltk.downloader.Downloader.download")
    def test_urlopen_monkey_patch_restored(self, mock_download, mock_urlopen, tmp_path):
        """Test that urlopen is restored after download, even on failure"""
        download_dir = str(tmp_path / "nltk_data")
        downloader = UnverifiedNLTKDownloader(download_dir)

        # Save original urlopen reference
        import nltk.downloader

        original_urlopen = nltk.downloader.urlopen

        # Mock download that raises exception
        mock_download.side_effect = RuntimeError("Test error")

        try:
            downloader.download("punkt_tab", quiet=True)
        except RuntimeError:
            pass

        # Verify urlopen was restored to original
        assert nltk.downloader.urlopen == original_urlopen

    def test_patched_urlopen_injects_unverified_context(self, tmp_path):
        """While downloading, nltk's urlopen forwards calls with the unverified SSL context"""
        import nltk.downloader

        downloader = UnverifiedNLTKDownloader(str(tmp_path / "nltk_data"))
        seen = {}

        def fake_download(package_id, quiet=False):
            seen["response"] = nltk.downloader.urlopen("https://example.invalid/index.xml", timeout=5)
            return True

        with (
            patch("urllib.request.urlopen", return_value="response") as mock_urlopen,
            patch.object(downloader.downloader, "download", side_effect=fake_download),
        ):
            assert downloader.download("punkt_tab", quiet=True) is True

        assert seen["response"] == "response"
        mock_urlopen.assert_called_once_with(
            "https://example.invalid/index.xml", timeout=5, context=downloader.ssl_context
        )


class TestEnsureNLTKData:
    """Test suite for ensure_nltk_data function"""

    @patch("nltk.data.find")
    def test_early_exit_when_data_exists(self, mock_find):
        """Test that function exits early if data already exists"""
        # Mock that data is found
        mock_find.return_value = "/path/to/punkt_tab"

        # Should not raise any exceptions
        ensure_nltk_data("punkt_tab")

        # Verify find was called
        mock_find.assert_called_once_with("tokenizers/punkt_tab")

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_successful_standard_download(self, mock_download, mock_find, tmp_path):
        """Test successful download with standard SSL verification"""
        # First call: data not found, second call: data found after download
        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]
        mock_download.return_value = True

        ensure_nltk_data("punkt_tab")

        # Verify download was called
        assert mock_download.call_count == 1
        # Verify find was called twice (check before and after download)
        assert mock_find.call_count == 2

    @patch("nltk.data.find")
    @patch("nltk.download")
    @patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader")
    def test_ssl_error_triggers_retry(self, mock_unverified_downloader, mock_download, mock_find):
        """Test that SSL errors trigger retry with unverified downloader"""
        # First call: data not found, second call: data found after retry
        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]

        # Standard download fails with SSL error
        mock_download.side_effect = ssl.SSLError("Certificate verify failed")

        # Mock unverified downloader success
        mock_downloader_instance = Mock()
        mock_downloader_instance.download.return_value = True
        mock_unverified_downloader.return_value = mock_downloader_instance

        ensure_nltk_data("punkt_tab")

        # Verify unverified downloader was used
        mock_unverified_downloader.assert_called_once()
        mock_downloader_instance.download.assert_called_once_with("punkt_tab", quiet=False)

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_connection_error_triggers_retry(self, mock_download, mock_find):
        """Test that connection errors trigger SSL bypass retry"""
        # First call: data not found, second call: data found after retry
        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]

        # Standard download returns False (SSL failure)
        mock_download.return_value = False

        with patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader") as mock_unverified:
            mock_downloader_instance = Mock()
            mock_downloader_instance.download.return_value = True
            mock_unverified.return_value = mock_downloader_instance

            ensure_nltk_data("punkt_tab")

            # Verify unverified downloader was used
            mock_unverified.assert_called_once()

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_non_ssl_error_not_retried(self, mock_download, mock_find):
        """Test that non-SSL errors are not retried"""
        mock_find.side_effect = LookupError("Not found")
        mock_download.side_effect = ValueError("Invalid package name")

        with pytest.raises(ValueError, match="Invalid package name"):
            ensure_nltk_data("punkt_tab")

    @patch("nltk.data.find")
    @patch("nltk.download")
    @patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader")
    def test_all_retries_fail(self, mock_unverified_downloader, mock_download, mock_find):
        """Test that RuntimeError is raised when all retries fail"""
        mock_find.side_effect = LookupError("Not found")
        mock_download.side_effect = ssl.SSLError("Certificate verify failed")

        # Mock unverified downloader also fails
        mock_downloader_instance = Mock()
        mock_downloader_instance.download.return_value = False
        mock_unverified_downloader.return_value = mock_downloader_instance

        with pytest.raises(RuntimeError, match="Failed to download NLTK"):
            ensure_nltk_data("punkt_tab")

    @patch("nltk.data.find")
    @patch("nltk.download")
    @patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader")
    def test_verification_fails_after_download(self, mock_unverified_downloader, mock_download, mock_find):
        """Test that RuntimeError is raised if verification fails after download"""
        # First call: not found, second call: still not found after download
        mock_find.side_effect = [
            LookupError("Not found"),
            LookupError("Still not found"),
        ]
        mock_download.side_effect = ssl.SSLError("Certificate verify failed")

        # Mock successful unverified download
        mock_downloader_instance = Mock()
        mock_downloader_instance.download.return_value = True
        mock_unverified_downloader.return_value = mock_downloader_instance

        with pytest.raises(RuntimeError, match="verification failed after download"):
            ensure_nltk_data("punkt_tab")

    @patch("nltk.data.path", [])
    @patch("nltk.data.find")
    def test_nltk_data_path_setup(self, mock_find):
        """Test that NLTK data path is properly set up"""
        import sys

        mock_find.return_value = "/path/to/punkt_tab"

        ensure_nltk_data("punkt_tab")

        # Verify venv nltk_data path was added
        venv_nltk_data = str(Path(sys.prefix) / "nltk_data")
        assert venv_nltk_data in nltk.data.path

    def test_thread_safety(self):
        """Test that concurrent calls are properly synchronized"""
        call_order = []
        lock_acquired_count = [0]

        def mock_ensure_nltk_data(package_id):
            """Mock function that tracks call order"""
            import time

            from docpipe.utils.infrastructure.nltk_data_manager import (
                _nltk_lock,
            )

            with _nltk_lock:
                lock_acquired_count[0] += 1
                call_order.append(threading.current_thread().name)
                time.sleep(0.1)  # Simulate work

        threads = []
        for i in range(3):
            thread = threading.Thread(target=mock_ensure_nltk_data, args=("punkt_tab",), name=f"Thread-{i}")
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All threads should have acquired the lock
        assert lock_acquired_count[0] == 3
        # All threads should have completed
        assert len(call_order) == 3

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_ssl_error_exception_detection(self, mock_download, mock_find):
        """Test that ssl.SSLError exceptions trigger retry with SSL bypass"""
        import ssl

        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]

        # Test with actual ssl.SSLError
        mock_download.side_effect = ssl.SSLError("certificate verify failed")

        with patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader") as mock_unverified:
            mock_downloader_instance = Mock()
            mock_downloader_instance.download.return_value = True
            mock_unverified.return_value = mock_downloader_instance

            ensure_nltk_data("punkt_tab")

            # Verify unverified downloader was used
            mock_unverified.assert_called_once()

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_connection_error_exception_detection(self, mock_download, mock_find):
        """Test that ConnectionError exceptions trigger retry with SSL bypass"""
        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]

        # Test with ConnectionError (raised when nltk.download returns False)
        mock_download.side_effect = ConnectionError("NLTK download returned False")

        with patch("docpipe.utils.infrastructure.nltk_data_manager.UnverifiedNLTKDownloader") as mock_unverified:
            mock_downloader_instance = Mock()
            mock_downloader_instance.download.return_value = True
            mock_unverified.return_value = mock_downloader_instance

            ensure_nltk_data("punkt_tab")

            # Verify unverified downloader was used
            mock_unverified.assert_called_once()

    @patch("nltk.data.find")
    @patch("nltk.download")
    def test_custom_package_id(self, mock_download, mock_find):
        """Test downloading a custom package ID"""
        mock_find.side_effect = [LookupError("Not found"), "/path/to/custom_package"]
        mock_download.return_value = True

        ensure_nltk_data("custom_package")

        # Verify correct package was requested
        mock_find.assert_any_call("tokenizers/custom_package")
        assert mock_download.call_count == 1

    @patch("nltk.data.find")
    @patch("nltk.download")
    @patch("pathlib.Path.mkdir")
    def test_download_directory_creation(self, mock_mkdir, mock_download, mock_find):
        """Test that download directory is created if it doesn't exist"""
        mock_find.side_effect = [LookupError("Not found"), "/path/to/punkt_tab"]
        mock_download.return_value = True

        ensure_nltk_data("punkt_tab")

        # Verify mkdir was called with correct parameters
        mock_mkdir.assert_called_once_with(exist_ok=True, parents=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
