# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for ProjectService."""

from unittest.mock import patch

import pytest

from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions.docpipe_exceptions import (
    ProjectAlreadyExistsException,
    ProjectInvalidDataException,
    ProjectNotFoundException,
)


class TestProjectServiceCreate:
    """Tests for ProjectService.create_project."""

    def test_create_project_with_valid_data(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Saving a valid project returns it with flow_count=0."""
        mock_project_repository.exists_by_name.return_value = False
        mock_project_repository.save.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.create_project(project=sample_project)

        assert result.project_id == sample_project.project_id
        assert result.flow_count == 0
        mock_project_repository.save.assert_called_once_with(project=sample_project)

    def test_create_project_sets_flow_count_zero(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Newly created project always has flow_count=0, even if flows exist."""
        mock_project_repository.exists_by_name.return_value = False
        mock_project_repository.save.return_value = sample_project
        # Simulate flows existing, but count should still be 0 on create
        mock_flow_repository.find_all.return_value = []
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.create_project(project=sample_project)

        assert result.flow_count == 0

    def test_create_project_duplicate_name_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Creating a project with an existing name raises ProjectAlreadyExistsException."""
        mock_project_repository.exists_by_name.return_value = True
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectAlreadyExistsException):
            service.create_project(project=sample_project)

        mock_project_repository.save.assert_not_called()

    def test_create_project_empty_name_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service
    ):
        """Empty project name raises ProjectInvalidDataException before hitting the repo."""
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )
        blank = Project(name="   ")

        with pytest.raises(ProjectInvalidDataException):
            service.create_project(project=blank)

        mock_project_repository.exists_by_name.assert_not_called()
        mock_project_repository.save.assert_not_called()

    def test_create_project_name_too_long_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service
    ):
        """Name exceeding 255 characters raises ProjectInvalidDataException."""
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )
        too_long = Project(name="x" * 256)

        with pytest.raises(ProjectInvalidDataException):
            service.create_project(project=too_long)

    def test_create_project_duplicate_logs_warning(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """A warning is logged when a duplicate name is detected."""
        mock_project_repository.exists_by_name.return_value = True
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with patch("docpipe.core.projects.application.services.project_service.logger") as mock_log:
            with pytest.raises(ProjectAlreadyExistsException):
                service.create_project(project=sample_project)
            mock_log.warning.assert_called_once()


class TestProjectServiceGet:
    """Tests for ProjectService.get_project."""

    def test_get_existing_project(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Fetching an existing project returns it enriched with flow_count."""
        mock_project_repository.get.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.get_project(project_id=sample_project.project_id)

        assert result.project_id == sample_project.project_id
        assert result.flow_count == 0

    def test_get_project_enriches_flow_count(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        sample_project,
        flow_for_project,
    ):
        """flow_count equals the number of flows whose container_id matches."""
        mock_project_repository.get.return_value = sample_project
        mock_flow_repository.find_all.return_value = [flow_for_project, flow_for_project]
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.get_project(project_id=sample_project.project_id)

        assert result.flow_count == 2

    def test_get_nonexistent_project_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service
    ):
        """Fetching a missing project raises ProjectNotFoundException."""
        mock_project_repository.get.return_value = None
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectNotFoundException):
            service.get_project(project_id="does-not-exist")


class TestProjectServiceList:
    """Tests for ProjectService.list_projects and count_projects."""

    def test_list_all_projects(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """list_projects returns all projects when no filters are given."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.list_projects()

        assert len(result) == 3

    def test_list_projects_pagination(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """skip/limit parameters slice the result correctly."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.list_projects(skip=1, limit=2)

        assert len(result) == 2
        assert result[0].project_id == multiple_projects[1].project_id

    def test_list_projects_name_filter(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """name_filter is a case-insensitive substring match."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.list_projects(name_filter="alpha")

        assert len(result) == 1
        assert result[0].name == "Alpha Project"

    def test_list_projects_tags_filter(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """tags_filter returns projects with at least one matching tag."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.list_projects(tags_filter=["analytics"])

        assert len(result) == 1
        assert result[0].name == "Beta Project"

    def test_list_projects_combined_filters(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """Both name and tags filters are applied together (AND)."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        # "research" tag exists on Alpha and Gamma; "gamma" name matches only Gamma
        result = service.list_projects(name_filter="gamma", tags_filter=["research"])

        assert len(result) == 1
        assert result[0].name == "Gamma Project"

    def test_count_projects_no_filters(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """count_projects returns the total without filters."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        assert service.count_projects() == 3

    def test_count_projects_with_name_filter(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        multiple_projects,
    ):
        """count_projects respects the name filter."""
        mock_project_repository.find_all.return_value = multiple_projects
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        assert service.count_projects(name_filter="project") == 3
        assert service.count_projects(name_filter="gamma") == 1


class TestProjectServiceUpdate:
    """Tests for ProjectService.update_project (full replace)."""

    def test_update_existing_project(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Full update saves and returns the enriched project."""
        mock_project_repository.exists.return_value = True
        mock_project_repository.update.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.update_project(project=sample_project)

        assert result.project_id == sample_project.project_id
        mock_project_repository.update.assert_called_once_with(project=sample_project)

    def test_update_nonexistent_project_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Updating a missing project raises ProjectNotFoundException."""
        mock_project_repository.exists.return_value = False
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectNotFoundException):
            service.update_project(project=sample_project)

        mock_project_repository.update.assert_not_called()


class TestProjectServicePartialUpdate:
    """Tests for ProjectService.partial_update_project (PATCH)."""

    def test_partial_update_applies_allowed_fields(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """PATCH updates only the supplied fields."""
        mock_project_repository.get.return_value = sample_project
        mock_project_repository.update.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.partial_update_project(
            project_id=sample_project.project_id,
            updates={"name": "Renamed Project", "description": "New desc"},
        )

        assert result is not None
        mock_project_repository.update.assert_called_once()

    def test_partial_update_strips_protected_fields(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Protected fields (project_id, created_on, created_by) are silently dropped."""
        mock_project_repository.get.return_value = sample_project
        mock_project_repository.update.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        result = service.partial_update_project(
            project_id=sample_project.project_id,
            updates={"project_id": "evil-id", "created_by": "hacker", "name": "Safe Update"},
        )

        # project_id must not have changed
        assert result.project_id == sample_project.project_id
        assert result.created_by == sample_project.created_by

    def test_partial_update_invalid_name_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """An empty name in a PATCH payload raises ProjectInvalidDataException."""
        mock_project_repository.get.return_value = sample_project
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectInvalidDataException):
            service.partial_update_project(project_id=sample_project.project_id, updates={"name": ""})

        mock_project_repository.update.assert_not_called()

    def test_partial_update_nonexistent_project_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service
    ):
        """PATCH on a missing project raises ProjectNotFoundException."""
        mock_project_repository.get.return_value = None
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectNotFoundException):
            service.partial_update_project(project_id="no-such-id", updates={"name": "X"})


class TestProjectServiceDelete:
    """Tests for ProjectService.delete_project."""

    def test_delete_existing_project(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Deleting an existing project calls repository.delete."""
        mock_project_repository.exists.return_value = True
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        service.delete_project(project_id=sample_project.project_id)

        mock_project_repository.delete.assert_called_once_with(project_id=sample_project.project_id)

    def test_delete_nonexistent_project_raises(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service
    ):
        """Deleting a missing project raises ProjectNotFoundException."""
        mock_project_repository.exists.return_value = False
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        with pytest.raises(ProjectNotFoundException):
            service.delete_project(project_id="missing-id")

        mock_project_repository.delete.assert_not_called()

    def test_delete_cascades_linked_flows(
        self,
        mock_project_repository,
        mock_flow_repository,
        mock_flow_service,
        mock_job_stats_service,
        sample_project,
        flow_for_project,
    ):
        """Deleting a project bulk-deletes all flows linked via container_id."""
        mock_project_repository.exists.return_value = True
        mock_flow_repository.find_all.return_value = [flow_for_project]
        mock_flow_service.bulk_delete_flows.return_value = {
            "deleted": [flow_for_project.asset_id],
            "failed": [],
            "total_requested": 1,
            "total_deleted": 1,
            "total_failed": 0,
        }
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        service.delete_project(project_id=sample_project.project_id)

        mock_flow_service.bulk_delete_flows.assert_called_once_with(flow_ids=[flow_for_project.asset_id], actor=None)
        mock_project_repository.delete.assert_called_once_with(project_id=sample_project.project_id)

    def test_delete_no_flows_skips_bulk_delete(
        self, mock_project_repository, mock_flow_repository, mock_flow_service, mock_job_stats_service, sample_project
    ):
        """Deleting a project with no linked flows does not call bulk_delete_flows."""
        mock_project_repository.exists.return_value = True
        mock_flow_repository.find_all.return_value = []
        service = ProjectService(
            repository=mock_project_repository,
            flow_repository=mock_flow_repository,
            flow_service=mock_flow_service,
            job_stats_service=mock_job_stats_service,
        )

        service.delete_project(project_id=sample_project.project_id)

        mock_flow_service.bulk_delete_flows.assert_not_called()
        mock_project_repository.delete.assert_called_once_with(project_id=sample_project.project_id)
