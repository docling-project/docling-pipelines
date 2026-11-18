"""
FastText Model Manager with Singleton Pattern and Reference Counting

This module provides a thread-safe singleton manager for the FastText language detection model.
It implements reference counting to efficiently manage model loading/unloading across parallel flows.

Key Features:
- Thread-safe singleton pattern with double-checked locking
- Reference counting for memory-efficient model sharing
- Lock timeout protection (60s for acquire, 10s for release)
- Graceful error handling with error state tracking
- Separate download lock to prevent concurrent downloads
- Automatic SSL fallback for corporate proxy environments
"""

import os
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from docpipe.utils.infrastructure.logging import get_logger


class FastTextConstants:
    """FastText language detection model configuration"""

    MODEL_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
    MODEL_FILENAME = "lid.176.ftz"
    MODEL_LOCAL_DIR = "models/fasttext"  # Relative to backend directory


logger = get_logger()


class FastTextModelManager:
    """
    Thread-safe singleton manager for FastText language detection model.

    Features:
    - Singleton pattern ensures only one model instance per process
    - Reference counting for efficient memory management
    - Automatic model download if not present (with download lock protection)
    - Thread-safe acquire/release operations with configurable timeouts
    - Error state tracking to prevent repeated failed load attempts
    - Graceful degradation when model loading fails

    Thread Safety:
    - Uses separate locks for model operations and downloads
    - Lock timeouts prevent indefinite blocking (60s acquire, 10s release)
    - Double-checked locking pattern for singleton and downloads
    """

    _instance: Optional["FastTextModelManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized: bool = True
        self._model = None
        self._ref_count = 0
        self._model_lock = threading.Lock()
        self._download_lock = threading.Lock()  # Separate lock for download operations
        self._model_path: Path | None = None
        self._load_failed = False
        self._load_error: Exception | None = None  # Store the error for reporting

        logger.info("FastTextModelManager initialized")

    def _get_model_path(self) -> Path:
        """
        Resolve the FastText model path.

        Checks the ``FASTTEXT_MODEL_PATH`` environment variable first.
        When set that path is used directly.

        Falls back to ``<tempdir>/models/fasttext/lid.176.ftz`` for local
        development so the auto-download path still works without any setup.

        Returns:
            Path to FastText model file
        """
        if self._model_path is not None:
            return self._model_path

        env_path = os.environ.get("FASTTEXT_MODEL_PATH")
        if env_path:
            self._model_path = Path(env_path)
        else:
            local_dir = Path(tempfile.gettempdir()) / FastTextConstants.MODEL_LOCAL_DIR
            local_dir.mkdir(parents=True, exist_ok=True)
            self._model_path = local_dir / FastTextConstants.MODEL_FILENAME

        logger.info("FastText model path: %s", self._model_path)
        return self._model_path

    def _download_model(self, model_path: Path) -> None:
        """
        Download FastText model if not present (local environment only).
        Thread-safe with download lock to prevent concurrent downloads.

        Args:
            model_path: Path where model should be downloaded
        """
        # Use separate download lock to prevent multiple threads from downloading simultaneously
        with self._download_lock:
            # Double-check after acquiring lock (another thread may have downloaded it)
            if model_path.exists():
                logger.info("FastText model already exists at %s", model_path)
                return

            model_url = FastTextConstants.MODEL_URL
            logger.info("Downloading FastText model from %s to %s", model_url, model_path)

            try:
                # Try with default SSL verification first
                try:
                    urllib.request.urlretrieve(model_url, model_path)  # nosec B310 — model_url is an internal constant (FastTextConstants.MODEL_URL), not user-supplied
                    logger.info("Model downloaded successfully with SSL verification")
                except (ssl.SSLError, urllib.error.URLError) as ssl_error:
                    # Fallback to unverified SSL for corporate proxies
                    logger.warning(
                        "SSL verification failed (%s), retrying with unverified context...",
                        ssl_error,
                    )
                    ssl_context = ssl._create_unverified_context()  # NOSONAR  # nosec B323 — intentional fallback for corporate proxy environments; primary attempt uses full SSL verification
                    with urllib.request.urlopen(model_url, context=ssl_context) as response:  # nosec B310 — intentional SSL fallback; only reached after verified attempt fails
                        with Path(model_path).open("wb") as out_file:
                            out_file.write(response.read())
                    logger.info("Model downloaded successfully with unverified SSL")

            except Exception as e:
                logger.error("Failed to download FastText model: %s", e)
                msg = f"Download failed. Manual download: curl -L {model_url} -o {model_path}"
                raise RuntimeError(msg) from e

    def _load_model(self):
        """
        Load the FastText model into memory.
        Called only when model is None and ref_count increases from 0.

        Raises:
            RuntimeError: If model loading fails
        """
        if self._model is not None:
            return  # Already loaded

        try:
            import fasttext

            model_path = self._get_model_path()

            # Download if not present (local mode only)
            if not model_path.exists():
                logger.info("Model not found at %s", model_path)
                self._download_model(model_path)

            logger.info("Loading FastText model from %s", model_path)
            self._model = fasttext.load_model(str(model_path))
            logger.info("FastText model loaded successfully")
            # Clear any previous error state on successful load
            self._load_failed = False
            self._load_error = None

        except Exception as e:
            logger.error("Failed to load FastText model: %s", e)
            self._load_failed = True
            self._load_error = e  # Store error for later reporting
            self._model = None
            msg = f"Failed to load FastText model: {e}"
            raise RuntimeError(msg) from e

    def acquire_model(self, timeout: float = 60.0):
        """
        Acquire the FastText model with reference counting and timeout.
        Loads the model on first acquisition.

        Args:
            timeout: Maximum time to wait for lock acquisition in seconds (default: 60)

        Returns:
            The FastText model instance, or None if loading failed

        Raises:
            RuntimeError: If lock cannot be acquired within timeout or if previous load failed
        """
        # Try to acquire lock with timeout
        if not self._model_lock.acquire(timeout=timeout):
            msg = (
                f"Failed to acquire model lock within {timeout} seconds. "
                "Another thread may be loading the model or the system is overloaded."
            )
            raise RuntimeError(msg)

        try:
            # Check if a previous load attempt failed
            if self._load_failed and self._load_error is not None:
                logger.error(
                    "Model loading previously failed. Not attempting to reload. Original error: %s",
                    self._load_error,
                )
                msg = f"FastText model loading previously failed: {self._load_error}"
                raise RuntimeError(msg) from self._load_error

            self._ref_count += 1
            logger.info("FastText model acquired. Reference count: %d", self._ref_count)

            if self._model is None and not self._load_failed:
                logger.info("First acquisition - loading FastText model")
                try:
                    self._load_model()
                except Exception as e:
                    logger.error("Model load failed: %s", e)
                    # Don't raise here - let caller handle None return

            return self._model
        finally:
            self._model_lock.release()

    def release_model(self, timeout: float = 10.0) -> None:
        """
        Release the FastText model with reference counting and timeout.
        Unloads the model when reference count reaches zero.

        Args:
            timeout: Maximum time to wait for lock acquisition in seconds (default: 10)

        Raises:
            RuntimeError: If lock cannot be acquired within timeout
        """
        if not self._model_lock.acquire(timeout=timeout):
            msg = f"Failed to acquire model lock for release within {timeout} seconds"
            raise RuntimeError(msg)

        try:
            if self._ref_count > 0:
                self._ref_count -= 1
                logger.info("FastText model released. Reference count: %d", self._ref_count)

                if self._ref_count == 0:
                    logger.info("Reference count reached zero - unloading FastText model")
                    self._model = None
                    # Clear error state when model is unloaded
                    self._load_failed = False
                    self._load_error = None
            else:
                logger.warning("Attempted to release FastText model with zero reference count")
        finally:
            self._model_lock.release()

    def get_ref_count(self) -> int:
        """
        Get current reference count with timeout protection.

        Returns:
            Current reference count, or -1 if lock cannot be acquired
        """
        if self._model_lock.acquire(timeout=1.0):
            try:
                return self._ref_count
            finally:
                self._model_lock.release()
        else:
            logger.warning("Could not acquire lock to get ref count")
            return -1

    def is_loaded(self) -> bool:
        """
        Check if model is currently loaded with timeout protection.

        Returns:
            True if model is loaded, False otherwise or if lock cannot be acquired
        """
        if self._model_lock.acquire(timeout=1.0):
            try:
                return self._model is not None
            finally:
                self._model_lock.release()
        else:
            logger.warning("Could not acquire lock to check if model is loaded")
            return False
