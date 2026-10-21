"""Unit tests for S3Adapter.

S3 is replaced by an in-memory fake client (paginated listing and download_file that writes the
object to disk), so the adapter downloads real files into a temporary cache and the real
FilesystemAdapter discovers, loads and validates the operators from there.

These tests do not remove or re-import modules via sys.modules: re-importing the adapter pulls in
numpy/torch a second time, which fails ("cannot load module more than once per process").
"""

from pathlib import Path
from typing import Any

import pytest

from docpipe.core.orchestration.operator_loader.adapters import s3_adapter
from docpipe.core.orchestration.operator_loader.adapters.s3_adapter import S3Adapter

_OPERATOR_SOURCE = '''
import pyarrow as pa
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class {class_name}(AbstractOperator):
    """Operator published to the S3 bucket."""

    short_name: str = "{short_name}"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = "custom"

    def transform(self, table: pa.Table, file_name: str | None = None):
        return [table], {{}}
'''


def _operator(class_name: str, short_name: str) -> bytes:
    return _OPERATOR_SOURCE.format(class_name=class_name, short_name=short_name).encode()


class FakePaginator:
    def __init__(self, client: "FakeS3Client") -> None:
        self._client = client

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._client.list_calls.append(kwargs)
        if self._client.list_error:
            raise self._client.list_error
        keys = sorted(k for k in self._client.objects if k.startswith(kwargs["Prefix"]))
        # Two pages, so the adapter has to follow pagination
        middle = len(keys) // 2
        return [
            {"Contents": [{"Key": k} for k in keys[:middle]]},
            {"Contents": [{"Key": k} for k in keys[middle:]]},
            {},
        ]


class FakeS3Client:
    """In-memory bucket with the two calls the adapter uses."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.list_calls: list[dict[str, Any]] = []
        self.download_calls: list[tuple[str, str, Any]] = []
        self.list_error: Exception | None = None

    def get_paginator(self, operation: str) -> FakePaginator:
        assert operation == "list_objects_v2"
        return FakePaginator(self)

    def download_file(self, bucket: str, key: str, filename: str, ExtraArgs: Any = None) -> None:  # noqa: N803
        self.download_calls.append((bucket, key, ExtraArgs))
        Path(filename).write_bytes(self.objects[key])


@pytest.fixture
def bucket() -> FakeS3Client:
    return FakeS3Client(
        {
            "operators/cleaner.py": _operator("CleanerOp", "cleaner_op"),
            "operators/nested/tagger.py": _operator("TaggerOp", "tagger_op"),
            "operators/_private_helper.py": b"HELPER = True\n",
            "operators/README.md": b"# not an operator\n",
            "other/ignored.py": _operator("IgnoredOp", "ignored_op"),
        }
    )


@pytest.fixture
def fake_aws(monkeypatch, bucket: FakeS3Client):
    """Route boto3.client("s3") to the fake bucket and pin the resolved account ID."""
    monkeypatch.setattr(s3_adapter.boto3, "client", lambda service: bucket)
    monkeypatch.setattr(s3_adapter, "resolve_aws_account_id", lambda: "123456789012")
    return bucket


class TestDownloadAndLoad:
    """Construction downloads operator files; the filesystem adapter then works on the cache."""

    def test_downloads_only_operator_files_below_prefix(self, fake_aws: FakeS3Client, tmp_path: Path) -> None:
        S3Adapter("s3://ops-bucket/operators", cache_dir=str(tmp_path))

        downloaded = sorted(key for _, key, _ in fake_aws.download_calls)
        assert downloaded == ["operators/cleaner.py", "operators/nested/tagger.py"]
        assert (tmp_path / "operators" / "cleaner.py").is_file()
        assert (tmp_path / "operators" / "nested" / "tagger.py").is_file()
        assert fake_aws.list_calls == [
            {"Bucket": "ops-bucket", "Prefix": "operators", "ExpectedBucketOwner": "123456789012"}
        ]
        assert all(extra == {"ExpectedBucketOwner": "123456789012"} for _, _, extra in fake_aws.download_calls)

    def test_lists_loads_and_validates_downloaded_operators(self, fake_aws: FakeS3Client, tmp_path: Path) -> None:
        adapter = S3Adapter("s3://ops-bucket/operators", cache_dir=str(tmp_path))

        operators = sorted(adapter.list_operators(), key=lambda op: op.short_name)

        assert [op.short_name for op in operators] == ["cleaner_op", "tagger_op"]
        assert {op.source_location for op in operators} == {"s3:s3://ops-bucket/operators"}

        module = adapter.load_operator(operator_info=operators[0])
        assert hasattr(module, "CleanerOp")
        assert adapter.validate_operator(module=module, operator_info=operators[0]).valid

    def test_default_cache_is_per_bucket_under_home(self, fake_aws: FakeS3Client, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        adapter = S3Adapter("s3://ops-bucket/operators")

        assert adapter.cache_dir == tmp_path / ".docpipe" / "custom_operators_cache" / "ops-bucket"
        assert (adapter.cache_dir / "operators" / "cleaner.py").is_file()

    def test_clear_cache_removes_downloaded_files(self, fake_aws: FakeS3Client, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        adapter = S3Adapter("s3://ops-bucket/operators", cache_dir=str(cache))

        adapter.clear_cache()

        assert not cache.exists()

    def test_clear_cache_when_cache_is_already_gone(self, fake_aws: FakeS3Client, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        adapter = S3Adapter("s3://ops-bucket/operators", cache_dir=str(cache))
        adapter.clear_cache()

        adapter.clear_cache()

        assert not cache.exists()


class TestFailures:
    """Configuration and S3 errors."""

    @pytest.mark.parametrize(
        ("uri", "message"),
        [("https://ops-bucket/operators", "Expected 's3://'"), ("s3:///operators", "Missing bucket name")],
    )
    def test_invalid_uri(self, fake_aws: FakeS3Client, tmp_path: Path, uri: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            S3Adapter(uri, cache_dir=str(tmp_path))

    def test_listing_error_is_reported(self, fake_aws: FakeS3Client, tmp_path: Path) -> None:
        fake_aws.list_error = PermissionError("AccessDenied")

        with pytest.raises(Exception, match="Failed to download operators from S3: AccessDenied"):
            S3Adapter("s3://ops-bucket/operators", cache_dir=str(tmp_path))

    def test_missing_boto3_is_reported(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(s3_adapter, "_BOTO3_AVAILABLE", False)

        with pytest.raises(ImportError, match="boto3 is required for S3 adapter"):
            S3Adapter("s3://ops-bucket/operators", cache_dir=str(tmp_path))


def test_adapter_identity() -> None:
    assert (S3Adapter.ADAPTER_NAME, S3Adapter.ADAPTER_DISPLAY_NAME) == ("s3", "Amazon S3")
