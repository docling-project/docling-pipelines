"""Unit tests for S3DestinationAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter import (
    S3DestinationAdapter,
)
from docpipe.core.operators.storage.adapters.outbound.destinations.s3.config import (
    S3DestinationConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREDS = {
    "access_key": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
    "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
    "bucket": "test-bucket",
}


def _make_config(**overrides) -> S3DestinationConfig:
    return S3DestinationConfig(**{**_CREDS, **overrides})


def _mock_s3_client() -> MagicMock:
    """Return a MagicMock that mimics a boto3 S3 client."""
    client = MagicMock()
    # head_object raises 404 ClientError by default (object does not exist)
    from botocore.exceptions import ClientError

    client.head_object.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    return client


# ---------------------------------------------------------------------------
# write_document — success path
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterWriteDocumentSuccess:
    def test_put_object_called_with_correct_args(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"hello s3",
                destination_path="exports/doc1.md",
                overwrite=True,
                config=cfg,
            )

        assert result.success is True
        assert result.write_status == "success"
        assert result.bytes_written == len(b"hello s3")
        assert result.destination_path == "s3://test-bucket/exports/doc1.md"
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "exports/doc1.md"
        assert call_kwargs["Body"] == b"hello s3"

    def test_content_type_injected_for_known_extension(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            adapter.write_document(
                content=b"# content",
                destination_path="out.md",
                overwrite=True,
                config=cfg,
            )

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs.get("ContentType") == "text/markdown"

    def test_expected_bucket_owner_injected_when_account_id_resolved(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value="123456789012"),
        ):
            adapter.write_document(
                content=b"data",
                destination_path="key.txt",
                overwrite=True,
                config=cfg,
            )

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs.get("ExpectedBucketOwner") == "123456789012"

    def test_no_content_type_for_unknown_extension(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            adapter.write_document(
                content=b"data",
                destination_path="doc.xyzunknown123",
                overwrite=True,
                config=cfg,
            )

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert "ContentType" not in call_kwargs


# ---------------------------------------------------------------------------
# write_document — overwrite=False
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterOverwriteFalse:
    def test_skips_when_object_exists(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        # head_object succeeds — object exists
        mock_client.head_object.return_value = {"ContentLength": 100}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"new content",
                destination_path="existing.md",
                overwrite=False,
                config=cfg,
            )

        assert result.success is False
        assert result.write_status == "skipped"
        assert result.error_message == "file exists, overwrite disabled"
        mock_client.put_object.assert_not_called()

    def test_uploads_when_object_absent_and_overwrite_false(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()  # head_object raises 404

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"fresh",
                destination_path="new.txt",
                overwrite=False,
                config=cfg,
            )

        assert result.success is True
        mock_client.put_object.assert_called_once()

    def test_skips_head_object_check_when_overwrite_true(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            adapter.write_document(
                content=b"data",
                destination_path="doc.md",
                overwrite=True,
                config=cfg,
            )

        mock_client.head_object.assert_not_called()


# ---------------------------------------------------------------------------
# write_document — error paths
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterErrorPaths:
    def test_client_error_returns_failed_result(self):
        from botocore.exceptions import ClientError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}}, "PutObject"
        )

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="key.txt",
                overwrite=True,
                config=cfg,
            )

        assert result.success is False
        assert result.write_status == "failed"
        assert "AccessDenied" in result.error_message

    def test_botocore_error_returns_failed_result(self):
        from botocore.exceptions import BotoCoreError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()
        mock_client.put_object.side_effect = BotoCoreError()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="key.txt",
                overwrite=True,
                config=cfg,
            )

        assert result.success is False
        assert result.write_status == "failed"

    def test_missing_config_returns_failed_result(self):
        adapter = S3DestinationAdapter()
        result = adapter.write_document(
            content=b"data",
            destination_path="key.txt",
            overwrite=True,
            config=None,
        )
        assert result.success is False
        assert "S3DestinationConfig is required" in result.error_message

    def test_bytes_written_is_zero_on_failure(self):
        from botocore.exceptions import ClientError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()
        mock_client.put_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "Error"}}, "PutObject")

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.write_document(
                content=b"data",
                destination_path="key.txt",
                overwrite=True,
                config=cfg,
            )

        assert result.bytes_written == 0


# ---------------------------------------------------------------------------
# ensure_directory — no-op
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterEnsureDirectory:
    def test_ensure_directory_is_noop(self):
        adapter = S3DestinationAdapter()
        # Must not raise and must not call any S3 API
        adapter.ensure_directory(path="any/prefix/")

    def test_ensure_directory_does_not_call_s3(self):
        adapter = S3DestinationAdapter()
        with patch("boto3.client") as mock_boto3:
            adapter.ensure_directory(path="some/prefix/")
        mock_boto3.assert_not_called()


# ---------------------------------------------------------------------------
# build_config_from_operator_params
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterBuildConfig:
    def test_accepts_ui_key_prefix(self):
        adapter = S3DestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={"bucket": "my-bucket", "key_prefix": "exports/"},
            credentials={"access_key": "AKID", "secret_key": "SECRET"},  # pragma: allowlist secret
        )
        assert cfg.key_prefix == "exports/"

    def test_builds_config_from_valid_params(self):
        adapter = S3DestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={
                "bucket": "my-bucket",
                "prefix": "exports/",
                "region": "us-east-1",
            },
            credentials={
                "access_key": "AKID",  # pragma: allowlist secret
                "secret_key": "SECRET",  # pragma: allowlist secret
            },
        )
        assert isinstance(cfg, S3DestinationConfig)
        assert cfg.bucket == "my-bucket"
        assert cfg.key_prefix == "exports/"
        assert cfg.region == "us-east-1"

    def test_missing_access_key_raises(self):
        adapter = S3DestinationAdapter()
        with pytest.raises(ValueError, match="access_key"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b"},
                credentials={"secret_key": "s"},  # pragma: allowlist secret
            )

    def test_missing_secret_key_raises(self):
        adapter = S3DestinationAdapter()
        with pytest.raises(ValueError, match="secret_key"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b"},
                credentials={"access_key": "a"},  # pragma: allowlist secret
            )

    def test_missing_bucket_raises(self):
        adapter = S3DestinationAdapter()
        with pytest.raises(ValueError, match="bucket"):
            adapter.build_config_from_operator_params(
                provider_config={},
                credentials={
                    "access_key": "a",  # pragma: allowlist secret
                    "secret_key": "s",  # pragma: allowlist secret
                },
            )

    def test_missing_prefix_raises(self):
        """Omitting 'prefix' must raise — bucket root writes are not permitted."""
        adapter = S3DestinationAdapter()
        with pytest.raises(ValueError, match="Missing required S3 destination path"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b"},
                credentials={
                    "access_key": "a",  # pragma: allowlist secret
                    "secret_key": "s",  # pragma: allowlist secret
                },
            )

    def test_empty_string_prefix_raises(self):
        """An explicit empty string prefix must also raise."""
        adapter = S3DestinationAdapter()
        with pytest.raises(ValueError, match="Missing required S3 destination path"):
            adapter.build_config_from_operator_params(
                provider_config={"bucket": "b", "prefix": ""},
                credentials={
                    "access_key": "a",  # pragma: allowlist secret
                    "secret_key": "s",  # pragma: allowlist secret
                },
            )

    def test_prefix_accepted(self):
        """'prefix' in provider_config is the accepted key for the destination path."""
        adapter = S3DestinationAdapter()
        cfg = adapter.build_config_from_operator_params(
            provider_config={
                "bucket": "my-bucket",
                "prefix": "/vt_workspace/dest_files_01/",
                "region": "us-east-1",
            },
            credentials={
                "access_key": "AKID",  # pragma: allowlist secret
                "secret_key": "SECRET",  # pragma: allowlist secret
            },
        )
        # normalise_key_prefix strips the leading slash
        assert cfg.key_prefix == "vt_workspace/dest_files_01/"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterRegistration:
    def test_dest_name_is_s3(self):
        assert S3DestinationAdapter.DEST_NAME == "s3"

    def test_is_registered_in_factory(self):
        # Importing the adapter module triggers @register_destination_adapter
        import docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter  # noqa: F401
        from docpipe.core.operators.storage.adapters.outbound.destinations.factories.destination_factory import (
            DestinationAdapterFactory,
        )

        assert DestinationAdapterFactory.is_registered("s3")

    def test_get_config_schema_returns_s3_destination_config(self):
        adapter = S3DestinationAdapter()
        assert adapter.get_config_schema() is S3DestinationConfig


class TestS3DestinationAdapterResolveDestinationPath:
    def test_prepends_key_prefix(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="exports/docs/")
        result = adapter.resolve_destination_path(relative_path="2026/doc.md", config=cfg)
        assert result == "exports/docs/2026/doc.md"

    def test_empty_prefix_returns_relative_path_unchanged(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="")
        result = adapter.resolve_destination_path(relative_path="doc.md", config=cfg)
        assert result == "doc.md"


# ---------------------------------------------------------------------------
# validate_destination
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterValidateDestination:
    def test_returns_none_when_bucket_accessible(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is None
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_returns_none_when_config_is_none(self):
        adapter = S3DestinationAdapter()
        result = adapter.validate_destination(config=None)
        assert result is None

    def test_returns_failed_result_on_client_error(self):
        from botocore.exceptions import ClientError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "The specified bucket does not exist"}},
            "HeadBucket",
        )

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is not None
        assert result.success is False
        assert "test-bucket" in result.error_message
        assert "NoSuchBucket" in result.error_message

    def test_returns_failed_result_on_access_denied(self):
        from botocore.exceptions import ClientError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "403", "Message": "Access Denied"}},
            "HeadBucket",
        )

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is not None
        assert result.success is False
        assert "403" in result.error_message

    def test_injects_expected_bucket_owner_when_account_id_resolved(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value="123456789012"),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is None
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket", ExpectedBucketOwner="123456789012")

    def test_returns_failed_result_on_botocore_error(self):
        from botocore.exceptions import BotoCoreError

        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = BotoCoreError()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is not None
        assert result.success is False
        assert "test-bucket" in result.error_message


# ---------------------------------------------------------------------------
# validate_destination — create_dirs=False prefix existence check
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterValidateDestinationCreateDirs:
    def test_create_dirs_true_skips_prefix_check(self):
        """Default create_dirs=True: list_objects_v2 is never called regardless of prefix."""
        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="vt_workspace/dest/", create_dirs=True)
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is None
        mock_client.list_objects_v2.assert_not_called()

    def test_create_dirs_false_prefix_exists_returns_none(self):
        """create_dirs=False and prefix has objects: validation passes."""
        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="vt_workspace/dest/", create_dirs=False)
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        mock_client.list_objects_v2.return_value = {"KeyCount": 2}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is None
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="test-bucket", Prefix="vt_workspace/dest/", MaxKeys=1
        )

    def test_create_dirs_false_prefix_missing_returns_failed_result(self):
        """create_dirs=False and prefix has no objects: validation fails with clear message."""
        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="vt_workspace/dest/", create_dirs=False)
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        mock_client.list_objects_v2.return_value = {"KeyCount": 0}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is not None
        assert result.success is False
        assert "destination prefix path does not exist" in result.error_message
        assert "create_dirs is disabled" in result.error_message
        assert "vt_workspace/dest/" in result.error_message

    def test_create_dirs_false_list_objects_client_error_returns_failed_result(self):
        """create_dirs=False and list_objects_v2 raises ClientError: validation fails gracefully."""
        from botocore.exceptions import ClientError

        adapter = S3DestinationAdapter()
        cfg = _make_config(key_prefix="vt_workspace/dest/", create_dirs=False)
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        mock_client.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "ListObjectsV2"
        )

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is not None
        assert result.success is False
        assert "S3 prefix check failed" in result.error_message
        assert "AccessDenied" in result.error_message

    def test_create_dirs_false_empty_key_prefix_skips_prefix_check(self):
        """create_dirs=False but key_prefix is empty string: prefix check is skipped (no-op)."""
        adapter = S3DestinationAdapter()
        # key_prefix="" is not a meaningful path to check — skip silently
        cfg = _make_config(create_dirs=False)
        # Manually set key_prefix to empty to bypass the normaliser
        object.__setattr__(cfg, "key_prefix", "")
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            result = adapter.validate_destination(config=cfg)

        assert result is None
        mock_client.list_objects_v2.assert_not_called()


# ---------------------------------------------------------------------------
# Caching — _create_s3_client and _get_aws_account_id called once per batch
# ---------------------------------------------------------------------------


class TestS3DestinationAdapterCaching:
    def test_s3_client_created_once_across_multiple_writes(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch("docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter.boto3") as mock_boto3,
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            mock_boto3.client.return_value = mock_client

            for key in ("doc1.md", "doc2.md", "doc3.md"):
                adapter.write_document(content=b"x", destination_path=key, config=cfg)

        mock_boto3.client.assert_called_once()

    def test_account_id_resolved_once_across_multiple_writes(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = _mock_s3_client()

        with (
            patch.object(adapter, "_create_s3_client", return_value=mock_client),
            patch(
                "docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter.resolve_aws_account_id",
                return_value="123456789012",
            ) as mock_resolve,
        ):
            for key in ("doc1.md", "doc2.md", "doc3.md"):
                adapter.write_document(content=b"x", destination_path=key, config=cfg)

        mock_resolve.assert_called_once()

    def test_different_configs_get_separate_clients(self):
        adapter = S3DestinationAdapter()
        cfg_a = _make_config(region="us-east-1")
        cfg_b = _make_config(region="eu-west-1")
        mock_client = MagicMock()

        with (
            patch("docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter.boto3") as mock_boto3,
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            mock_boto3.client.return_value = mock_client

            adapter.write_document(content=b"x", destination_path="doc1.md", config=cfg_a)
            adapter.write_document(content=b"x", destination_path="doc2.md", config=cfg_b)

        assert mock_boto3.client.call_count == 2

    def test_client_reused_across_validate_and_write(self):
        adapter = S3DestinationAdapter()
        cfg = _make_config()
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}

        with (
            patch("docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter.boto3") as mock_boto3,
            patch.object(adapter, "_get_aws_account_id", return_value=None),
        ):
            mock_boto3.client.return_value = mock_client

            adapter.validate_destination(config=cfg)
            adapter.write_document(content=b"x", destination_path="doc1.md", config=cfg)

        mock_boto3.client.assert_called_once()
