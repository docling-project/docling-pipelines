# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""LocalProjectRepository — filesystem-based project persistence adapter.

Stores each project as a single JSON file under the configured base directory:
    <base_dir>/{project_id}.json

Default base directory: ~/Documents/pipeline/projects

Implements the ProjectRepository port for the projects bounded context.
This adapter is used when DOCPIPE_STORAGE_BACKEND is not set or is set to
the default local filesystem mode. Swap it for a different adapter
(e.g. PostgresProjectRepository) without touching any application or domain code.

File writes are protected by a per-project lock to prevent data corruption
under concurrent API requests.
"""

import json
from pathlib import Path

import portalocker

from docpipe.core.projects.domain.models.project import Project
from docpipe.core.projects.domain.ports.project_repository import ProjectRepository
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_DEFAULT_PROJECTS_PATH = Path.home() / "Documents" / "pipeline" / "projects"


class LocalProjectRepository(ProjectRepository):
    """Concrete ProjectRepository that persists projects as JSON files.

    Each project is stored as a single file named {project_id}.json in the
    base directory. Operations on different projects are independent — only
    the specific file for a given project_id is read or written per call.

    Args:
        base_dir: Directory in which to store project JSON files.
            Defaults to ~/Documents/pipeline/projects. Override via the
            DOCPIPE_CONFIG_PATH YAML (projects.base_dir) or the
            DOCPIPE_PROJECTS_BASE_DIR environment variable.
    """

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_PROJECTS_PATH
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("LocalProjectRepository initialised at %s", self._base_dir)

    # ── Helpers ──────────────────────────────────────────────────────

    def _file_path(self, project_id: str) -> Path:
        return self._base_dir / f"{project_id}.json"

    def _lock_path(self, project_id: str) -> str:
        return str(self._file_path(project_id)) + ".lock"

    # ── ProjectRepository interface ───────────────────────────────────

    def save(self, *, project: Project) -> Project:
        """Write project to disk as JSON. Acquires a file-level lock."""
        path = self._file_path(project.project_id)
        with portalocker.Lock(
            self._lock_path(project.project_id),
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            timeout=30.0,
        ):
            path.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
        logger.info("Saved project %s (%s)", project.project_id, project.name)
        return project

    def get(self, *, project_id: str) -> Project | None:
        """Read a project from disk by ID."""
        path = self._file_path(project_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Project.from_dict(data=data)
        except Exception as exc:
            logger.warning("Failed to load project %s: %s", project_id, exc)
            return None

    def find_all(self) -> list[Project]:
        """Load all project JSON files from the storage directory."""
        projects: list[Project] = []
        for path in self._base_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                projects.append(Project.from_dict(data=data))
            except Exception as exc:
                logger.warning("Skipping unreadable project file %s: %s", path, exc)
        return projects

    def update(self, *, project: Project) -> Project:
        """Overwrite an existing project file."""
        return self.save(project=project)

    def delete(self, *, project_id: str) -> bool:
        """Delete a project file. Returns False if it does not exist."""
        path = self._file_path(project_id)
        if not path.exists():
            return False
        path.unlink()
        # Remove stale lock file if present
        lock = Path(self._lock_path(project_id))
        if lock.exists():
            lock.unlink(missing_ok=True)
        logger.info("Deleted project %s", project_id)
        return True

    def exists(self, *, project_id: str) -> bool:
        """Return True if a JSON file exists for the given project_id."""
        return self._file_path(project_id).exists()

    def exists_by_name(self, *, name: str) -> bool:
        """Scan all projects and return True if any has the given name."""
        return any(p.name == name for p in self.find_all())
