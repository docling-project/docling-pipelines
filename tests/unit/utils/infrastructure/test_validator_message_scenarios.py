# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Scenario tests for validator-authored messages in provider configuration models.

Each scenario builds a valid baseline, applies one mutated field whose value carries a sentinel, and checks
that the intended validator rejected it at the expected location. The sentinel must then be absent from the
output of ``format_pydantic_errors`` and ``sanitize_exception``. A blanket sentinel in every field is not used,
because an unrelated failure can stop the targeted validator from running.

Coverage exceptions (written reasons, per the change's tasks):

- ``pii_and_hap.watsonx``, ``pii_and_hap.litellm``, ``pii_and_hap.presidio``: plain fields, no custom validator.
- ``ingest.box``, ``storage.box`` credentials path, ``storage.filesystem`` and the ``folder_path`` and
  ``key_prefix`` normalisers of the Graph and S3 models: validators only expand environment variables, the home
  directory, slashes or extensions and never raise.
- The "<field> cannot be empty" validators (OneDrive, SharePoint and S3 ingest; S3, SharePoint and Box storage):
  they reject only a blank value, so the rejected input cannot carry a sentinel, and the message interpolates the
  field name, never the value.
- ``pii_and_hap.huggingface``: the model-level validator reflects ``model_id``. That is the one approved exception
  besides the filesystem root path, covered by its own scenario that asserts the identifier is present.

"""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from docpipe.core.constants.constants import ServiceConstants
from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.config import DropboxSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.config import FilesystemSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.config import GoogleDriveSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.onedrive.config import OneDriveSourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.s3.config import S3SourceConfig
from docpipe.core.operators.ingest.adapters.outbound.sources.sharepoint.config import SharePointSourceConfig
from docpipe.core.operators.quality.pii_and_hap.adapters.outbound.huggingface.config import HuggingFaceHAPConfig
from docpipe.core.operators.storage.adapters.outbound.destinations.google_drive.config import (
    GoogleDriveDestinationConfig,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.s3.config import S3DestinationConfig
from docpipe.core.operators.storage.adapters.outbound.destinations.sharepoint.config import (
    SharePointDestinationConfig,
)
from docpipe.core.operators.vectordb.adapters.outbound.weaviate.config import WeaviateConfig
from docpipe.utils.infrastructure.exception_sanitizer import format_pydantic_errors, sanitize_exception

SENTINEL = "SENTINEL-4c2a9e71-credential"
KEY = "provider_config"

# Model-level validators report an empty location; field validators report the field name.
MODEL_LEVEL: tuple[str, ...] = ()


def _weaviate_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a Weaviate baseline that validates with auth disabled."""
    return {"collection_name": "Documents", "connection_type": "on-prem", "auth_type": "none", **overrides}


def _weaviate_auth_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a Weaviate baseline with TLS on and API-key auth, so only the mutated field is at issue."""
    return _weaviate_baseline(
        auth_type="api_key",
        secure=True,
        grpc_secure=True,
        api_key="baseline-key",  # pragma: allowlist secret
        **overrides,
    )


def _dropbox_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a Dropbox baseline that validates with an access token."""
    return {"access_token": "baseline-token", **overrides}


def _gdrive_source_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a Google Drive source baseline that validates with one credential source."""
    return {"service_account_json_path": "/tmp/baseline-sa.json", **overrides}


def _gdrive_destination_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a Google Drive destination baseline that validates with one credential source."""
    return {"folder_id": "baseline-folder", "service_account_json_path": "/tmp/baseline-sa.json", **overrides}


def _onedrive_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a OneDrive source baseline that validates."""
    return {
        "client_id": "baseline-id",
        "client_secret": "baseline-secret",  # pragma: allowlist secret
        "tenant_id": "baseline-tenant",
        "drive_id": "baseline-drive",
        **overrides,
    }


def _sharepoint_source_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a SharePoint source baseline that validates."""
    return {
        "client_id": "baseline-id",
        "client_secret": "baseline-secret",  # pragma: allowlist secret
        "tenant_id": "baseline-tenant",
        "document_library_id": "baseline-library",
        **overrides,
    }


def _sharepoint_destination_baseline(**overrides: Any) -> dict[str, Any]:
    """Return a SharePoint destination baseline that validates."""
    return {
        "client_id": "baseline-id",
        "client_secret": "baseline-secret",  # pragma: allowlist secret
        "tenant_id": "baseline-tenant",
        "drive_id": "baseline-drive",
        **overrides,
    }


def _s3_baseline(**overrides: Any) -> dict[str, Any]:
    """Return an S3 baseline, valid for both the source and the destination model."""
    return {
        "access_key": "baseline-access",
        "secret_key": "baseline-secret",  # pragma: allowlist secret
        "bucket": "baseline-bucket",
        **overrides,
    }


def _rejection(*, model: type[BaseModel], baseline: dict[str, Any], mutation: dict[str, Any]) -> ValidationError:
    """Validate the baseline, apply the single mutation, and return the resulting ValidationError."""
    model(**baseline)
    with pytest.raises(ValidationError) as excinfo:
        model(**{**baseline, **mutation})
    return excinfo.value


def _assert_sentinel_absent(*, exc: ValidationError) -> None:
    """Assert the sentinel appears in neither the formatter nor the sanitizer output."""
    rendered = format_pydantic_errors(exc=exc, prefix=KEY)
    assert not any(SENTINEL in message for message in rendered), rendered
    assert SENTINEL not in sanitize_exception(exc=exc, config_key=KEY)


def _assert_loc(*, exc: ValidationError, expected_loc: tuple[str, ...]) -> None:
    """Assert the intended validator rejected the mutated field at ``expected_loc``."""
    assert [error["loc"] for error in exc.errors()] == [expected_loc], exc.errors()


# (scenario id, model, baseline factory, mutation, expected loc)
_SENTINEL_SCENARIOS: list[
    tuple[str, type[BaseModel], Callable[..., dict[str, Any]], dict[str, Any], tuple[str, ...]]
] = [
    # Weaviate environment references (task 3.6): the reference name is hidden behind the field name.
    (
        "weaviate_api_key_braced_reference",
        WeaviateConfig,
        _weaviate_auth_baseline,
        {"api_key": "${" + SENTINEL + "}"},
        MODEL_LEVEL,
    ),
    (
        "weaviate_api_key_bare_reference",
        WeaviateConfig,
        _weaviate_auth_baseline,
        {"api_key": "$" + SENTINEL},
        MODEL_LEVEL,
    ),
    # Weaviate field validator with a fixed message: the rejected collection name must not be echoed.
    (
        "weaviate_collection_name_pattern",
        WeaviateConfig,
        _weaviate_baseline,
        {"collection_name": "bad-" + SENTINEL},
        ("collection_name",),
    ),
    # Dropbox model validator: fixed text naming the missing fields, no value interpolated.
    (
        "dropbox_refresh_token_without_app_credentials",
        DropboxSourceConfig,
        _dropbox_baseline,
        {"access_token": None, "refresh_token": SENTINEL},
        MODEL_LEVEL,
    ),
    # Google Drive ingest model validator: fixed text listing the accepted sources.
    (
        "google_drive_source_both_credential_sources",
        GoogleDriveSourceConfig,
        _gdrive_source_baseline,
        {"credentials_json": SENTINEL},
        MODEL_LEVEL,
    ),
    # Google Drive destination model validator: fixed text naming both fields.
    (
        "google_drive_destination_both_credential_sources",
        GoogleDriveDestinationConfig,
        _gdrive_destination_baseline,
        {"credentials_path": SENTINEL},
        MODEL_LEVEL,
    ),
    # S3 endpoint URL: fixed text, the rejected URL (which can carry credentials) is not echoed.
    (
        "s3_source_endpoint_url_scheme",
        S3SourceConfig,
        _s3_baseline,
        {"endpoint_url": SENTINEL + ".example.com"},
        ("endpoint_url",),
    ),
    (
        "s3_destination_endpoint_url_scheme",
        S3DestinationConfig,
        _s3_baseline,
        {"endpoint_url": SENTINEL + ".example.com"},
        ("endpoint_url",),
    ),
    # Graph API version: the message lists the allowed values, not the rejected one.
    (
        "onedrive_graph_api_version",
        OneDriveSourceConfig,
        _onedrive_baseline,
        {"graph_api_version": SENTINEL},
        ("graph_api_version",),
    ),
    (
        "sharepoint_source_graph_api_version",
        SharePointSourceConfig,
        _sharepoint_source_baseline,
        {"graph_api_version": SENTINEL},
        ("graph_api_version",),
    ),
    (
        "sharepoint_destination_graph_api_version",
        SharePointDestinationConfig,
        _sharepoint_destination_baseline,
        {"graph_api_version": SENTINEL},
        ("graph_api_version",),
    ),
]


@pytest.mark.parametrize(
    ("model", "baseline", "mutation", "expected_loc"),
    [case[1:] for case in _SENTINEL_SCENARIOS],
    ids=[case[0] for case in _SENTINEL_SCENARIOS],
)
def test_validator_rejection_keeps_sentinel_out_of_rendered_output(
    *,
    model: type[BaseModel],
    baseline: Callable[..., dict[str, Any]],
    mutation: dict[str, Any],
    expected_loc: tuple[str, ...],
) -> None:
    """Build a valid baseline, reject one mutated field, and check the sentinel stays out of rendered output."""
    exc = _rejection(model=model, baseline=baseline(), mutation=mutation)

    _assert_loc(exc=exc, expected_loc=expected_loc)
    _assert_sentinel_absent(exc=exc)


def test_filesystem_root_path_is_the_permitted_diagnostic() -> None:
    """The filesystem root path is a permitted reflected value, so it must still appear.

    ``Root path does not exist`` is the only validator message that reflects a local path by design (spec
    operators-api, Permitted filesystem path diagnostic). The scenario asserts the path is present so that a
    future change which removes it fails loudly rather than silently narrowing the diagnostic.
    """
    missing_path = "/nonexistent-" + SENTINEL
    exc = _rejection(
        model=FilesystemSourceConfig,
        baseline={"paths": ["/"]},
        mutation={"paths": [missing_path]},
    )

    _assert_loc(exc=exc, expected_loc=("paths",))
    rendered = format_pydantic_errors(exc=exc, prefix=KEY)
    assert rendered == [f"{KEY}.paths: Value error: Root path does not exist: {missing_path}"]


def test_hap_non_default_model_reflects_model_id_as_an_approved_exception() -> None:
    """The Hugging Face HAP model-level validator reflects ``model_id``; this is a written, approved exception.

    The validator reports ``toxic_labels is required for model '<model_id>'``. The ``model_id`` is a Hugging Face
    Hub identifier chosen by the operator, not a credential, so it is treated as a named exception rather than
    removed. The scenario asserts the identifier IS present, so a change that drops it fails loudly and is
    reviewed against the design, which lists the approved reflected values. Adding another reflected value still
    requires a design change.
    """
    model_id = "org/" + SENTINEL
    exc = _rejection(
        model=HuggingFaceHAPConfig,
        baseline={"model_id": ServiceConstants.DEFAULT_HUGGINGFACE_HAP_MODEL_ID},
        mutation={"model_id": model_id},
    )

    _assert_loc(exc=exc, expected_loc=MODEL_LEVEL)
    rendered = format_pydantic_errors(exc=exc, prefix=KEY)
    assert len(rendered) == 1
    assert f"'{model_id}'" in rendered[0]
    assert f"'{model_id}'" in sanitize_exception(exc=exc, config_key=KEY)
