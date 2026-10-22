"""Unit tests for resolve_aws_account_id when boto3 is not installed."""

import importlib.util
import sys
from types import ModuleType

import pytest

from docpipe.integrations.aws import s3_utils
from docpipe.integrations.aws.s3_utils import resolve_aws_account_id


def _fail_if_sts_is_called(*_args, **_kwargs):
    raise AssertionError("STS must not be called when boto3 is unavailable")


@pytest.fixture
def boto3_unavailable(monkeypatch):
    """Simulate a runtime without boto3 and make any STS client creation fail loudly."""
    monkeypatch.setattr(s3_utils, "_BOTO3_AVAILABLE", False)
    monkeypatch.setattr(s3_utils.boto3, "client", _fail_if_sts_is_called)


class TestResolveAwsAccountIdWithoutBoto3:
    """resolve_aws_account_id must degrade gracefully, or fail clearly in strict mode."""

    def test_returns_none_when_not_strict(self, boto3_unavailable):
        access_key = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret

        assert resolve_aws_account_id(access_key=access_key, region="us-east-1") is None

    def test_strict_raises_with_install_hint(self, boto3_unavailable):
        with pytest.raises(RuntimeError, match=r"boto3 is required .*uv sync --extra aws"):
            resolve_aws_account_id(strict=True)

    def test_endpoint_url_skips_boto3_check_even_when_strict(self, boto3_unavailable):
        """S3-compatible storage never needs STS, so a missing boto3 is irrelevant there."""
        assert resolve_aws_account_id(endpoint_url="http://localhost:9000", strict=True) is None


def _load_s3_utils_without_boto3(monkeypatch) -> ModuleType:
    """Execute a fresh copy of s3_utils while ``import boto3`` raises ImportError."""
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", None)
    spec = importlib.util.spec_from_file_location("_s3_utils_without_boto3", s3_utils.__file__)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestModuleImportWithoutBoto3:
    """The module stays importable when the optional aws extra is not installed."""

    def test_import_marks_boto3_unavailable(self, monkeypatch):
        module = _load_s3_utils_without_boto3(monkeypatch)

        assert module._BOTO3_AVAILABLE is False
        assert not hasattr(module, "boto3")

    def test_freshly_imported_module_resolves_to_none(self, monkeypatch):
        module = _load_s3_utils_without_boto3(monkeypatch)

        assert module.resolve_aws_account_id() is None
        with pytest.raises(RuntimeError, match="boto3 is required"):
            module.resolve_aws_account_id(strict=True)
