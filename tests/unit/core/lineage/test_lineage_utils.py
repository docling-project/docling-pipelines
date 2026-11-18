"""Unit tests for LineageUtils."""

import uuid
from typing import Any

import pytest

from docpipe.core.lineage.utils import LineageUtils


class TestLineageUtils:
    """Consolidated test suite for LineageUtils static helpers."""

    def test_now_returns_iso_format(self) -> None:
        now_str = LineageUtils.now()
        assert isinstance(now_str, str)
        assert "T" in now_str
        assert "+" in now_str or "Z" in now_str

    def test_is_valid_uuid(self) -> None:
        valid_id = str(uuid.uuid4())
        assert LineageUtils.is_valid_uuid(valid_id) is True
        assert LineageUtils.is_valid_uuid("not-a-uuid") is False
        assert LineageUtils.is_valid_uuid("") is False

    @pytest.mark.parametrize(
        ("snake", "expected"),
        [
            ("processed_docs", "processedDocs"),
            ("docs_before_filter", "docsBeforeFilter"),
            ("chunks_indexed_successfully", "chunksIndexedSuccessfully"),
            ("node_status", "nodeStatus"),
            ("total_chunks_to_index", "totalChunksToIndex"),
            ("nrows", "nrows"),
            ("processedDocs", "processedDocs"),
        ],
    )
    def test_to_camel_case(self, snake: str, expected: str) -> None:
        assert LineageUtils.to_camel_case(snake) == expected

    def test_strip_credentials(self) -> None:
        data = {
            "api_key": "secret123",  # pragma: allowlist secret
            "password": "pass",  # pragma: allowlist secret
            "node": {
                "name": "op1",
                "token": "tok456",  # pragma: allowlist secret
                "safe_config": {"batch_size": 10},
            },
        }
        stripped = LineageUtils.strip_credentials(data)
        assert "api_key" not in stripped
        assert "password" not in stripped
        assert stripped["node"]["name"] == "op1"
        assert "token" not in stripped["node"]
        assert stripped["node"]["safe_config"]["batch_size"] == 10
        assert LineageUtils.strip_credentials("string") == "string"
        list_data = [{"api_key": "secret", "value": 1}, {"safe": 2}]  # pragma: allowlist secret
        stripped_list = LineageUtils.strip_credentials(list_data)
        assert stripped_list == [{"value": 1}, {"safe": 2}]

    def test_node_run_id(self) -> None:
        job_run_id = str(uuid.uuid4())
        node_id = "chunker_node"
        id1 = LineageUtils.node_run_id(job_run_id=job_run_id, node_id=node_id)
        id2 = LineageUtils.node_run_id(job_run_id=job_run_id, node_id=node_id)
        assert id1 == id2
        assert LineageUtils.is_valid_uuid(id1) is True
        # non-UUID job_run_id fallback
        id3 = LineageUtils.node_run_id(job_run_id="custom-run-1", node_id="node-1")
        assert LineageUtils.is_valid_uuid(id3) is True

    def test_resolve_flow_id(self) -> None:
        res = LineageUtils.resolve_flow_id(flow_id="my-flow-id", flow_def={"a": 1})
        assert res == "my-flow-id"
        # empty flow_id falls back to sha256
        res1 = LineageUtils.resolve_flow_id(flow_id="", flow_def={"flow_name": "test"})
        res2 = LineageUtils.resolve_flow_id(flow_id="", flow_def={"flow_name": "test"})
        assert res1 == res2
        assert len(res1) == 64

    def test_derive_dataset_info_from_ingest(self) -> None:
        fs_op = {
            "config": {
                "provider": "filesystem",
                "connection_params": {"paths": ["./tests/fixtures/customer_support_docs/"]},
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=fs_op) == (
            "file",
            "./tests/fixtures/customer_support_docs",
        )

        s3_op = {
            "config": {
                "provider": "s3",
                "provider_config": {"bucket": "my-bucket", "prefix": "data/docs"},
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=s3_op) == (
            "s3://my-bucket",
            "data/docs",
        )

        empty_op: dict[str, Any] = {}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=empty_op) == (
            "unknown://source",
            "source",
        )

        # Single path in provider_config & operator_config
        single_path_op = {
            "config": {
                "provider": "local",
                "provider_config": {"path": "/var/data"},
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=single_path_op) == (
            "file",
            "/var/data",
        )

        op_cfg_path_op = {
            "config": {
                "provider": "file",
                "path": "/opt/data",
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=op_cfg_path_op) == (
            "file",
            "/opt/data",
        )

        fs_no_paths = {"config": {"provider": "filesystem"}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=fs_no_paths) == (
            "file",
            "source",
        )

        # S3 defaults
        s3_default_op = {"config": {"provider": "s3"}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=s3_default_op) == (
            "s3://unknown",
            "/",
        )

        # Box provider: BoxSourceConfig uses folder_id
        box_op = {"config": {"provider": "box", "provider_config": {"folder_id": "123456789"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=box_op) == (
            "box://app.box.com:443/default",
            "123456789",
        )

        box_default_op = {"config": {"provider": "box"}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=box_default_op) == (
            "box://app.box.com:443/default",
            "0",
        )

        # SharePoint provider: SharePointSourceConfig uses document_library_id + folder_path
        sp_op = {
            "config": {
                "provider": "sharepoint",
                "provider_config": {
                    "document_library_id": "b!lib1",
                    "folder_path": "/Shared Documents/Reports/",
                },
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=sp_op) == (
            "mssharepoint://graph.microsoft.com:443/b!lib1",
            "/Shared Documents/Reports",
        )

        sp_root_op = {"config": {"provider": "sharepoint", "provider_config": {"document_library_id": "b!lib1"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=sp_root_op) == (
            "mssharepoint://graph.microsoft.com:443/b!lib1",
            "/",
        )

        # Google Drive provider: folder_id / folder_path / drive_id
        gdrive_op = {"config": {"provider": "google_drive", "provider_config": {"folder_id": "fold_1"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=gdrive_op) == (
            "googledrive://drive.google.com",
            "fold_1",
        )

        gdrive_shared_op = {
            "config": {
                "provider": "google_drive",
                "provider_config": {"drive_id": "shared_9", "folder_path": "/Reports"},
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=gdrive_shared_op) == (
            "googledrive://drive.google.com/shared_9",
            "/Reports",
        )

        gdrive_default_op = {"config": {"provider": "google_drive"}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=gdrive_default_op) == (
            "googledrive://drive.google.com",
            "root",
        )

        # Custom provider with paths
        custom_op = {
            "config": {
                "provider": "azure_blob",
                "connection_params": {"paths": ["container/data"]},
            }
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=custom_op) == (
            "azure_blob://source",
            "container/data",
        )

    def test_derive_dataset_info_from_sink(self) -> None:
        opensearch_op = {
            "operator": "vectordb",
            "config": {
                "provider": "opensearch",
                "provider_config": {"host": "localhost", "port": 9200, "index_name": "kb_index"},
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=opensearch_op) == (
            "opensearch://localhost:9200",
            "kb_index",
        )

        milvus_op = {
            "operator": "vectordb",
            "config": {
                "provider": "milvus",
                "provider_config": {
                    "host": "milvus.local",
                    "port": 19530,
                    "database": "kb_db",
                    "collection_name": "chunks",
                },
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=milvus_op) == (
            "milvus://milvus.local:19530",
            "kb_db.chunks",
        )

        storage_s3_op = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "s3",
                    "provider_config": {"bucket": "out-bucket", "prefix": "processed"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_s3_op) == (
            "s3://out-bucket",
            "processed",
        )

        storage_fs_op = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "filesystem",
                    "provider_config": {"root_path": "/tmp/out"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_fs_op) == (
            "file",
            "/tmp/out",
        )

        docset_op = {
            "operator": "document_set",
            "config": {"document_set_name": "my_dataset"},
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=docset_op) == (
            "docpipe://document_set",
            "my_dataset",
        )

        chunker_op = {
            "operator": "chunker",
            "config": {},
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=chunker_op) is None

        # Milvus with default database & collection
        milvus_def_op = {
            "operator": "vectordb",
            "config": {"provider": "milvus"},
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=milvus_def_op) == (
            "milvus://localhost:19530",
            "default.default_collection",
        )

        # Opensearch with config root fallback
        opensearch_fallback = {
            "operator": "vector_db",
            "config": {"provider": "opensearch", "index_name": "direct_kb"},
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=opensearch_fallback) == (
            "opensearch://localhost:9200",
            "direct_kb",
        )

        # Generic vector provider (e.g. Qdrant) with port and without port
        qdrant_op = {
            "operator": "vectordb",
            "config": {
                "provider": "qdrant",
                "provider_config": {"host": "qdrant.internal", "port": 6333, "collection_name": "docs"},
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=qdrant_op) == (
            "qdrant://qdrant.internal:6333",
            "docs",
        )

        qdrant_no_port = {
            "operator": "VectorDBOperator",
            "config": {
                "provider": "qdrant",
                "provider_config": {"host": "qdrant.internal", "index_name": "idx"},
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=qdrant_no_port) == (
            "qdrant://qdrant.internal",
            "idx",
        )

        # Storage sinks: Box, SharePoint, Google Drive, generic (valid destination adapter configs)
        storage_box_op = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "box",
                    "provider_config": {"folder_id": "987654321", "create_dirs": True},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_box_op) == (
            "box://app.box.com:443/default",
            "987654321",
        )

        storage_sp_op = {
            "operator": "StorageOutputOperator",
            "config": {
                "destination_config": {
                    "provider": "sharepoint",
                    "provider_config": {"drive_id": "b!abc123", "folder_path": "/Processed Documents"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_sp_op) == (
            "mssharepoint://graph.microsoft.com:443/b!abc123",
            "/Processed Documents",
        )

        storage_gdrive_op = {
            "operator": "storage",
            "config": {
                "destination_config": {
                    "provider": "google_drive",
                    "provider_config": {"folder_id": "target_folder", "drive_id": "shared_1"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_gdrive_op) == (
            "googledrive://drive.google.com/shared_1",
            "target_folder",
        )

        storage_custom_op = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "custom_store",
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_custom_op) == (
            "custom_store://destination",
            "output",
        )

        # Storage filesystem: FilesystemDestinationConfig uses root_path
        storage_local_single = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "local",
                    "provider_config": {"root_path": "/tmp/local_out"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_local_single) == (
            "file",
            "/tmp/local_out",
        )

        # S3 destination: key_prefix is the adapter field
        storage_s3_key_prefix = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "s3",
                    "provider_config": {"bucket": "out-bucket", "key_prefix": "exports/documents/"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=storage_s3_key_prefix) == (
            "s3://out-bucket",
            "exports/documents",
        )

        # Document set default name
        docset_default = {"operator": "DocumentSetOperator", "config": {}}
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=docset_default) == (
            "docpipe://document_set",
            "document_set",
        )

    def test_distinct_locations_do_not_collapse_to_one_dataset(self) -> None:
        """Different Box folders, SharePoint drives and Drive folders must map to different datasets."""

        def sink(provider: str, provider_config: dict[str, Any]) -> tuple[str, str] | None:
            op = {
                "operator": "storage_output",
                "config": {"destination_config": {"provider": provider, "provider_config": provider_config}},
            }
            return LineageUtils.derive_dataset_info_from_sink(operator_def=op)

        def ingest(provider: str, provider_config: dict[str, Any]) -> tuple[str, str]:
            op = {"config": {"provider": provider, "provider_config": provider_config}}
            return LineageUtils.derive_dataset_info_from_ingest(ingest_operator=op)

        assert sink("box", {"folder_id": "1"}) != sink("box", {"folder_id": "2"})
        assert sink("sharepoint", {"drive_id": "d1", "folder_path": "/a"}) != sink(
            "sharepoint", {"drive_id": "d2", "folder_path": "/a"}
        )
        assert sink("sharepoint", {"drive_id": "d1", "folder_path": "/a"}) != sink(
            "sharepoint", {"drive_id": "d1", "folder_path": "/b"}
        )
        assert sink("google_drive", {"folder_id": "f1"}) != sink("google_drive", {"folder_id": "f2"})
        assert sink("google_drive", {"folder_id": "f1"}) != sink("google_drive", {"folder_id": "f1", "drive_id": "s1"})
        assert sink("filesystem", {"root_path": "/a"}) != sink("filesystem", {"root_path": "/b"})
        assert sink("s3", {"bucket": "b", "key_prefix": "x/"}) != sink("s3", {"bucket": "b", "key_prefix": "y/"})

        assert ingest("box", {"folder_id": "1"}) != ingest("box", {"folder_id": "2"})
        assert ingest("sharepoint", {"document_library_id": "l1"}) != ingest(
            "sharepoint", {"document_library_id": "l2"}
        )
        assert ingest("google_drive", {"folder_id": "f1"}) != ingest("google_drive", {"folder_id": "f2"})

        # A source and destination pointing at the same SharePoint library resolve to one dataset
        assert ingest("sharepoint", {"document_library_id": "d1", "folder_path": "/a"}) == sink(
            "sharepoint", {"drive_id": "d1", "folder_path": "/a"}
        )

    def test_onedrive_dropbox_web_sources(self) -> None:
        def ingest(provider: str, provider_config: dict[str, Any]) -> tuple[str, str]:
            op = {"config": {"provider": provider, "provider_config": provider_config}}
            return LineageUtils.derive_dataset_info_from_ingest(ingest_operator=op)

        # OneDriveSourceConfig uses drive_id + folder_path
        assert ingest("onedrive", {"drive_id": "b!drv1", "folder_path": "/Docs/"}) == (
            "onedrive://graph.microsoft.com:443/b!drv1",
            "/Docs",
        )
        assert ingest("onedrive", {"drive_id": "b!drv1"}) != ingest("onedrive", {"drive_id": "b!drv2"})
        # a OneDrive drive and a SharePoint library are different services, even for the same ID
        assert ingest("onedrive", {"drive_id": "x"}) != ingest("sharepoint", {"document_library_id": "x"})

        # DropboxSourceConfig uses folder_path only
        assert ingest("dropbox", {"folder_path": "/Reports"}) == ("dropbox://api.dropbox.com", "/Reports")
        assert ingest("dropbox", {}) == ("dropbox://api.dropbox.com", "/")
        assert ingest("dropbox", {"folder_path": "/a"}) != ingest("dropbox", {"folder_path": "/b"})

        # WebSourceConfig uses urls; only scheme, host and port are used for the namespace
        assert ingest("web", {"urls": ["https://docs.example.com/guide/start"]}) == (
            "https://docs.example.com",
            "/guide/start",
        )
        assert ingest("web", {"urls": ["http://localhost:8080"]}) == ("http://localhost:8080", "/")
        assert ingest("web", {"urls": ["https://a.example.com"]}) != ingest("web", {"urls": ["https://b.example.com"]})
        # credentials embedded in the URL must never reach the dataset identity
        url = "https://user:s3cret@docs.example.com/p"  # pragma: allowlist secret
        namespace, name = ingest("web", {"urls": [url]})
        assert "s3cret" not in namespace + name
        assert "user" not in namespace + name
        # no usable URL falls back to the generic placeholder
        assert ingest("web", {}) == ("web://source", "source")

    def test_milvus_identity_follows_auth_type(self) -> None:
        def milvus(provider_config: dict[str, Any]) -> tuple[str, str] | None:
            op = {"operator": "vectordb", "config": {"provider": "milvus", "provider_config": provider_config}}
            return LineageUtils.derive_dataset_info_from_sink(operator_def=op)

        assert milvus({"host": "m1", "port": 19530, "auth_type": "standalone", "collection_name": "c"}) == (
            "milvus://m1:19530",
            "default.c",
        )
        # uri auth: host and port come from the URI, not from the localhost default
        assert milvus(
            {
                "uri": "https://ibmlhapikey_bob:topsecret@wxdata.example.com:31234",  # pragma: allowlist secret
                "auth_type": "uri",
                "collection_name": "c",
            }
        ) == ("milvus://wxdata.example.com:31234", "default.c")
        assert milvus({"uri": "https://a.example.com:1", "auth_type": "uri", "collection_name": "c"}) != milvus(
            {"uri": "https://b.example.com:1", "auth_type": "uri", "collection_name": "c"}
        )
        # API key embedded in the URI must never reach the dataset identity
        namespace, name = milvus(
            {"uri": "https://ibmlhapikey_bob:topsecret@h.example.com:1", "auth_type": "uri"}  # pragma: allowlist secret
        ) or ("", "")
        assert "topsecret" not in namespace + name
        assert "bob" not in namespace + name
        # lite auth: the local .db file is the endpoint
        assert milvus({"uri": "./data/a.db", "auth_type": "lite", "collection_name": "c"}) == (
            "milvus://lite/./data/a.db",
            "default.c",
        )
        assert milvus({"uri": "./data/a.db", "auth_type": "lite"}) != milvus(
            {"uri": "./data/b.db", "auth_type": "lite"}
        )
        # database is part of the name
        assert milvus({"host": "m1", "database": "kb", "collection_name": "c"}) == ("milvus://m1:19530", "kb.c")

    def test_env_var_placeholders_are_resolved_like_the_adapters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOX_SRC_FOLDER", "111")
        monkeypatch.setenv("BOX_DST_FOLDER", "222")
        monkeypatch.setenv("SP_DRIVE", "b!live")
        monkeypatch.setenv("OUT_BUCKET", "prod-bucket")
        monkeypatch.setenv("OS_HOST", "search.internal")

        box_src = {"config": {"provider": "box", "provider_config": {"folder_id": "${BOX_SRC_FOLDER}"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=box_src)[1] == "111"

        sink = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "box",
                    "provider_config": {"folder_id": "${BOX_DST_FOLDER}"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=sink) == (
            "box://app.box.com:443/default",
            "222",
        )

        sp = {"config": {"provider": "sharepoint", "provider_config": {"document_library_id": "${SP_DRIVE}"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=sp)[0].endswith("/b!live")

        s3_sink = {
            "operator": "storage_output",
            "config": {
                "destination_config": {
                    "provider": "s3",
                    "provider_config": {"bucket": "${OUT_BUCKET}", "key_prefix": "out/"},
                }
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=s3_sink) == ("s3://prod-bucket", "out")

        os_sink = {
            "operator": "vectordb",
            "config": {
                "provider": "opensearch",
                "provider_config": {"host": "$OS_HOST", "port": 9200, "index_name": "idx"},
            },
        }
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=os_sink) == (
            "opensearch://search.internal:9200",
            "idx",
        )

    def test_unset_env_var_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lineage must never fail a flow because a variable is unset; the placeholder is kept as written."""
        monkeypatch.delenv("DEFINITELY_UNSET_FOLDER", raising=False)
        op = {"config": {"provider": "box", "provider_config": {"folder_id": "${DEFINITELY_UNSET_FOLDER}"}}}
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=op) == (
            "box://app.box.com:443/default",
            "${DEFINITELY_UNSET_FOLDER}",
        )

    def test_resolution_does_not_mutate_the_flow_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOX_SRC_FOLDER", "111")
        provider_config = {"folder_id": "${BOX_SRC_FOLDER}"}
        op = {"config": {"provider": "box", "provider_config": provider_config}}
        LineageUtils.derive_dataset_info_from_ingest(ingest_operator=op)
        assert provider_config["folder_id"] == "${BOX_SRC_FOLDER}"

    @pytest.mark.parametrize(
        ("dataset_type", "config", "expected"),
        [
            ("filesystem", {"root_path": "/data/out/"}, ("file", "/data/out")),
            ("filesystem", {"paths": ["/data/in/"]}, ("file", "/data/in")),
            ("s3", {"bucket": "b", "prefix": "in/"}, ("s3://b", "in")),
            ("s3", {"bucket": "b", "key_prefix": "out/"}, ("s3://b", "out")),
            ("box", {"folder_id": "42"}, ("box://app.box.com:443/default", "42")),
            ("sharepoint", {"drive_id": "d", "folder_path": "/x"}, ("mssharepoint://graph.microsoft.com:443/d", "/x")),
            ("sharepoint", {"document_library_id": "d"}, ("mssharepoint://graph.microsoft.com:443/d", "/")),
            ("onedrive", {"drive_id": "d"}, ("onedrive://graph.microsoft.com:443/d", "/")),
            ("google_drive", {"drive_id": "s", "folder_id": "f"}, ("googledrive://drive.google.com/s", "f")),
            ("dropbox", {"folder_path": "/r"}, ("dropbox://api.dropbox.com", "/r")),
            ("web", {"urls": ["https://e.com/a"]}, ("https://e.com", "/a")),
            ("opensearch", {"host": "h", "port": 9201, "index_name": "i"}, ("opensearch://h:9201", "i")),
            ("milvus", {"host": "h", "database": "d", "collection_name": "c"}, ("milvus://h:19530", "d.c")),
            ("document_set", {"document_set_name": "s"}, ("docpipe://document_set", "s")),
            ("qdrant", {"host": "q", "port": 6333, "collection_name": "c"}, ("qdrant://q:6333", "c")),
        ],
    )
    def test_get_dataset_info_by_dataset_type(
        self, dataset_type: str, config: dict[str, Any], expected: tuple[str, str]
    ) -> None:
        assert LineageUtils.get_dataset_info(dataset_type=dataset_type, config=config) == expected

    def test_get_dataset_info_is_the_single_source_of_truth_for_ingest_and_sink(self) -> None:
        """Ingest and sink wrappers only pick type and config; both must agree with get_dataset_info."""
        cfg = {"drive_id": "d1", "folder_path": "/a"}
        expected = LineageUtils.get_dataset_info(dataset_type="sharepoint", config=cfg)
        ingest = {"config": {"provider": "sharepoint", "provider_config": cfg}}
        sink = {
            "operator": "storage_output",
            "config": {"destination_config": {"provider": "sharepoint", "provider_config": cfg}},
        }
        assert LineageUtils.derive_dataset_info_from_ingest(ingest_operator=ingest) == expected
        assert LineageUtils.derive_dataset_info_from_sink(operator_def=sink) == expected

    def test_get_dataset_info_unknown_type_keeps_source_and_destination_apart(self) -> None:
        """An unrecognised provider used on both ends must not collapse into one dataset (cycle in Marquez)."""
        src = LineageUtils.get_dataset_info(dataset_type="azure_blob", config={}, role="source")
        dst = LineageUtils.get_dataset_info(dataset_type="azure_blob", config={}, role="destination")
        assert src == ("azure_blob://source", "source")
        assert dst == ("azure_blob://destination", "output")
        assert src != dst

    def test_provider_aliases_resolve_like_their_canonical_provider(self) -> None:
        """The Box source registers as ``box_driver`` and IBM COS aliases ``s3``; both must get a real ID.

        Without the alias they fall through to the generic fallback, which ignores the config and gives one
        fixed ID per role, so every Box or COS flow would collapse into a single dataset.
        """
        box_cfg = {"folder_id": "123"}
        assert LineageUtils.get_dataset_info(dataset_type="box_driver", config=box_cfg) == (
            "box://app.box.com:443/default",
            "123",
        )
        assert LineageUtils.get_dataset_info(
            dataset_type="box_driver", config=box_cfg
        ) == LineageUtils.get_dataset_info(dataset_type="box", config=box_cfg)
        assert LineageUtils.get_dataset_info(dataset_type="box_driver", config={"folder_id": "1"}) != (
            LineageUtils.get_dataset_info(dataset_type="box_driver", config={"folder_id": "2"})
        )

        cos_source = {"bucket": "b", "prefix": "in/"}
        cos_sink = {"bucket": "b", "key_prefix": "in/"}
        assert LineageUtils.get_dataset_info(dataset_type="ibm_cos", config=cos_source) == ("s3://b", "in")
        assert LineageUtils.get_dataset_info(dataset_type="ibm_cos", config=cos_source) == (
            LineageUtils.get_dataset_info(dataset_type="ibm_cos", config=cos_sink)
        )

    def test_box_source_and_destination_name_the_same_folder_identically(self) -> None:
        """A Box ingest (``box_driver``) and a Box sink (``box``) on one folder must be the same dataset."""
        ingest = {"config": {"provider": "box_driver", "provider_config": {"folder_id": "42"}}}
        sink = {
            "operator": "storage_output",
            "config": {"destination_config": {"provider": "box", "provider_config": {"folder_id": "42"}}},
        }
        assert LineageUtils.derive_dataset_info_from_ingest(
            ingest_operator=ingest
        ) == LineageUtils.derive_dataset_info_from_sink(operator_def=sink)

    @pytest.mark.parametrize("provider", ["S3", " s3 ", "Box_Driver", "IBM_COS"])
    def test_provider_name_is_normalised_like_the_ingest_operator(self, provider: str) -> None:
        """IngestSourceOperator lower-cases the provider, so mixed case or padding must still hit a rule."""
        info = LineageUtils.get_dataset_info(dataset_type=provider, config={"bucket": "b", "folder_id": "7"})
        assert not info[0].endswith("://source")
        assert info[0].startswith(("s3://", "box://"))

    def test_single_file_ingest_does_not_collapse_to_the_folder_default(self) -> None:
        """file_id / file_path name the dataset when set, since the adapter then ignores the folder fields."""

        def info(provider: str, config: dict[str, Any]) -> tuple[str, str]:
            return LineageUtils.get_dataset_info(dataset_type=provider, config=config)

        assert info("box_driver", {"file_id": "9"}) == ("box://app.box.com:443/default", "9")
        assert info("box_driver", {"file_id": "9", "folder_id": "5"}) == ("box://app.box.com:443/default", "9")
        assert info("box_driver", {"file_id": "1"}) != info("box_driver", {"file_id": "2"})
        assert info("google_drive", {"file_id": "f1"})[1] == "f1"
        assert info("google_drive", {"file_id": "f1", "folder_id": "d"})[1] == "f1"
        assert info("sharepoint", {"drive_id": "d", "file_path": "/a/x.txt"})[1] == "/a/x.txt"
        assert info("onedrive", {"drive_id": "d", "file_path": "/a/x.txt"})[1] == "/a/x.txt"
        assert info("dropbox", {"file_path": "/a/x.txt", "folder_path": "/a"})[1] == "/a/x.txt"
        # no file set: the folder still names the dataset
        assert info("dropbox", {"folder_path": "/a"})[1] == "/a"

    def test_file_path_url_query_and_fragment_are_not_kept(self) -> None:
        """A SharePoint/OneDrive file_path may be a URL; query and fragment can carry share tokens."""
        _, name = LineageUtils.get_dataset_info(
            dataset_type="sharepoint",
            config={"drive_id": "d", "file_path": "https://x.sharepoint.com/a/b.docx?id=1&token=abc#frag"},
        )
        assert name == "https://x.sharepoint.com/a/b.docx"

    def test_sink_accepts_raw_flow_json_type_key(self) -> None:
        """Compiled nodes use ``operator``; raw flow JSON uses ``type``. Both must work, ``operator`` first."""
        config = {"provider": "opensearch", "provider_config": {"host": "h", "port": 9200, "index_name": "i"}}
        expected = ("opensearch://h:9200", "i")
        assert (
            LineageUtils.derive_dataset_info_from_sink(operator_def={"type": "vectordb", "config": config}) == expected
        )
        assert (
            LineageUtils.derive_dataset_info_from_sink(operator_def={"operator": "vectordb", "config": config})
            == expected
        )
        assert (
            LineageUtils.derive_dataset_info_from_sink(
                operator_def={"operator": "vectordb", "type": "noop", "config": config}
            )
            == expected
        )

    def test_get_dataset_info_resolves_env_vars_in_dataset_type_and_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAGE_TEST_BUCKET", "env-bucket")
        assert LineageUtils.get_dataset_info(dataset_type="s3", config={"bucket": "${LINEAGE_TEST_BUCKET}"}) == (
            "s3://env-bucket",
            "/",
        )

    def test_derive_ingest_dataset_name(self) -> None:
        ingest_op = {
            "config": {
                "provider": "filesystem",
                "connection_params": {"paths": ["/data/input/"]},
            }
        }
        assert LineageUtils.derive_ingest_dataset_name(ingest_operator=ingest_op) == "/data/input"

        op_with_paths = {
            "config": {
                "provider": "filesystem",
                "connection_params": {"paths": ["./tests/fixtures/customer_support_docs/"]},
            }
        }
        assert (
            LineageUtils.derive_ingest_dataset_name(ingest_operator=op_with_paths)
            == "./tests/fixtures/customer_support_docs"
        )
