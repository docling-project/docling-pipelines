# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Ollama Client Wrapper for PII and HAP Detection.

Provides a simplified interface for interacting with Ollama models,
with support for JSON output parsing and retry logic.
"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any

import ollama
from ollama import GenerateResponse
from ollama._types import ChatResponse

from docpipe.core.constants.constants import ServiceConstants
from docpipe.exceptions.docpipe_exceptions import TROUBLESHOOTING_DOCS_URL, ConfigurationError, DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.base_llm_client import BaseLLMClient, retry_with_backoff
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Ollama model token limits (approximate)
OLLAMA_MODEL_TOKEN_LIMITS: dict[str, int] = {
    "llama2": 4096,
    "llama3": 8192,
    "llama3.1": 128000,
    "llama3.2": 128000,
    "mistral": 8192,
    "mixtral": 32768,
    "codellama": 16384,
    "phi": 2048,
    "gemma": 8192,
    "qwen": 32768,
    "deepseek-coder": 16384,
    "neural-chat": 4096,
    "starling-lm": 8192,
    "vicuna": 4096,
    "orca-mini": 4096,
    "wizard-vicuna": 4096,
    "nous-hermes": 4096,
    "openhermes": 8192,
    "granite3.2:2b": 128000,
    "granite3.2:8b": 128000,
    "granite4": 131072,
}

# Default token limit for unknown models
DEFAULT_TOKEN_LIMIT = 4096


class InteractionMode(Enum):
    """
    Defines the interaction modes supported by the wrapper.

    Supported modes:
    - GENERATE: Single-turn text generation
    - CHAT: Multi-turn conversational interactions
    - EMBEDDINGS: Generate vector embeddings for text
    """

    GENERATE = "generate"
    CHAT = "chat"
    EMBEDDINGS = "embeddings"


class OllamaClient(BaseLLMClient):
    """
    Wrapper for Ollama API interactions with JSON parsing support.

    This client provides a simplified interface for calling Ollama models
    with automatic JSON parsing and retry logic for robust operation.

    Extends BaseLLMClient to provide consistent interface across all LLM clients.
    """

    def __init__(
        self,
        *,
        model_name: str = "granite4",
        host: str | None = None,
        mode: InteractionMode = InteractionMode.GENERATE,
        system_prompt: str | None = None,
        validate_model: bool = True,
        timeout: float | None = None,
        max_concurrent_requests: int = ServiceConstants.DEFAULT_OLLAMA_MAX_CONCURRENT_REQUESTS,
        **kwargs,
    ):
        """
        Initialize the Ollama client.

        Args:
            model_name: Name of the Ollama model to use (e.g., "granite4", "llama3")
            host: Ollama server host URL (default: from OLLAMA_HOST env var or "http://localhost:11434")
            mode: Interaction mode (GENERATE, CHAT, or EMBEDDINGS) - Ollama-specific
            system_prompt: Optional system-level instructions for chat mode
            validate_model: Whether to validate model availability on initialization
            timeout: Timeout in seconds for API calls (default: None, no timeout)
            max_concurrent_requests: Maximum number of concurrent requests for batch embeddings (default: 8)
            **kwargs: Additional configuration parameters

        Raises:
            ImportError: If ollama package is not installed
            ValueError: If model validation is enabled and model is not available
        """
        super().__init__(model_name=model_name, **kwargs)

        self.host = host if host is not None else ServiceConstants.DEFAULT_OLLAMA_HOST
        self.mode = mode if isinstance(mode, InteractionMode) else InteractionMode(mode)
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.max_concurrent_requests = max_concurrent_requests

        logger.info(
            "Initialized OllamaClient: host=%s, model=%s, mode=%s, max_concurrent_requests=%s",
            self.host,
            model_name,
            self.mode.value,
            max_concurrent_requests,
        )

        if validate_model:
            self._validate_model()

    def _validate_model(self) -> None:
        """
        Validate that the specified model is available in Ollama.

        Raises:
            ImportError: If ollama package is not installed
            DocpipeException: If the model is not available or connection fails
        """
        try:
            import ollama
        except ImportError as exc:
            raise ImportError(f"ollama package not installed: {exc}") from exc

        try:
            # Create client with trust_env=False to avoid proxy issues
            client = ollama.Client(host=self.host, trust_env=False)
            # List available models
            models_response = client.list()
            # Handle both ListResponse object and dict formats for backward compatibility
            if hasattr(models_response, "models"):
                model_list = models_response.models
            elif isinstance(models_response, dict) and "models" in models_response:
                model_list = models_response["models"]
            else:
                model_list = []

            available_models = [m.model.split(":")[0] for m in model_list if m.model]

            # Check if the requested model is available
            model_base = self.model_name.split(":")[0]  # Handle model:tag format
            if model_base not in available_models:
                raise DocpipeException(
                    message=(
                        f"Model '{self.model_name}' is not available. "
                        f"Available models: {', '.join(available_models) if available_models else 'none'}. "
                        f"Please pull the model using: ollama pull {self.model_name}"
                    ),
                    status_code=404,
                    error_code=ErrorCode.OLLAMA_MODEL_NOT_FOUND,
                    more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-model-not-found",
                )

            logger.info("Model '%s' validated successfully", self.model_name)
        except DocpipeException:
            raise
        except (ConnectionError, TimeoutError) as exc:
            raise DocpipeException(
                message=f"Failed to connect to Ollama server: {exc}",
                status_code=503,
                error_code=ErrorCode.OLLAMA_CONNECTION_FAILED,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-connection-refused",
            ) from exc
        except Exception as exc:
            logger.warning("Could not validate model availability: %s", exc)
            # Don't fail initialization if validation check itself fails

    def run(self, *, prompt: str) -> str:
        """
        Execute the model with the given prompt.

        Args:
            prompt: Input text for the model

        Returns:
            Generated text as string

        Raises:
            ImportError: If ollama package is not installed
            Exception: For other errors during model execution
        """
        try:
            import ollama
        except ImportError as exc:
            raise ImportError(f"ollama package not installed: {exc}") from exc

        try:
            # Create client with trust_env=False to avoid proxy issues
            client = ollama.Client(host=self.host, trust_env=False)

            if self.mode == InteractionMode.CHAT:
                messages = []
                if self.system_prompt:
                    messages.append({"role": "system", "content": self.system_prompt})
                messages.append({"role": "user", "content": prompt})

                response: ChatResponse | GenerateResponse = client.chat(model=self.model_name, messages=messages)
                # When stream=False, response is a dict with the message content
                # Returns empty string if response format is unexpected (e.g., streaming mode not fully handled)
                # Handle both dict and ChatResponse object
                if isinstance(response, dict):
                    return response.get("message", {}).get("content", "")
                if hasattr(response, "message"):
                    # ChatResponse object
                    message = response.message
                    if isinstance(message, dict):
                        return message.get("content", "")
                    if hasattr(message, "content"):
                        return message.content or ""
                return ""  # Fallback for unexpected response format
            response = client.generate(model=self.model_name, prompt=prompt)
            # Handle both dict and GenerateResponse object
            if isinstance(response, dict):
                return response.get("response", "")
            if hasattr(response, "response"):
                # GenerateResponse object from newer ollama versions
                return response.response or ""
            logger.warning("Unexpected response type: %s", type(response).__name__)
            return ""
        except (ConnectionError, TimeoutError) as exc:
            logger.error("Connection failed: %s", exc)
            raise DocpipeException(
                message=f"Failed to connect to Ollama server: {exc}",
                status_code=503,
                error_code=ErrorCode.OLLAMA_CONNECTION_FAILED,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-connection-refused",
            ) from exc
        except ValueError as exc:
            logger.error("Invalid model or parameters: %s", exc)
            raise DocpipeException(
                message=f"Model '{self.model_name}' not found or invalid parameters: {exc}",
                status_code=404,
                error_code=ErrorCode.OLLAMA_MODEL_NOT_FOUND,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-model-not-found",
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error during model execution: %s", exc)
            raise

    def _parse_json_response(self, raw: str) -> dict[str, Any] | None:
        """
        Attempt to parse JSON from raw model output.

        Tries direct parsing first, then extracts from markdown/mixed content
        using JSONDecoder for robust handling of nested structures.

        Args:
            raw: Raw string output from model

        Returns:
            Parsed dict if successful, None otherwise
        """
        if not raw or not raw.strip():
            return None

        # Try direct JSON parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Look for JSON in markdown code blocks
        markdown_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if markdown_match:
            try:
                return json.loads(markdown_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try extracting JSON from mixed content using JSONDecoder
        try:
            decoder = json.JSONDecoder()
            # Find first valid JSON object
            idx = raw.find("{")
            if idx != -1:
                obj, _end_idx = decoder.raw_decode(raw, idx)
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find JSON array
        try:
            idx = raw.find("[")
            if idx != -1:
                decoder = json.JSONDecoder()
                obj, _end_idx = decoder.raw_decode(raw, idx)
                # Wrap array in expected format
                if isinstance(obj, list):
                    return {"detections": obj}
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def run_json(self, *, prompt: str, system_prompt: str | None = None, retries: int = 3) -> dict[str, Any]:
        """
        Run the model and enforce JSON output with retries.

        Args:
            prompt: The task prompt
            system_prompt: Optional system-level override
            retries: Number of times to retry parsing JSON

        Returns:
            dict parsed from model JSON output

        Raises:
            json.JSONDecodeError: If JSON parsing fails after all retries
        """
        base_instruction = (
            "You must respond with ONLY valid JSON. "
            "Do not include natural language, markdown, or commentary. "
            'If there are no detections, return: {"detections": []}'
        )

        prompt_parts = [base_instruction, "", prompt]
        last_raw = None

        for attempt in range(retries):
            full_prompt = "\n".join(prompt_parts)
            raw = self.run(prompt=full_prompt)
            last_raw = raw

            # Try parsing JSON
            parsed = self._parse_json_response(raw)
            if parsed is not None:
                return parsed

            if attempt < retries - 1:
                logger.warning("Failed to parse JSON from model (attempt %s/%s). Retrying...", attempt + 1, retries)
                # Add emphasis only once
                if len(prompt_parts) == 3:
                    prompt_parts.append("\nIMPORTANT: Respond ONLY with JSON, nothing else.")

        # If all retries fail, raise an exception with the last response
        raise json.JSONDecodeError(
            f"Failed to parse JSON after {retries} attempts. "
            f"Model: {self.model_name}, Mode: {self.mode.value}. "
            f"Last response: {last_raw[:200] if last_raw else 'None'}...",
            last_raw or "",
            0,
        )

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def generate_embeddings(self, text: str) -> list[float]:
        """
        Generate embeddings for the given text using Ollama.

        Args:
            text: Text to generate embeddings for

        Returns:
            List of floats representing the embedding vector

        Raises:
            Exception: For errors during embedding generation
        """
        self._validate_text_input(text=text)

        try:
            # Create client with trust_env=False to avoid proxy issues
            client = ollama.Client(host=self.host, trust_env=False)
            embedding_response = client.embeddings(model=self.model_name, prompt=text)

            # Handle both dict and EmbeddingsResponse object types
            if isinstance(embedding_response, dict):
                embedding = embedding_response.get("embedding")
            elif hasattr(embedding_response, "embedding"):
                # Handle EmbeddingsResponse object from newer ollama versions
                embedding = embedding_response.embedding
            else:
                raise DocpipeException(
                    message=f"Unexpected response type from model '{self.model_name}': {type(embedding_response).__name__}",
                    status_code=500,
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                )

            if not isinstance(embedding, list) or not embedding:
                raise DocpipeException(
                    message=f"Empty or missing embedding in response from model '{self.model_name}'.",
                    status_code=500,
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                )

            self._validate_embeddings_output(embedding)
            return embedding

        except (ConnectionError, TimeoutError) as exc:
            logger.error("Connection failed during embedding generation: %s", exc)
            raise DocpipeException(
                message=f"Failed to connect to Ollama server during embedding generation: {exc}",
                status_code=503,
                error_code=ErrorCode.OLLAMA_CONNECTION_FAILED,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-connection-refused",
            ) from exc

        except DocpipeException:
            raise

        except (ValueError, TypeError) as exc:
            logger.error("Invalid response structure from Ollama API: %s", exc)
            raise DocpipeException(
                message=f"Invalid response from Ollama API: {exc}",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            ) from exc

        except Exception as exc:
            logger.exception("Unexpected error during embedding generation")
            raise DocpipeException(
                message=f"Unexpected error during embedding generation: {exc}",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            ) from exc

    def _generate_single_embedding(self, *, client: Any, index: int, text: str) -> tuple[int, list[float]]:
        """Generate embedding for a single text using the provided Ollama client.

        Args:
            client: An instantiated ollama.Client
            index: Original index of the text in the batch (used to preserve order)
            text: The text to embed

        Returns:
            Tuple of (original index, embedding vector)

        Raises:
            DocpipeException: If the response is unexpected or empty
        """
        embedding_response = client.embeddings(model=self.model_name, prompt=text)

        if isinstance(embedding_response, dict):
            embedding = embedding_response.get("embedding")
        elif hasattr(embedding_response, "embedding"):
            embedding = embedding_response.embedding
        else:
            raise DocpipeException(
                message=f"Unexpected response type: {type(embedding_response).__name__}",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            )

        if not isinstance(embedding, list) or not embedding:
            raise DocpipeException(
                message="Empty or missing embedding in response",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            )

        return index, embedding

    def _collect_batch_results(
        self,
        *,
        futures: dict,
        all_embeddings: list,
        executor: Any,
        lock: Any,
    ) -> None:
        """Collect results from completed futures into all_embeddings, raising on first failure.

        Args:
            futures: Dict mapping futures to their original indices
            all_embeddings: Pre-allocated list to write results into (mutated in place)
            executor: The ThreadPoolExecutor (used to cancel remaining futures on error)
            lock: Threading lock protecting all_embeddings writes
        """
        for future in as_completed(futures):
            try:
                index, embedding = future.result()
                with lock:
                    all_embeddings[index] = embedding
            except Exception as e:
                executor.shutdown(wait=False, cancel_futures=True)
                raise DocpipeException(
                    message=f"Batch embedding generation failed: {e}",
                    status_code=500,
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                ) from e

    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts using concurrent requests.

        Since Ollama doesn't have native batch support, this method uses
        concurrent requests to improve throughput by 20-30%.

        The number of concurrent requests is configured via max_concurrent_requests
        parameter during client initialization (default: 8).

        Args:
            texts: List of input texts to generate embeddings for

        Returns:
            List of embedding vectors, one per input text

        Raises:
            DocpipeException: If embedding generation fails
        """
        if not texts or not isinstance(texts, list):
            raise ConfigurationError("texts must be a non-empty list")

        if not all(isinstance(t, str) and t for t in texts):
            raise ConfigurationError("all texts must be non-empty strings")

        client = ollama.Client(host=self.host, trust_env=False)
        all_embeddings: list[list[float] | None] = [None] * len(texts)
        lock = threading.Lock()

        try:
            with ThreadPoolExecutor(max_workers=self.max_concurrent_requests) as executor:
                futures = {
                    executor.submit(self._generate_single_embedding, client=client, index=i, text=text): i
                    for i, text in enumerate(texts)
                }
                self._collect_batch_results(
                    futures=futures, all_embeddings=all_embeddings, executor=executor, lock=lock
                )

            if None in all_embeddings:
                raise DocpipeException(
                    message="Some embeddings failed to generate",
                    status_code=500,
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                )

            return all_embeddings  # type: ignore[return-value]

        except (ConnectionError, TimeoutError) as exc:
            logger.error("Connection failed during batch embedding generation: %s", exc)
            raise DocpipeException(
                message=f"Failed to connect to Ollama server: {exc}",
                status_code=503,
                error_code=ErrorCode.OLLAMA_CONNECTION_FAILED,
                more_info=f"{TROUBLESHOOTING_DOCS_URL}#issue-ollama-connection-refused",
            ) from exc

        except DocpipeException:
            raise

        except Exception as exc:
            logger.exception("Unexpected error during batch embedding generation")
            raise DocpipeException(
                message=f"Unexpected error during batch embedding generation: {exc}",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            ) from exc

    @staticmethod
    def is_installed() -> bool:
        """
        Check if Ollama CLI is installed on the system.

        Returns:
            bool: True if Ollama is installed, False otherwise
        """
        import shutil
        import subprocess  # nosec B404 — subprocess is used only to invoke the ollama CLI with a fixed command, not with user input

        ollama_path = shutil.which("ollama")
        if ollama_path is None:
            return False
        try:
            result = subprocess.run([ollama_path, "--version"], capture_output=True, text=True, timeout=5)  # nosec B603
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False

    @staticmethod
    def is_server_running(*, host: str | None = None) -> bool:
        """
        Check if Ollama server is running and accessible.

        Args:
            host: Ollama server host URL (default: from OLLAMA_HOST env var or "http://localhost:11434")

        Returns:
            bool: True if Ollama server is accessible, False otherwise
        """
        if host is None:
            host = ServiceConstants.DEFAULT_OLLAMA_HOST
        try:
            import ollama

            # Create client with trust_env=False to avoid proxy issues
            client = ollama.Client(host=host, trust_env=False)
            # Try to list models - this will fail if server is not running
            client.list()
            return True
        except Exception:
            return False

    @staticmethod
    def start_server(wait_timeout: int = 10) -> bool:
        """
        Start Ollama server in background.

        Args:
            wait_timeout: Maximum seconds to wait for server to start (default: 10)

        Returns:
            bool: True if server started successfully, False otherwise
        """
        import platform
        import shutil
        import subprocess  # nosec B404 — subprocess is used only to invoke the ollama CLI with fixed command arrays, not with user input
        import time

        try:
            system = platform.system()
            # Resolve absolute path to avoid B607 (partial executable path)
            ollama_path = shutil.which("ollama") or "ollama"

            if system == "Windows":
                # Windows: Start in background using START command
                # CREATE_NEW_PROCESS_GROUP is Windows-specific
                creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen(  # nosec B603 B607 — fixed command array, no user input interpolated
                    ["cmd", "/c", "start", "/B", ollama_path, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
            else:
                # macOS/Linux: Start in background using nohup
                subprocess.Popen(  # nosec B603 B607 — fixed command array, no user input interpolated
                    ["nohup", ollama_path, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=lambda: None,
                )

            # Wait for server to start
            logger.info("Starting Ollama server...")
            for i in range(wait_timeout):
                time.sleep(1)
                if OllamaClient.is_server_running():
                    logger.info("Ollama server started successfully")
                    return True
                logger.debug("Waiting for server... (%s/%s)", i + 1, wait_timeout)

            logger.warning("Ollama server may not have started properly")
            return False

        except Exception as e:
            logger.error("Failed to start Ollama server: %s", e)
            return False

    @staticmethod
    def is_model_available(model_name: str, *, host: str | None = None) -> bool:
        """
        Check if a model is already pulled in Ollama.

        Args:
            model_name: Name of the model to check
            host: Ollama server host URL (default: from OLLAMA_HOST env var or "http://localhost:11434")

        Returns:
            bool: True if model is available, False otherwise
        """
        if host is None:
            host = ServiceConstants.DEFAULT_OLLAMA_HOST
        try:
            import ollama

            # Create client with trust_env=False to avoid proxy issues
            client = ollama.Client(host=host, trust_env=False)
            models: Any = client.list()

            # Check if model exists in the list
            if hasattr(models, "models"):
                model_list = models.models
            elif isinstance(models, dict) and "models" in models:
                model_list = models["models"]
            else:
                model_list = models

            for model in model_list:
                # Handle both dict and object formats
                if isinstance(model, dict):
                    name = model.get("name", "")
                else:
                    name = getattr(model, "model", "")

                # Check if model name matches (handle version tags)
                if name.startswith(model_name) or name.split(":")[0] == model_name:
                    return True

            return False

        except Exception as e:
            logger.error("Failed to check model availability: %s", e)
            return False

    @staticmethod
    def pull_model(model_name: str, show_progress: bool = True) -> bool:
        """
        Pull an Ollama model.

        Args:
            model_name: Name of the model to pull
            show_progress: Whether to display progress output (default: True)

        Returns:
            bool: True if model pulled successfully, False otherwise
        """
        import shutil
        import subprocess  # nosec B404 — subprocess is used only to invoke the ollama CLI with a fixed command, not with user input

        try:
            if show_progress:
                logger.info("Pulling model '%s'... (this may take several minutes)", model_name)

            # Resolve absolute path to avoid B607 (partial executable path)
            ollama_path = shutil.which("ollama") or "ollama"
            # Use subprocess to show real-time progress
            process = subprocess.Popen(  # nosec B603 B607 — fixed command array, model_name is an internal config value not from untrusted user input
                [ollama_path, "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            # Stream output if progress is enabled
            if show_progress and process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        logger.debug("Pull progress: %s", line)

            process.wait()

            if process.returncode == 0:
                logger.info("Model '%s' pulled successfully", model_name)
                return True
            logger.error("Failed to pull model '%s'", model_name)
            return False

        except Exception as e:
            logger.error("Failed to pull model: %s", e)
            return False

    @classmethod
    def _ensure_server_running(cls, auto_start: bool) -> tuple[bool, str]:
        """
        Ensure Ollama server is running, optionally starting it.

        Args:
            auto_start: Whether to automatically start the server if not running

        Returns:
            tuple: (success: bool, error_message: str or empty)
        """
        if cls.is_server_running():
            return True, ""

        if not auto_start:
            return False, "Ollama server is not running. Start with: ollama serve"

        logger.info("Ollama server not running, attempting to start...")
        if cls.start_server():
            return True, ""

        return False, ("Failed to start Ollama server automatically. Please start it manually with: ollama serve")

    @classmethod
    def _ensure_model_available(cls, model_name: str, auto_pull: bool) -> tuple[bool, str]:
        """
        Ensure model is available, optionally pulling it.

        Args:
            model_name: Name of the model to check/pull
            auto_pull: Whether to automatically pull the model if not available

        Returns:
            tuple: (success: bool, error_message: str or empty)
        """
        if cls.is_model_available(model_name):
            return True, ""

        if not auto_pull:
            return (
                False,
                f"Model '{model_name}' not available. Pull with: ollama pull {model_name}",
            )

        logger.info("Model '%s' not found, attempting to pull...", model_name)
        if cls.pull_model(model_name, show_progress=False):
            return True, ""

        return False, (f"Failed to pull model '{model_name}'. Please pull it manually with: ollama pull {model_name}")

    @classmethod
    def ensure_ready(cls, model_name: str, auto_start: bool = True, auto_pull: bool = True) -> tuple[bool, str]:
        """
        Comprehensive readiness check with auto-remediation.

        This method checks if Ollama is installed, the server is running,
        and the specified model is available. It can automatically start
        the server and pull the model if requested.

        Args:
            model_name: Model to check/pull
            auto_start: Automatically start server if not running (default: True)
            auto_pull: Automatically pull model if not available (default: True)

        Returns:
            tuple: (success: bool, message: str) - Status and user-friendly message

        Example:
            >>> success, message = OllamaClient.ensure_ready("llama2")
            >>> if not success:
            ...     print(f"Error: {message}")
            >>> else:
            ...     client = OllamaClient(model="llama2")
        """
        # Guard clause: Check installation
        if not cls.is_installed():
            return (
                False,
                "Ollama is not installed. Install from: https://ollama.ai/download",
            )

        # Ensure server is running
        server_ok, server_msg = cls._ensure_server_running(auto_start)
        if not server_ok:
            return False, server_msg

        # Ensure model is available
        model_ok, model_msg = cls._ensure_model_available(model_name, auto_pull)
        if not model_ok:
            return False, model_msg

        return True, f"Ollama ready with model '{model_name}'"

    @staticmethod
    def get_model_token_limit(model_name: str) -> int:
        """
        Get the token limit for a specific Ollama model.

        Args:
            model_name: Name of the Ollama model

        Returns:
            Maximum token limit for the model
        """
        # Extract base model name (remove version tags)
        base_model = model_name.split(":")[0]
        return OLLAMA_MODEL_TOKEN_LIMITS.get(base_model, DEFAULT_TOKEN_LIMIT)

    @staticmethod
    def get_embedding_dimension(model_name: str) -> int:
        """
        Get the embedding dimension for a specific Ollama model.

        Args:
            model_name: Name of the Ollama model

        Returns:
            Embedding dimension (0 indicates runtime detection required)

        Note:
            Ollama embedding dimensions vary by model and require runtime detection.
            The OllamaAdapter class handles dimension detection via _detect_dimension().
        """
        # Return 0 to indicate dimension should be determined at runtime
        # This is consistent with LiteLLM's approach for models with unknown dimensions
        return 0

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt (single-turn).

        Delegates to run() method with current mode.

        Args:
            prompt: Input prompt for generation
            **kwargs: Additional generation parameters (currently unused)

        Returns:
            Generated text as string
        """
        return self.run(prompt=prompt)

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        Generate response from chat messages (multi-turn).

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional chat parameters (currently unused)

        Returns:
            Generated response as string
        """
        # Convert messages to prompt format
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                # System messages handled via system_prompt in constructor
                continue
            prompt_parts.append(content)

        prompt = "\n".join(prompt_parts)

        # Temporarily switch to CHAT mode if not already
        original_mode = self.mode
        self.mode = InteractionMode.CHAT
        try:
            return self.run(prompt=prompt)
        finally:
            self.mode = original_mode
