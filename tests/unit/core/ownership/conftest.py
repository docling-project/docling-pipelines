# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared fixtures for service-level ownership tests."""

from typing import Any
from unittest.mock import Mock

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.models.actor_context import ActorContext
from docpipe.core.projects.domain.models.project import Project

DEFINITION = {"doc_type": "pipeline", "pipelines": []}


class InMemoryFlowRepository:
    """Minimal in-memory stand-in for ``AssetRepository[Flow]``."""

    def __init__(self) -> None:
        self.flows: dict[str, Flow] = {}

    def save(self, *, asset: Flow) -> Flow:
        self.flows[asset.flow_id] = asset
        return asset

    def find_by_id(self, *, asset_id: str) -> Flow | None:
        return self.flows.get(asset_id)

    def find_all(self) -> list[Flow]:
        return list(self.flows.values())

    def exists_by_name(self, *, name: str) -> bool:
        return any(f.name == name for f in self.flows.values())

    def update(self, *, asset: Flow) -> Flow:
        self.flows[asset.flow_id] = asset
        return asset

    def partial_update(self, asset: Flow, updates: dict[str, Any]) -> Flow:
        for key, value in updates.items():
            setattr(asset, key, value)
        return asset

    def delete(self, *, asset_id: str) -> bool:
        return self.flows.pop(asset_id, None) is not None

    def bulk_delete(self, *, asset_ids: list[str]) -> dict[str, Any]:
        deleted = [i for i in asset_ids if self.flows.pop(i, None) is not None]
        failed = [{"flow_id": i, "error": "not found"} for i in asset_ids if i not in deleted]
        return {
            "deleted": deleted,
            "failed": failed,
            "total_requested": len(asset_ids),
            "total_deleted": len(deleted),
            "total_failed": len(failed),
        }


class InMemoryProjectRepository:
    """Minimal in-memory stand-in for ``ProjectRepository``."""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}

    def save(self, *, project: Project) -> Project:
        self.projects[project.project_id] = project
        return project

    def get(self, *, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def find_all(self) -> list[Project]:
        return list(self.projects.values())

    def update(self, *, project: Project) -> Project:
        self.projects[project.project_id] = project
        return project

    def delete(self, *, project_id: str) -> bool:
        return self.projects.pop(project_id, None) is not None

    def exists(self, *, project_id: str) -> bool:
        return project_id in self.projects

    def exists_by_name(self, *, name: str) -> bool:
        return any(p.name == name for p in self.projects.values())


def make_flow(*, flow_id: str, created_by: str | None = None, container_id: str | None = None) -> Flow:
    return Flow(
        asset_id=flow_id,
        name=f"flow-{flow_id}",
        definition=dict(DEFINITION),
        container_kind="project" if container_id else None,
        container_id=container_id,
        created_by=created_by,
    )


def make_actor(username: str, *roles: str) -> ActorContext:
    return ActorContext(username=username, roles=frozenset(roles))


@pytest.fixture
def alice() -> ActorContext:
    return make_actor("alice", "editor")


@pytest.fixture
def bob() -> ActorContext:
    return make_actor("bob", "editor")


@pytest.fixture
def admin() -> ActorContext:
    return make_actor("root", "admin")


@pytest.fixture
def viewer() -> ActorContext:
    return make_actor("vera", "viewer")


@pytest.fixture
def flow_repo() -> InMemoryFlowRepository:
    return InMemoryFlowRepository()


@pytest.fixture
def flow_service(flow_repo) -> FlowService:
    return FlowService(repository=flow_repo)  # type: ignore[arg-type]


@pytest.fixture
def project_repo() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


@pytest.fixture
def job_stats_service() -> Mock:
    return Mock()
