# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Real-client construction with a revealed secret (add-secret-management, task B.5).

Operators now hand adapters ``SecretValue`` objects. Each adapter must reveal them at the point where it builds its
client. These tests build the *real* client library object (boto3, MSAL, Box, Google, Dropbox, httpx, ``opensearchpy``,
``pymilvus``) from ``SecretValue`` inputs through the adapter's own entry point, and assert that the library received the
plain secret. A client that is handed a ``SecretValue`` would break at that point (a ``SecretValue`` is not a ``str``), so a
missed reveal fails here and not in production.

Only the network edge is stubbed (MSAL's authority discovery, the OpenSearch and Milvus connect calls). The client
classes themselves are real.
"""

import json
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from docpipe.integrations.secrets.registry import get_registry
from docpipe.integrations.secrets.secret_value import SecretValue

CANARY_ACCESS = "AKIACANARY0000000001"  # pragma: allowlist secret
CANARY_SECRET = "canary-secret-value-0001"  # pragma: allowlist secret
CANARY_TOKEN = "canary-token-value-0001"  # pragma: allowlist secret
CANARY_PASSWORD = "canary-password-0001"  # pragma: allowlist secret


def secret(value: Any) -> SecretValue:
    return SecretValue(value=value)


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    get_registry().clear_all()
    yield
    get_registry().clear_all()


@pytest.fixture(scope="module")
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture(scope="module")
def encrypted_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"pw")
    ).decode()


class TestBoto3:
    def test_s3_source_client_receives_the_plain_credentials(self):
        from docpipe.core.operators.ingest.adapters.outbound.sources.s3.adapter import S3SourceAdapter

        adapter = S3SourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "access_key": secret(CANARY_ACCESS),
                "secret_key": secret(CANARY_SECRET),
                "bucket": secret("bucket"),
                "endpoint_url": secret("http://localhost:9000"),
                "region": secret("us-east-1"),
            }
        )
        client = adapter._create_s3_client(config)

        credentials = client._request_signer._credentials
        assert credentials.access_key == CANARY_ACCESS
        assert credentials.secret_key == CANARY_SECRET
        assert client.meta.endpoint_url == "http://localhost:9000"

    def test_s3_destination_client_receives_the_plain_credentials(self):
        from docpipe.core.operators.storage.adapters.outbound.destinations.s3.adapter import S3DestinationAdapter

        adapter = S3DestinationAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "bucket": secret("bucket"),
                "key_prefix": "out/",
                "endpoint_url": secret("http://localhost:9000"),
                "region": secret("us-east-1"),
            },
            credentials={"access_key": secret(CANARY_ACCESS), "secret_key": secret(CANARY_SECRET)},
        )
        client = adapter._create_s3_client(config)

        assert client._request_signer._credentials.secret_key == CANARY_SECRET


class TestDropbox:
    def test_access_token_reaches_the_client_as_a_string(self):
        from docpipe.core.operators.ingest.adapters.outbound.sources.dropbox.adapter import DropboxSourceAdapter

        adapter = DropboxSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"access_token": secret(CANARY_TOKEN), "folder_path": "/x"}
        )
        client = adapter._get_dropbox_client(config=config)

        assert client._oauth2_access_token == CANARY_TOKEN


class TestMsal:
    @pytest.fixture
    def offline_authority(self) -> Iterator[None]:
        """Stub MSAL's network authority discovery; the application class stays real."""
        import msal.authority

        document = {
            "authorization_endpoint": "https://login.microsoftonline.com/t/oauth2/v2.0/authorize",
            "token_endpoint": "https://login.microsoftonline.com/t/oauth2/v2.0/token",
            "issuer": "https://login.microsoftonline.com/t/v2.0",
        }
        with mock.patch.object(msal.authority, "tenant_discovery", return_value=document):
            yield

    @pytest.mark.parametrize(
        ("module", "adapter_class", "drive_key"),
        [
            ("sharepoint", "SharePointSourceAdapter", "document_library_id"),
            ("onedrive", "OneDriveSourceAdapter", "drive_id"),
        ],
    )
    def test_confidential_client_receives_the_plain_secret(self, offline_authority, module, adapter_class, drive_key):
        import importlib

        import msal

        adapter_module = importlib.import_module(
            f"docpipe.core.operators.ingest.adapters.outbound.sources.{module}.adapter"
        )
        adapter = getattr(adapter_module, adapter_class)()
        config = adapter.build_config_from_operator_params(
            provider_config={
                drive_key: secret("d"),
                "client_id": secret("client-id"),
                "client_secret": secret(CANARY_SECRET),
                "tenant_id": secret("t"),
            }
        )
        loader = adapter._get_loader(
            drive_id=getattr(config, drive_key),
            client_id=config.client_id,
            client_secret=config.client_secret,
            tenant_id=config.tenant_id,
        )
        assert isinstance(loader.client_secret, str)

        with mock.patch.object(msal.ConfidentialClientApplication, "acquire_token_for_client") as acquire:
            acquire.return_value = {"access_token": "token"}
            captured: dict[str, Any] = {}
            real_init = msal.ConfidentialClientApplication.__init__

            def spy(self: Any, *args: Any, **kwargs: Any) -> None:
                real_init(self, *args, **kwargs)
                captured["client_credential"] = self.client_credential

            with mock.patch.object(msal.ConfidentialClientApplication, "__init__", spy):
                loader._get_token()

        assert captured["client_credential"] == CANARY_SECRET

    def test_acl_adapter_receives_the_plain_secret(self, offline_authority):
        import msal

        from docpipe.core.operators.acl.adapters.outbound.sharepoint_adapter import SharePointACLAdapter

        adapter = SharePointACLAdapter()
        config = adapter.build_config_from_operator_params(
            connection_params={"drive_id": "d"},
            credentials={"client_id": "cid", "client_secret": secret(CANARY_SECRET), "tenant_id": secret("t")},
            provider_metadata={},
        )
        assert config.client_secret == CANARY_SECRET

        with mock.patch.object(msal.ConfidentialClientApplication, "acquire_token_for_client") as acquire:
            acquire.return_value = {"access_token": "token"}
            seen: dict[str, Any] = {}
            real_init = msal.ConfidentialClientApplication.__init__

            def spy(self: Any, *args: Any, **kwargs: Any) -> None:
                real_init(self, *args, **kwargs)
                seen["client_credential"] = self.client_credential

            with mock.patch.object(msal.ConfidentialClientApplication, "__init__", spy):
                import asyncio

                asyncio.run(adapter._get_token(config=config))

        assert seen["client_credential"] == CANARY_SECRET


class TestBox:
    def test_inline_jwt_config_builds_a_real_client(self, encrypted_private_key_pem):
        from box_sdk_gen import BoxClient

        from docpipe.core.operators.ingest.adapters.outbound.sources.box.adapter import BoxSourceAdapter

        jwt_config = {
            "boxAppSettings": {
                "clientID": "cid",
                "clientSecret": CANARY_SECRET,
                "appAuth": {"publicKeyID": "kid", "privateKey": encrypted_private_key_pem, "passphrase": "pw"},
            },
            "enterpriseID": "123",
        }
        adapter = BoxSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"credentials_json": secret(jwt_config), "folder_id": "0"}
        )
        assert isinstance(config.credentials_json, dict)

        client = adapter._get_box_client(config=config)

        assert isinstance(client, BoxClient)

    def test_inline_jwt_config_given_as_json_text_builds_a_real_client(self, encrypted_private_key_pem):
        from box_sdk_gen import BoxClient

        from docpipe.core.operators.ingest.adapters.outbound.sources.box.adapter import BoxSourceAdapter

        jwt_config = {
            "boxAppSettings": {
                "clientID": "cid",
                "clientSecret": CANARY_SECRET,
                "appAuth": {"publicKeyID": "kid", "privateKey": encrypted_private_key_pem, "passphrase": "pw"},
            },
            "enterpriseID": "123",
        }
        adapter = BoxSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"credentials_json": secret(json.dumps(jwt_config)), "folder_id": "0"}
        )

        assert isinstance(adapter._get_box_client(config=config), BoxClient)


class TestGoogleDrive:
    @staticmethod
    def _service_account(private_key_pem: str) -> dict[str, str]:
        return {
            "type": "service_account",
            "client_email": "sa@project.iam.gserviceaccount.com",
            "private_key": private_key_pem,
            "token_uri": "https://oauth2.googleapis.com/token",
            "project_id": "project",
        }

    def test_inline_service_account_json_is_forwarded_and_builds_credentials(self, private_key_pem):
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
            GoogleDriveSourceAdapter,
        )

        adapter = GoogleDriveSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "f", "service_account_json": secret(self._service_account(private_key_pem))}
        )

        assert isinstance(config.service_account_json, dict)
        assert adapter._get_credentials(config).service_account_email == "sa@project.iam.gserviceaccount.com"

    def test_inline_service_account_json_text_is_forwarded(self, private_key_pem):
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
            GoogleDriveSourceAdapter,
        )

        adapter = GoogleDriveSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={
                "folder_id": "f",
                "service_account_json": secret(json.dumps(self._service_account(private_key_pem))),
            }
        )

        assert adapter._get_credentials(config).service_account_email == "sa@project.iam.gserviceaccount.com"

    def test_inline_oauth_client_json_is_forwarded(self):
        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
            GoogleDriveSourceAdapter,
        )

        oauth = {
            "installed": {
                "client_id": "id",
                "client_secret": CANARY_SECRET,
                "auth_uri": "https://a",
                "token_uri": "https://t",
            }
        }
        config = GoogleDriveSourceAdapter().build_config_from_operator_params(
            provider_config={"folder_id": "f", "credentials_json": secret(oauth)}
        )

        assert config.credentials_json == oauth

    def test_drive_service_is_built_from_the_credentials(self, private_key_pem):
        from googleapiclient.discovery import build

        from docpipe.core.operators.ingest.adapters.outbound.sources.google_drive.adapter import (
            GoogleDriveSourceAdapter,
        )

        adapter = GoogleDriveSourceAdapter()
        config = adapter.build_config_from_operator_params(
            provider_config={"folder_id": "f", "service_account_json": secret(self._service_account(private_key_pem))}
        )

        service = build("drive", "v3", credentials=adapter._get_credentials(config))

        assert hasattr(service, "files")


class TestHttp:
    def test_docling_serve_client_receives_the_plain_api_key(self):
        from docpipe.core.operators.extract.adapters.outbound.factories.text_extraction_adapter_factory import (
            TextExtractionAdapterFactory,
        )
        from docpipe.core.operators.extract.adapters.outbound.text_extraction.docling_serve_adapter import (
            DoclingServeAdapter,
        )
        from docpipe.core.operators.extract.domain.models import TextExtractionMode

        text_extraction_config = {
            "provider": "docling_serve",
            "provider_config": {"base_url": secret("http://localhost:5001"), "api_key": secret(CANARY_TOKEN)},
        }
        adapter = TextExtractionAdapterFactory.create_adapter(
            mode=TextExtractionMode.DOCLING_SERVE, text_extraction_config=text_extraction_config, global_config={}
        )

        assert isinstance(adapter, DoclingServeAdapter)
        assert adapter.api_key == CANARY_TOKEN
        assert adapter.base_url == "http://localhost:5001"

    def test_chunker_remote_client_receives_plain_values(self):
        from docpipe.core.operators.functional.chunker import ChunkerOperator

        operator = ChunkerOperator.__new__(ChunkerOperator)
        operator.provider_config = {"api_base": secret("http://localhost:5001"), "api_key": secret(CANARY_TOKEN)}
        operator._remote_chunking_client = None
        operator.common_log_arguments = {}

        client = operator._get_docling_serve_client()

        assert client.base_url == "http://localhost:5001"


class TestOpenSearch:
    def test_client_receives_plain_connection_values(self):
        from docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter import OpenSearchAdapter

        with (
            mock.patch(
                "docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch"
            ) as client_class,
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter.OpenSearchIndexManager"),
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter.OpenSearchBatchProcessor"),
        ):
            OpenSearchAdapter(
                index_name="idx",
                host=secret("search.internal"),
                port=9200,
                username=secret("svc"),
                password=secret(CANARY_PASSWORD),
                use_ssl=False,
                verify_certs=False,
            )

        kwargs = client_class.call_args.kwargs
        assert kwargs["hosts"] == [{"host": "search.internal", "port": 9200}]
        assert kwargs["http_auth"] == ("svc", CANARY_PASSWORD)
        assert all(type(part) is str for part in kwargs["http_auth"])

    def test_basic_auth_header_value_is_registered_for_scrubbing(self):
        import base64

        from docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter import OpenSearchAdapter

        with (
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.client.OpenSearch"),
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter.OpenSearchIndexManager"),
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.opensearch.adapter.OpenSearchBatchProcessor"),
        ):
            OpenSearchAdapter(
                index_name="idx",
                host="search.internal",
                username=secret("svc"),
                password=secret(CANARY_PASSWORD),
                use_ssl=False,
                verify_certs=False,
            )

        header = base64.b64encode(f"svc:{CANARY_PASSWORD}".encode()).decode()
        assert get_registry().scrub_text(text=f"Authorization: Basic {header}") == "Authorization: Basic ***"


class TestMilvus:
    def test_client_receives_a_plain_token_and_registers_the_derived_one(self):
        from docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter import MilvusAdapter

        with (
            mock.patch(
                "docpipe.core.operators.vectordb.adapters.outbound.milvus.client.PyMilvusClient"
            ) as client_class,
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter.MilvusIndexManager"),
            mock.patch("docpipe.core.operators.vectordb.adapters.outbound.milvus.adapter.MilvusBatchProcessor"),
        ):
            MilvusAdapter(
                collection_name="c",
                host=secret("milvus.internal"),
                port=19530,
                username=secret("svc"),
                password=secret(CANARY_PASSWORD),
                auth_type="standalone",
            )

        kwargs = client_class.call_args.kwargs
        assert kwargs["uri"] == "http://milvus.internal:19530"
        assert kwargs["token"] == f"svc:{CANARY_PASSWORD}"
        assert type(kwargs["token"]) is str
        assert get_registry().scrub_text(text=f"token={kwargs['token']}") == "token=***"
