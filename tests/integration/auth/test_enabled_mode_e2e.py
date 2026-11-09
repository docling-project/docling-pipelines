# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""End-to-end tests of the real ``/api/v1`` app with authentication enabled.

The app, routes, guards, session dependency, CSRF check, login, logout, services and
repositories are real. Storage is real and lives under ``tmp_path``: local JSON files for
flows and projects, DuckDB files for document sets and libraries, a file-backed custom
operator store, and the in-memory job stats store. Only the flow executor thread pool is
replaced, so a created job run stays queued instead of running a pipeline.

The administrator logs in through ``POST /auth/login`` with a bootstrap account whose
bcrypt hash is generated in the test. Viewer and editor sessions use tokens minted by the
JWT handler, because no login method yields those roles without LDAP or OIDC.
"""

from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import bcrypt
import pytest
from fastapi.testclient import TestClient

from docpipe.api import dependencies as deps
from docpipe.api import main as api_main
from docpipe.api.auth.bootstrap_auth import BootstrapAdminAuthenticator
from docpipe.api.auth.config import DEFAULT_COOKIE_NAME
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.main import app
from docpipe.api.middleware import rate_limit
from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
from docpipe.core.assets.common.adapters.repositories.local_asset_repository import LocalAssetRepository
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory
from docpipe.core.assets.document_libraries.application.services.document_library_service import (
    DocumentLibraryService,
)
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.assets.document_sets.factories import DataStoreFactory
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.core.job_management.adapters.frameworks import DefaultJobRunManager
from docpipe.core.job_management.adapters.services import JobTrackerService
from docpipe.core.job_management.adapters.stores import InMemoryJobStatsStore
from docpipe.core.job_management.application.services import JobManagementService, NodeStatsAggregator
from docpipe.core.projects.adapters.repositories.local.local_project_repository import LocalProjectRepository
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage

_JWT_SECRET = "e2e-test-secret-key-that-is-long-enough"  # pragma: allowlist secret
_ADMIN_USERNAME = "breakglass"
_ADMIN_PASSWORD = "e2e-admin-password"  # pragma: allowlist secret
_CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
_MISSING_ID = "99999999-9999-4999-8999-999999999999"

_AUTHORING_FLOW = {
    "flow_name": "e2e-flow",
    "flow": [{"type": "ingest_source", "name": "ingest", "config": {}, "depends_on": []}],
    "global_config": {},
}

_OPERATOR_CODE = """
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class E2ECustomOperator(AbstractOperator):
    short_name = "e2e_custom_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "e2e_custom_op"}
"""

_LIST_URLS = (
    "/api/v1/flows",
    "/api/v1/projects",
    "/api/v1/job_runs",
    "/api/v1/document-sets",
    "/api/v1/document-libraries",
    "/api/v1/custom_operators",
)


@dataclass(frozen=True)
class Stack:
    """Real services wired over temp-dir storage, plus a client for the real app."""

    client: TestClient
    jwt_config: JWTConfig

    def headers(self, *, username: str, role: str) -> dict[str, str]:
        """Return a Bearer header for a token minted by the JWT handler."""
        token = create_access_token({"username": username, "roles": [role]}, self.jwt_config)
        return {"Authorization": f"Bearer {token}"}

    def viewer(self) -> dict[str, str]:
        return self.headers(username="vera", role="viewer")

    def alice(self) -> dict[str, str]:
        return self.headers(username="alice", role="editor")

    def bob(self) -> dict[str, str]:
        return self.headers(username="bob", role="editor")


@pytest.fixture(autouse=True)
def _clean_throttle() -> Generator[None, None, None]:
    rate_limit.reset_all_state()
    yield
    rate_limit.reset_all_state()


@pytest.fixture
def stack(*, tmp_path: Path, auth_enabled: None, monkeypatch: pytest.MonkeyPatch) -> Generator[Stack, None, None]:
    """Build real services over ``tmp_path`` and enable authentication with a bootstrap admin."""
    del auth_enabled
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
    for name in ("DOCPIPE_TRUST_PROXY_HEADERS", "DOCPIPE_AUTH_COOKIE_SECURE", "DOCPIPE_AUTH_COOKIE_NAME"):
        monkeypatch.delenv(name, raising=False)

    jwt_config = JWTConfig(jwt_secret_key=_JWT_SECRET)
    password_hash = bcrypt.hashpw(_ADMIN_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setattr(api_main, "jwt_config", jwt_config)
    monkeypatch.setattr(api_main, "ldap_authenticator", None)
    monkeypatch.setattr(
        api_main,
        "bootstrap_authenticator",
        BootstrapAdminAuthenticator(username=_ADMIN_USERNAME, password_hash=password_hash),
    )

    flow_repository = LocalAssetRepository(asset_type=Flow, storage_path=str(tmp_path / "flows"))
    stats_store = InMemoryJobStatsStore()
    job_stats_service = JobTrackerService(
        job_stats_store=stats_store,
        node_stats_aggregator=NodeStatsAggregator(job_stats_store=stats_store),
    )
    flow_service = FlowService(repository=flow_repository, job_stats_service=job_stats_service)
    project_service = ProjectService(
        repository=LocalProjectRepository(base_dir=tmp_path / "projects"),
        flow_repository=flow_repository,
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )
    job_management_service = JobManagementService(
        job_stats_service=job_stats_service,
        job_run_manager=DefaultJobRunManager(job_stats_service=job_stats_service),
        flow_service=flow_service,
        executor=MagicMock(spec=ThreadPoolExecutor),
    )

    sets_db = str(tmp_path / "document_sets.duckdb")
    document_set_service = DocumentSetService(
        metadata_repository=DuckDBAssetRepository.from_config(
            asset_type=DocumentSet, config={"database_path": sets_db}
        ),
        data_store=DataStoreFactory.create(adapter_name="duckdb", config={"database_path": sets_db}),
        attachment_repository=AttachmentRepositoryFactory.create(
            adapter_name="duckdb", config={"database_path": sets_db}
        ),
    )
    libraries_db = str(tmp_path / "document_libraries.duckdb")
    document_library_service = DocumentLibraryService(
        repository=DuckDBAssetRepository.from_config(asset_type=DocumentLibrary, config={"database_path": libraries_db})
    )
    custom_operator_service = CustomOperatorService(
        file_store=LocalFileStore(base_dir=tmp_path / "custom_operators"),
        metadata_storage=KeyValueFileSystemStorage(base_dir=tmp_path),
    )

    overrides: dict[Callable[..., Any], Any] = {
        deps.get_flow_service: flow_service,
        deps.get_project_service: project_service,
        deps.get_job_management_service: job_management_service,
        deps.get_job_stats_service: job_stats_service,
        deps.get_document_set_service: document_set_service,
        deps.get_document_library_service: document_library_service,
        deps.get_custom_operator_service: custom_operator_service,
        deps.get_event_mapping_service: MagicMock(),
    }
    for dependency, instance in overrides.items():
        app.dependency_overrides[dependency] = _provide(instance)
    try:
        yield Stack(client=TestClient(app, raise_server_exceptions=False), jwt_config=jwt_config)
    finally:
        app.dependency_overrides.clear()
        job_management_service.shutdown()


def _provide(instance: Any) -> Callable[[], Any]:
    """Return a no-argument dependency override that yields ``instance``."""
    return lambda: instance


def _login_client() -> TestClient:
    """Return a fresh cookie-holding client for real-login tests."""
    return TestClient(app, raise_server_exceptions=False)


def _admin_login(*, client: TestClient) -> dict[str, Any]:
    response = client.post("/auth/login", json={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD})
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _admin_headers(*, stack: Stack) -> dict[str, str]:
    """Log in as the bootstrap administrator and return the issued token as a Bearer header."""
    body = _admin_login(client=_login_client())
    return {"Authorization": f"Bearer {body['access_token']}"}


def _operator_upload(*, name: str = "E2E custom operator") -> dict[str, Any]:
    return {
        "data": {"name": name, "description": "uploaded by the e2e suite"},
        "files": {"operator_file": ("e2e_operator.py", _OPERATOR_CODE, "text/x-python")},
    }


@dataclass(frozen=True)
class Seed:
    """Identifiers of one resource of each kind, owned by alice unless noted."""

    flow_id: str
    project_id: str
    job_run_id: str
    document_set_id: str
    library_id: str
    operator_id: str


def _seed(*, stack: Stack) -> Seed:
    """Create one of each asset through the API: owned by alice, the operator by the admin."""
    client = stack.client
    alice = stack.alice()
    flow = client.post("/api/v1/flows", json=_AUTHORING_FLOW, headers=alice)
    assert flow.status_code == 201, flow.text
    flow_id = flow.json()["flow_id"]
    project = client.post("/api/v1/projects", json={"name": "e2e project"}, headers=alice)
    assert project.status_code == 201, project.text
    run = client.post("/api/v1/job_runs", json={"entity": {"job": {"asset_ref": flow_id}}}, headers=alice)
    assert run.status_code == 201, run.text
    document_set = client.post("/api/v1/document-sets", json={"name": "e2e set"}, headers=alice)
    assert document_set.status_code == 201, document_set.text
    library = client.post("/api/v1/document-libraries", json={"name": "E2E library"}, headers=alice)
    assert library.status_code == 201, library.text
    operator = client.post("/api/v1/custom_operators", headers=_admin_headers(stack=stack), **_operator_upload())
    assert operator.status_code == 201, operator.text
    return Seed(
        flow_id=flow_id,
        project_id=project.json()["project_id"],
        job_run_id=run.json()["job_run_id"],
        document_set_id=document_set.json()["id"],
        library_id=library.json()["library_id"],
        operator_id=operator.json()["operator_id"],
    )


def _snapshot(*, stack: Stack) -> dict[str, Any]:
    """Read every listing as the admin; used to prove a refused write changed nothing."""
    headers = _admin_headers(stack=stack)
    snapshot: dict[str, Any] = {}
    for url in _LIST_URLS:
        response = stack.client.get(url, headers=headers)
        assert response.status_code == 200, f"{url}: {response.text}"
        snapshot[url] = response.json()
    return snapshot


def _assert_forbidden(response: Any) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["errors"][0]["code"] == "forbidden"


# Every write action that the UI hides from a viewer. Each entry maps a name to a builder
# that returns (method, url, request kwargs) for the seeded resources.
_WRITE_ACTIONS: dict[str, Callable[[Seed], tuple[str, str, dict[str, Any]]]] = {
    "create_flow": lambda s: ("POST", "/api/v1/flows", {"json": {**_AUTHORING_FLOW, "flow_name": "viewer-flow"}}),
    "update_flow": lambda s: ("PUT", f"/api/v1/flows/{s.flow_id}", {"json": _AUTHORING_FLOW}),
    "patch_flow": lambda s: ("PATCH", f"/api/v1/flows/{s.flow_id}", {"json": {"description": "changed"}}),
    "delete_flow": lambda s: ("DELETE", f"/api/v1/flows/{s.flow_id}", {}),
    "bulk_delete_flows": lambda s: ("DELETE", "/api/v1/flows", {"params": {"flow_ids": s.flow_id}}),
    "create_project": lambda s: ("POST", "/api/v1/projects", {"json": {"name": "viewer project"}}),
    "replace_project": lambda s: ("PUT", f"/api/v1/projects/{s.project_id}", {"json": {"name": "renamed"}}),
    "patch_project": lambda s: ("PATCH", f"/api/v1/projects/{s.project_id}", {"json": {"description": "changed"}}),
    "delete_project": lambda s: ("DELETE", f"/api/v1/projects/{s.project_id}", {}),
    "run_flow": lambda s: ("POST", "/api/v1/job_runs", {"json": {"entity": {"job": {"asset_ref": s.flow_id}}}}),
    "cancel_job_run": lambda s: ("POST", f"/api/v1/job_runs/{s.job_run_id}/cancel", {}),
    "delete_job_run": lambda s: ("DELETE", f"/api/v1/job_runs/{s.job_run_id}", {}),
    "create_document_set": lambda s: ("POST", "/api/v1/document-sets", {"json": {"name": "viewer set"}}),
    "update_document_set": lambda s: (
        "PATCH",
        f"/api/v1/document-sets/{s.document_set_id}",
        {"json": {"description": "changed"}},
    ),
    "delete_document_set": lambda s: ("DELETE", f"/api/v1/document-sets/{s.document_set_id}", {}),
    "create_document_library": lambda s: ("POST", "/api/v1/document-libraries", {"json": {"name": "Viewer library"}}),
    "update_document_library": lambda s: (
        "PATCH",
        f"/api/v1/document-libraries/{s.library_id}",
        {"json": {"description": "changed"}},
    ),
    "delete_document_library": lambda s: ("DELETE", f"/api/v1/document-libraries/{s.library_id}", {}),
    "attach_document_set": lambda s: (
        "PUT",
        f"/api/v1/document-libraries/{s.library_id}/document-sets",
        {"params": {"document_sets_ids": s.document_set_id}},
    ),
    "detach_document_set": lambda s: (
        "DELETE",
        f"/api/v1/document-libraries/{s.library_id}/document-sets",
        {"params": {"document_sets_ids": s.document_set_id}},
    ),
    "create_custom_operator": lambda s: (
        "POST",
        "/api/v1/custom_operators",
        _operator_upload(name="Viewer operator"),
    ),
    "update_custom_operator": lambda s: (
        "PATCH",
        f"/api/v1/custom_operators/{s.operator_id}",
        {"data": {"name": "Renamed operator"}},
    ),
    "delete_custom_operator": lambda s: ("DELETE", f"/api/v1/custom_operators/{s.operator_id}", {}),
    "create_event_mapping": lambda s: ("POST", "/api/v1/event_mappings", {"json": {}}),
    "update_event_mapping": lambda s: ("PUT", "/api/v1/event_mappings/key", {"json": {}}),
    "delete_event_mapping": lambda s: ("DELETE", "/api/v1/event_mappings/key", {}),
}


class TestUnauthenticated:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", "/api/v1/flows"),
            ("GET", "/api/v1/projects"),
            ("GET", "/api/v1/job_runs"),
            ("GET", "/api/v1/document-sets"),
            ("GET", "/api/v1/document-libraries"),
            ("GET", "/api/v1/custom_operators"),
            ("GET", "/api/v1/operators/metadata"),
            ("POST", "/api/v1/flows"),
            ("POST", "/api/v1/projects"),
            ("POST", "/api/v1/job_runs"),
            ("POST", "/api/v1/custom_operators"),
            ("POST", "/api/v1/validation/validate_flow"),
            ("DELETE", f"/api/v1/flows/{_MISSING_ID}"),
        ],
    )
    def test_request_without_credentials_is_401(self, *, stack: Stack, method: str, url: str) -> None:
        response = stack.client.request(method, url)

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_bearer_token_is_401(self, *, stack: Stack) -> None:
        response = stack.client.get("/api/v1/flows", headers={"Authorization": "Bearer not-a-jwt"})

        assert response.status_code == 401

    def test_token_signed_with_another_key_is_401(self, *, stack: Stack) -> None:
        forged = create_access_token(
            {"username": "mallory", "roles": ["admin"]},
            JWTConfig(jwt_secret_key="some-other-secret-key-that-is-long-enough"),  # pragma: allowlist secret
        )

        response = stack.client.get("/api/v1/flows", headers={"Authorization": f"Bearer {forged}"})

        assert response.status_code == 401

    def test_health_and_auth_config_stay_public(self, *, stack: Stack) -> None:
        assert stack.client.get("/health").status_code == 200
        config = stack.client.get("/auth/config")
        assert config.status_code == 200
        assert config.json()["auth_enabled"] is True

    def test_nothing_is_created_by_an_unauthenticated_post(self, *, stack: Stack) -> None:
        stack.client.post("/api/v1/flows", json=_AUTHORING_FLOW)

        listing = stack.client.get("/api/v1/flows", headers=stack.viewer()).json()
        assert listing["total_count"] == 0


class TestViewer:
    @pytest.mark.parametrize("url", _LIST_URLS)
    def test_viewer_can_read_listings(self, *, stack: Stack, url: str) -> None:
        response = stack.client.get(url, headers=stack.viewer())

        assert response.status_code == 200

    def test_viewer_can_read_single_assets(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        urls = [
            f"/api/v1/flows/{seed.flow_id}",
            f"/api/v1/projects/{seed.project_id}",
            f"/api/v1/job_runs/{seed.job_run_id}",
            f"/api/v1/document-sets/{seed.document_set_id}",
            f"/api/v1/document-libraries/{seed.library_id}",
            f"/api/v1/custom_operators/{seed.operator_id}",
        ]

        statuses = {url: stack.client.get(url, headers=stack.viewer()).status_code for url in urls}

        assert statuses == dict.fromkeys(urls, 200)

    @pytest.mark.parametrize("url", ["/api/v1/validation/validate_flow", "/api/v1/validation/enrich_flow_features"])
    def test_viewer_can_call_read_only_validation_posts(self, *, stack: Stack, url: str) -> None:
        response = stack.client.post(url, json=_AUTHORING_FLOW, headers=stack.viewer())

        assert response.status_code not in (401, 403)

    @pytest.mark.parametrize("action", sorted(_WRITE_ACTIONS))
    def test_viewer_gets_403_on_every_hidden_write_action_and_nothing_changes(
        self, *, stack: Stack, action: str
    ) -> None:
        seed = _seed(stack=stack)
        before = _snapshot(stack=stack)
        method, url, kwargs = _WRITE_ACTIONS[action](seed)

        response = stack.client.request(method, url, headers=stack.viewer(), **kwargs)

        _assert_forbidden(response)
        assert _snapshot(stack=stack) == before


class TestEditor:
    def test_editor_modifies_their_own_flow(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        alice = stack.alice()
        client = stack.client

        read = client.get(f"/api/v1/flows/{seed.flow_id}", headers=alice)
        replaced = client.put(
            f"/api/v1/flows/{seed.flow_id}", json={**_AUTHORING_FLOW, "description": "replaced"}, headers=alice
        )
        patched = client.patch(f"/api/v1/flows/{seed.flow_id}", json={"description": "patched"}, headers=alice)
        deleted = client.delete(f"/api/v1/flows/{seed.flow_id}", headers=alice)

        assert read.json()["created_by"] == "alice"
        assert replaced.status_code == 200
        assert patched.status_code == 200
        assert patched.json()["modified_by"] == "alice"
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/flows/{seed.flow_id}", headers=alice).status_code == 404

    def test_editor_gets_403_on_another_editors_flow_and_it_remains(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        bob = stack.bob()
        client = stack.client
        before = _snapshot(stack=stack)

        responses = [
            client.put(f"/api/v1/flows/{seed.flow_id}", json=_AUTHORING_FLOW, headers=bob),
            client.patch(f"/api/v1/flows/{seed.flow_id}", json={"description": "x"}, headers=bob),
            client.delete(f"/api/v1/flows/{seed.flow_id}", headers=bob),
        ]

        for response in responses:
            _assert_forbidden(response)
            assert "alice" not in response.text
        assert _snapshot(stack=stack) == before

    def test_bulk_delete_removes_own_flows_and_reports_foreign_ones_without_the_owner(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        client = stack.client
        bob = stack.bob()
        own = client.post("/api/v1/flows", json={**_AUTHORING_FLOW, "flow_name": "bob-flow"}, headers=bob).json()

        response = client.delete("/api/v1/flows", params={"flow_ids": f"{seed.flow_id},{own['flow_id']}"}, headers=bob)

        assert response.status_code == 200
        body = response.json()
        assert body["deleted"] == [own["flow_id"]]
        assert [item["flow_id"] for item in body["failed"]] == [seed.flow_id]
        assert "alice" not in response.text
        assert client.get(f"/api/v1/flows/{seed.flow_id}", headers=bob).status_code == 200

    def test_editor_gets_403_on_another_editors_project_and_it_remains(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        bob = stack.bob()

        responses = [
            stack.client.put(f"/api/v1/projects/{seed.project_id}", json={"name": "taken"}, headers=bob),
            stack.client.patch(f"/api/v1/projects/{seed.project_id}", json={"description": "x"}, headers=bob),
            stack.client.delete(f"/api/v1/projects/{seed.project_id}", headers=bob),
        ]

        for response in responses:
            _assert_forbidden(response)
        assert stack.client.get(f"/api/v1/projects/{seed.project_id}", headers=bob).status_code == 200

    def test_editor_can_run_a_flow_and_the_run_records_the_owner(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)

        response = stack.client.post(
            "/api/v1/job_runs", json={"entity": {"job": {"asset_ref": seed.flow_id}}}, headers=stack.bob()
        )

        assert response.status_code == 201
        listing = stack.client.get("/api/v1/job_runs", headers=stack.bob()).json()
        owners = {item["job_run_id"]: item["user_id"] for item in listing["list"]}
        assert owners[response.json()["job_run_id"]] == "bob"
        assert owners[seed.job_run_id] == "alice"

    def test_editor_gets_403_cancelling_or_deleting_another_editors_job_run(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        bob = stack.bob()
        before = _snapshot(stack=stack)

        cancel = stack.client.post(f"/api/v1/job_runs/{seed.job_run_id}/cancel", headers=bob)
        delete = stack.client.delete(f"/api/v1/job_runs/{seed.job_run_id}", headers=bob)

        _assert_forbidden(cancel)
        _assert_forbidden(delete)
        assert _snapshot(stack=stack) == before

    def test_owner_cancels_and_deletes_their_own_job_run(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        alice = stack.alice()

        cancel = stack.client.post(f"/api/v1/job_runs/{seed.job_run_id}/cancel", headers=alice)
        delete = stack.client.delete(f"/api/v1/job_runs/{seed.job_run_id}", headers=alice)

        assert cancel.status_code == 202
        assert delete.status_code == 204

    def test_editor_manages_document_sets_and_libraries(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        bob = stack.bob()
        client = stack.client

        updated_set = client.patch(
            f"/api/v1/document-sets/{seed.document_set_id}", json={"description": "edited"}, headers=bob
        )
        attached = client.put(
            f"/api/v1/document-libraries/{seed.library_id}/document-sets",
            params={"document_sets_ids": seed.document_set_id},
            headers=bob,
        )
        detached = client.delete(
            f"/api/v1/document-libraries/{seed.library_id}/document-sets",
            params={"document_sets_ids": seed.document_set_id},
            headers=bob,
        )
        updated_library = client.patch(
            f"/api/v1/document-libraries/{seed.library_id}", json={"description": "edited"}, headers=bob
        )
        deleted_set = client.delete(f"/api/v1/document-sets/{seed.document_set_id}", headers=bob)
        deleted_library = client.delete(f"/api/v1/document-libraries/{seed.library_id}", headers=bob)

        assert updated_set.status_code == 200
        assert attached.status_code == 204
        assert detached.status_code == 204
        assert updated_library.status_code == 200
        assert deleted_set.status_code == 204
        assert deleted_library.status_code == 204

    def test_editor_gets_403_on_custom_operator_upload_update_and_delete(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        alice = stack.alice()
        before = _snapshot(stack=stack)

        responses = [
            stack.client.post("/api/v1/custom_operators", headers=alice, **_operator_upload(name="Editor operator")),
            stack.client.patch(
                f"/api/v1/custom_operators/{seed.operator_id}", data={"name": "Renamed operator"}, headers=alice
            ),
            stack.client.delete(f"/api/v1/custom_operators/{seed.operator_id}", headers=alice),
        ]

        for response in responses:
            _assert_forbidden(response)
        assert _snapshot(stack=stack) == before


class TestAdmin:
    def test_admin_uploads_updates_and_deletes_a_custom_operator(self, *, stack: Stack) -> None:
        admin = _admin_headers(stack=stack)
        client = stack.client

        created = client.post("/api/v1/custom_operators", headers=admin, **_operator_upload())
        operator_id = created.json()["operator_id"]
        updated = client.patch(
            f"/api/v1/custom_operators/{operator_id}", data={"name": "Renamed operator"}, headers=admin
        )
        fetched = client.get(f"/api/v1/custom_operators/{operator_id}", headers=admin)
        deleted = client.delete(f"/api/v1/custom_operators/{operator_id}", headers=admin)

        assert created.status_code == 201
        assert updated.status_code == 200
        assert fetched.json()["name"] == "Renamed operator"
        assert deleted.status_code == 200
        assert client.get(f"/api/v1/custom_operators/{operator_id}", headers=admin).status_code == 404

    def test_admin_modifies_any_flow_project_and_job_run(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        admin = _admin_headers(stack=stack)
        client = stack.client

        patched_flow = client.patch(f"/api/v1/flows/{seed.flow_id}", json={"description": "by admin"}, headers=admin)
        patched_project = client.patch(
            f"/api/v1/projects/{seed.project_id}", json={"description": "by admin"}, headers=admin
        )
        cancelled = client.post(f"/api/v1/job_runs/{seed.job_run_id}/cancel", headers=admin)
        deleted_run = client.delete(f"/api/v1/job_runs/{seed.job_run_id}", headers=admin)
        deleted_flow = client.delete(f"/api/v1/flows/{seed.flow_id}", headers=admin)
        deleted_project = client.delete(f"/api/v1/projects/{seed.project_id}", headers=admin)

        assert patched_flow.status_code == 200
        assert patched_flow.json()["modified_by"] == _ADMIN_USERNAME
        assert patched_project.status_code == 200
        assert cancelled.status_code == 202
        assert deleted_run.status_code == 204
        assert deleted_flow.status_code == 204
        assert deleted_project.status_code == 204

    def test_admin_manages_document_sets_and_libraries(self, *, stack: Stack) -> None:
        seed = _seed(stack=stack)
        admin = _admin_headers(stack=stack)

        deleted_set = stack.client.delete(f"/api/v1/document-sets/{seed.document_set_id}", headers=admin)
        deleted_library = stack.client.delete(f"/api/v1/document-libraries/{seed.library_id}", headers=admin)

        assert deleted_set.status_code == 204
        assert deleted_library.status_code == 204


class TestSession:
    def test_login_returns_admin_roles_and_sets_the_session_cookie(self, *, stack: Stack) -> None:
        client = _login_client()

        body = _admin_login(client=client)

        assert body["user"]["username"] == _ADMIN_USERNAME
        assert body["user"]["roles"] == ["admin"]
        assert client.cookies.get(DEFAULT_COOKIE_NAME) == body["access_token"]
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["roles"] == ["admin"]

    def test_wrong_password_is_401_and_sets_no_cookie(self, *, stack: Stack) -> None:
        client = _login_client()

        response = client.post("/auth/login", json={"username": _ADMIN_USERNAME, "password": "wrong-password"})

        assert response.status_code == 401
        assert client.cookies.get(DEFAULT_COOKIE_NAME) is None

    def test_cookie_session_reads_without_the_csrf_header(self, *, stack: Stack) -> None:
        client = _login_client()
        _admin_login(client=client)

        assert client.get("/api/v1/flows").status_code == 200

    def test_cookie_mutation_without_csrf_header_is_403_and_creates_nothing(self, *, stack: Stack) -> None:
        client = _login_client()
        _admin_login(client=client)

        response = client.post("/api/v1/projects", json={"name": "csrf project"})

        assert response.status_code == 403
        assert client.get("/api/v1/projects").json()["total_count"] == 0

    def test_cookie_mutation_with_csrf_header_succeeds(self, *, stack: Stack) -> None:
        client = _login_client()
        _admin_login(client=client)

        response = client.post("/api/v1/projects", json={"name": "csrf project"}, headers=_CSRF_HEADERS)

        assert response.status_code == 201
        assert response.json()["created_by"] == _ADMIN_USERNAME

    @pytest.mark.parametrize(
        ("method", "url", "kwargs"),
        [
            ("POST", "/api/v1/projects", {"json": {"name": "csrf project"}}),
            ("DELETE", f"/api/v1/flows/{_MISSING_ID}", {}),
        ],
    )
    def test_cookie_mutation_with_an_empty_csrf_header_is_403(
        self, *, stack: Stack, method: str, url: str, kwargs: dict[str, Any]
    ) -> None:
        client = _login_client()
        _admin_login(client=client)

        response = client.request(method, url, headers={"X-Requested-With": ""}, **kwargs)

        assert response.status_code == 403

    def test_bearer_mutation_without_csrf_header_is_exempt(self, *, stack: Stack) -> None:
        body = _admin_login(client=_login_client())

        response = stack.client.post(
            "/api/v1/projects",
            json={"name": "bearer project"},
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )

        assert response.status_code == 201

    def test_logout_clears_the_cookie_and_ends_cookie_access(self, *, stack: Stack) -> None:
        client = _login_client()
        _admin_login(client=client)
        assert client.get("/api/v1/flows").status_code == 200

        response = client.post("/auth/logout", headers=_CSRF_HEADERS)

        assert response.status_code == 200
        cleared = response.headers["set-cookie"].lower()
        assert f"{DEFAULT_COOKIE_NAME}=" in cleared
        assert "max-age=0" in cleared
        assert "httponly" in cleared
        assert client.cookies.get(DEFAULT_COOKIE_NAME) is None
        assert client.get("/api/v1/flows").status_code == 401

    def test_logout_without_a_session_still_succeeds(self, *, stack: Stack) -> None:
        response = _login_client().post("/auth/logout", headers=_CSRF_HEADERS)

        assert response.status_code == 200
