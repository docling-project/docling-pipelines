# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Detection and in-memory decryption of password-protected documents.

Encrypted PDF and OOXML (``.docx``, ``.pptx``, ``.xlsx``) documents are decrypted after
their bytes are fetched and before any text extraction provider or entity extraction
adapter sees them, so every provider shares the same pooled Docling converter and no
password ever reaches Docling's format options.

Candidate passwords come from the ``document_passwords`` operator parameter. Passwords are
held as ``SecretStr`` and are never logged, stored in the table, or included in failure
reasons. Decrypted bytes only replace the ``binary_content`` of the in-memory fetch task.
"""

import fnmatch
import io
import logging
import threading
from concurrent.futures import Future
from pathlib import PurePath
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.integrations.secrets.secret_provider import is_vault_reference
from docpipe.integrations.secrets.secret_value import reveal_value
from docpipe.utils.infrastructure.logging import get_logger

logger: logging.Logger = get_logger()

_PDF_EXTENSION = ".pdf"
_PDF_HEADER = b"%PDF-"
_PDF_HEADER_SEARCH_BYTES = 1024
_PDF_ENCRYPT_KEY = b"/Encrypt"
_PDFIUM_LOCKED_ERROR_TEXT = "incorrect password"
_OOXML_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Upper bound on candidates per rule (and for ``default``): every rejected OOXML candidate costs a full
# key derivation, and decryption runs serially before extraction tasks are submitted.
MAX_CANDIDATES = 10
# Key under which the ``default`` list remembers its winning candidate
_DEFAULT_GROUP = -1
_ENCRYPTED_PACKAGE_MARKER = "EncryptedPackage".encode("utf-16-le")

# Used only when Docling is not installed; Docling's own lock is preferred so that PDFium is
# never entered concurrently with a conversion running in another micro-batch thread.
_FALLBACK_PDFIUM_LOCK = threading.Lock()


class DocumentPasswordsConfigError(ValueError):
    """Raised when ``document_passwords`` is malformed. Messages never contain password values."""

    def __init__(self, *, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


class DocumentDecryptionError(Exception):
    """Raised when an encrypted document cannot be decrypted."""

    def __init__(self, *, failure_reason: str, message: str) -> None:
        super().__init__(message)
        self.failure_reason = failure_reason
        self.message = message


def _require_non_empty(password: SecretStr) -> SecretStr:
    """Reject an empty password without echoing any value."""
    if not password.get_secret_value():
        msg = "password must be a non-empty string"
        raise ValueError(msg)
    return password


Password = Annotated[SecretStr, AfterValidator(_require_non_empty)]


class PasswordRule(BaseModel):
    """One ordered rule: documents whose name or path matches ``match`` use ``passwords``."""

    model_config = ConfigDict(extra="forbid")

    match: str = Field(min_length=1)
    passwords: list[Password] = Field(min_length=1, max_length=MAX_CANDIDATES)


class DocumentPasswordsConfig(BaseModel):
    """Parsed ``document_passwords`` operator parameter."""

    model_config = ConfigDict(extra="forbid")

    rules: list[PasswordRule] = Field(default_factory=list)
    default: list[Password] = Field(default_factory=list, max_length=MAX_CANDIDATES)

    @classmethod
    def from_config(cls, value: Any) -> "DocumentPasswordsConfig":
        """Parse the raw parameter; ``None`` means no passwords are configured.

        Raises:
            DocumentPasswordsConfigError: If the value is malformed. Each message names the
                location and the problem, never the input value.
        """
        if value is None:
            return cls()
        try:
            # A vault:// reference arrives resolved as an opaque SecretValue; the password is consumed
            # here, straight into SecretStr, and never held as plain text afterwards.
            return cls.model_validate(reveal_value(value))
        except ValidationError as exc:
            raise DocumentPasswordsConfigError(messages=cls._describe_errors(exc=exc)) from None

    @staticmethod
    def _describe_errors(*, exc: ValidationError) -> list[str]:
        """Build error messages from each error's location and message only."""
        messages: list[str] = []
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            location = OperatorConstants.Config.DOCUMENT_PASSWORDS
            for part in error["loc"]:
                location += f"[{part}]" if isinstance(part, int) else f".{part}"
            messages.append(f"{location}: {error['msg']}")
        return messages

    def plain_text_password_locations(self) -> list[str]:
        """Return the locations of passwords given as plain text rather than ``vault://`` references.

        ``ExtractOperator.validate()`` reports each one as a validation error.

        Only meaningful during flow validation, where vault references have been replaced by
        the validation placeholder; at runtime every value has already been resolved.
        """
        key = OperatorConstants.Config.DOCUMENT_PASSWORDS
        locations: list[str] = []
        for rule_index, rule in enumerate(self.rules):
            for password_index, password in enumerate(rule.passwords):
                if self._is_plain_text(password=password):
                    locations.append(f"{key}.rules[{rule_index}].passwords[{password_index}]")
        for password_index, password in enumerate(self.default):
            if self._is_plain_text(password=password):
                locations.append(f"{key}.default[{password_index}]")
        return locations

    @staticmethod
    def _is_plain_text(*, password: SecretStr) -> bool:
        """Return True when the value is neither a ``vault://`` reference nor the validation placeholder."""
        value = password.get_secret_value()
        return not is_vault_reference(value) and value != DocpipeConstants.VALIDATION_SECRET_SENTINEL

    def candidates_for(self, *, name: str, path: str | None) -> list[SecretStr]:
        """Return the candidate passwords of the first rule matching ``name`` or ``path``, else ``default``."""
        return self.candidate_group_for(name=name, path=path)[1]

    def candidate_group_for(self, *, name: str, path: str | None) -> tuple[int, list[SecretStr]]:
        """Return ``(group, candidates)`` for the first rule matching ``name`` or ``path``, else ``default``.

        ``group`` is the rule's index, or ``-1`` for ``default``; it identifies the list when
        remembering which candidate last worked. Backslashes in ``path`` are treated as ``/`` so one
        POSIX-style pattern also matches Windows paths. ``name`` is matched as is.
        """
        posix_path = path.replace("\\", "/") if path is not None else None
        for index, rule in enumerate(self.rules):
            if fnmatch.fnmatchcase(name, rule.match) or (
                posix_path is not None and fnmatch.fnmatchcase(posix_path, rule.match)
            ):
                return index, rule.passwords
        return _DEFAULT_GROUP, self.default


class DocumentDecryptor:
    """Detects encrypted PDF and OOXML documents and decrypts them in memory.

    Detection runs whether or not passwords are configured, so an encrypted document fails
    with an explicit, recoverable reason instead of a Docling error.
    """

    # Task key holding the failed extraction result for a document that could not be decrypted
    FAILED_RESULT_KEY = "decryption_failed_result"

    def __init__(self, *, passwords_config: DocumentPasswordsConfig) -> None:
        self.passwords_config = passwords_config
        # Index of the candidate that last opened a document, per rule (or ``default``). Documents
        # matching one rule almost always share a password, so trying it first avoids repeating
        # key derivations for every rejected candidate. Held in memory only.
        self._winners: dict[int, int] = {}
        self._winners_lock = threading.Lock()

    def decrypt_tasks(self, *, tasks: list[dict[str, Any]]) -> None:
        """Decrypt the ``binary_content`` of each fetched task in place.

        Tasks whose document cannot be decrypted get a failed extraction result under
        ``FAILED_RESULT_KEY``; callers report it instead of running extraction. Rules are matched
        against the task's ``doc_name`` and its optional ``path`` key.
        """
        for task in tasks:
            data = task.get(OperatorConstants.Columns.BINARY_CONTENT)
            if OperatorConstants.Extraction.ERROR in task or not isinstance(data, bytes):
                continue
            name = str(task["doc_name"])
            path = task.get(OperatorConstants.Columns.PATH)
            try:
                task[OperatorConstants.Columns.BINARY_CONTENT] = self._decrypt_document(
                    name=name, path=str(path) if path is not None else None, data=data
                )
            except DocumentDecryptionError as exc:
                logger.warning("Could not decrypt password-protected document %s: %s", name, exc.failure_reason)
                task[self.FAILED_RESULT_KEY] = {
                    OperatorConstants.Extraction.SUCCESS: False,
                    OperatorConstants.Extraction.ERROR: exc.message,
                    OperatorConstants.Extraction.FAILURE_REASON: exc.failure_reason,
                    OperatorConstants.Columns.DOC_COLUMN_DEFAULT: None,
                }
            except Exception as exc:
                # A corrupt document can make PDFium or msoffcrypto raise something other than their
                # own error types (ValueError, struct.error, OSError, ...). One bad document must not
                # fail the whole batch: keep the original bytes and let extraction report the problem
                # as it did before this feature. Only the exception type is logged; the message and
                # traceback are left out because they come from code that handles passwords.
                logger.warning(
                    "Encryption check failed for %s (%s); passing the document through unchanged",
                    name,
                    type(exc).__name__,
                )

    @classmethod
    def failed_result_future(cls, *, task: dict[str, Any]) -> Future | None:
        """Return an already-completed future carrying the task's failed result, if it has one."""
        failed_result = task.get(cls.FAILED_RESULT_KEY)
        if failed_result is None:
            return None
        future: Future = Future()
        future.set_result(failed_result)
        return future

    def _decrypt_document(self, *, name: str, path: str | None, data: bytes) -> bytes:
        """Return decrypted bytes for an encrypted document, or ``data`` unchanged otherwise."""
        suffix = PurePath(name).suffix.lower()
        # The PDF test comes first on purpose: it also catches PDFs with a wrong extension, and a
        # non-PDF that happens to contain the header is harmless because _decrypt_pdf returns early
        # when the bytes carry no /Encrypt key or PDFium opens them without a password.
        if suffix == _PDF_EXTENSION or _PDF_HEADER in data[:_PDF_HEADER_SEARCH_BYTES]:
            return self._decrypt_pdf(name=name, path=path, data=data)
        if suffix in _OOXML_EXTENSIONS and data.startswith(_OLE_SIGNATURE):
            return self._decrypt_ooxml(name=name, path=path, data=data)
        return data

    def _decrypt_pdf(self, *, name: str, path: str | None, data: bytes) -> bytes:
        """Return decrypted PDF bytes, or ``data`` unchanged when the PDF opens without a password."""
        # Every encrypted PDF names its encryption dictionary in an uncompressed trailer or
        # cross-reference stream dictionary, so a missing key means it is not encrypted.
        if _PDF_ENCRYPT_KEY not in data:
            return data
        try:
            import pypdfium2 as pdfium
            import pypdfium2.raw as pdfium_c
        except ImportError:
            logger.debug("pypdfium2 is not installed; cannot check %s for encryption", name)
            return data

        with self._pdfium_lock():
            # Try without a password first: PDFium returns the same "incorrect password" error for a
            # missing and a wrong password, so this is the only way to tell "needs a password" from
            # "rejected our candidate". Do not drop or reorder this step.
            try:
                pdfium.PdfDocument(data).close()
                # Opens without a password: not encrypted, or protected by an owner password only.
                return data
            except pdfium.PdfiumError as exc:
                if _PDFIUM_LOCKED_ERROR_TEXT not in str(exc).lower():
                    # Some other problem; let extraction report it as it does today.
                    return data

            group, candidates = self.passwords_config.candidate_group_for(name=name, path=path)
            if not candidates:
                raise self._password_required()
            for index, candidate in self._ordered_candidates(group=group, candidates=candidates):
                try:
                    document = pdfium.PdfDocument(data, password=candidate.get_secret_value())
                except pdfium.PdfiumError:
                    continue
                self._remember_winner(group=group, index=index)
                try:
                    buffer = io.BytesIO()
                    document.save(buffer, flags=pdfium_c.FPDF_REMOVE_SECURITY)
                finally:
                    document.close()
                # The matching candidate is deliberately not logged: its position would reveal which
                # password opened the document.
                logger.info("Decrypted password-protected PDF %s", name)
                return buffer.getvalue()
        raise self._password_incorrect(candidate_count=len(candidates))

    def _decrypt_ooxml(self, *, name: str, path: str | None, data: bytes) -> bytes:
        """Return decrypted OOXML bytes, or ``data`` unchanged when the file is not an encrypted package."""
        try:
            import msoffcrypto
            from msoffcrypto.exceptions import DecryptionError, FileFormatError, InvalidKeyError
        except ImportError:
            if _ENCRYPTED_PACKAGE_MARKER in data:
                raise DocumentDecryptionError(
                    failure_reason=OperatorConstants.Extraction.DECRYPTION_UNAVAILABLE,
                    message=(
                        f"{OperatorConstants.Extraction.DECRYPTION_UNAVAILABLE}: Document is an encrypted Office "
                        "file, but Office decryption is not installed. Install docling-pipelines-slim[extract] "
                        "or msoffcrypto-tool."
                    ),
                ) from None
            return data

        try:
            if not msoffcrypto.OfficeFile(io.BytesIO(data)).is_encrypted():
                return data
        except DecryptionError:
            raise self._unsupported_office_encryption() from None
        except (FileFormatError, OSError):
            # Not an Office container this library understands; let extraction report it.
            return data

        group, candidates = self.passwords_config.candidate_group_for(name=name, path=path)
        if not candidates:
            raise self._password_required()
        for index, candidate in self._ordered_candidates(group=group, candidates=candidates):
            output = io.BytesIO()
            try:
                office_file = msoffcrypto.OfficeFile(io.BytesIO(data))
                office_file.load_key(password=candidate.get_secret_value(), verify_password=True)
                office_file.decrypt(output)
            except InvalidKeyError:
                continue
            except DecryptionError:
                raise self._unsupported_office_encryption() from None
            self._remember_winner(group=group, index=index)
            logger.info("Decrypted password-protected Office document %s", name)
            return output.getvalue()
        raise self._password_incorrect(candidate_count=len(candidates))

    def _ordered_candidates(self, *, group: int, candidates: list[SecretStr]) -> list[tuple[int, SecretStr]]:
        """Return ``(index, candidate)`` pairs with the group's last winner first, the rest in configured order."""
        with self._winners_lock:
            winner = self._winners.get(group)
        ordered = list(enumerate(candidates))
        if winner is not None and 0 < winner < len(ordered):
            ordered.insert(0, ordered.pop(winner))
        return ordered

    def _remember_winner(self, *, group: int, index: int) -> None:
        """Record which candidate last opened a document for the rule (or ``default``)."""
        with self._winners_lock:
            self._winners[group] = index

    @staticmethod
    def _pdfium_lock() -> Any:
        """Return Docling's PDFium lock, or a local fallback when Docling is not installed."""
        try:
            from docling.utils.locks import pypdfium2_lock
        except ImportError:
            return _FALLBACK_PDFIUM_LOCK
        return pypdfium2_lock

    @staticmethod
    def _password_required() -> DocumentDecryptionError:
        """Build the error for an encrypted document with no applicable candidate password."""
        return DocumentDecryptionError(
            failure_reason=OperatorConstants.Extraction.PASSWORD_REQUIRED,
            message=(
                f"{OperatorConstants.Extraction.PASSWORD_REQUIRED}: Document is password-protected and no "
                "password in document_passwords applies to it."
            ),
        )

    @staticmethod
    def _password_incorrect(*, candidate_count: int) -> DocumentDecryptionError:
        """Build the error for an encrypted document that rejected every candidate password."""
        return DocumentDecryptionError(
            failure_reason=OperatorConstants.Extraction.PASSWORD_INCORRECT,
            message=(
                f"{OperatorConstants.Extraction.PASSWORD_INCORRECT}: Document is password-protected and none of "
                f"the {candidate_count} configured password(s) opened it."
            ),
        )

    @staticmethod
    def _unsupported_office_encryption() -> DocumentDecryptionError:
        """Build the error for an Office encryption scheme the library cannot decrypt."""
        return DocumentDecryptionError(
            failure_reason=OperatorConstants.Extraction.DECRYPTION_UNAVAILABLE,
            message=(
                f"{OperatorConstants.Extraction.DECRYPTION_UNAVAILABLE}: Document uses an Office encryption "
                "scheme that cannot be decrypted."
            ),
        )
