# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Route inventory: every ``/api/v1/*`` route needs a session dependency and a matrix entry.

The permission matrix below is the reviewed list of (method, path) pairs and the minimum
role each one requires. The inventory walks the real application's ``APIRoute`` entries and
fails when a route was added without the session dependency, without a matrix entry, or
with a role guard that differs from the matrix.
"""

import inspect
from collections.abc import Iterable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from docpipe.api.auth.dependencies import require_session
from docpipe.api.auth.guards import require_role
from docpipe.api.auth.roles import Role
from docpipe.api.main import app as real_app

API_PREFIX = "/api/v1/"

# FastAPI's built-in documentation endpoints are plain Starlette routes, not ``APIRoute``
# entries, so they carry no dependencies. They are public by design and exempt from the
# inventory. ``/docs/oauth2-redirect`` is the path FastAPI actually registers for the
# Swagger OAuth redirect; ``/api/v1/docs/oauth2-redirect`` is listed because the design
# names it.
EXEMPT_NON_API_ROUTE_PATHS = frozenset(
    {
        "/api/v1/docs",
        "/api/v1/redoc",
        "/api/v1/openapi.json",
        "/api/v1/docs/oauth2-redirect",
        "/docs/oauth2-redirect",
    }
)

_GUARD_QUALNAME = "require_role.<locals>._guard"

# (method, path) -> minimum role. ``viewer`` is the floor enforced by the router-level
# session dependency; ``editor`` and ``admin`` entries carry a ``require_role`` guard.
PERMISSION_MATRIX: dict[tuple[str, str], Role] = {
    # projects
    ("POST", "/api/v1/projects"): Role.EDITOR,
    ("GET", "/api/v1/projects"): Role.VIEWER,
    ("GET", "/api/v1/projects/{project_id}"): Role.VIEWER,
    ("PUT", "/api/v1/projects/{project_id}"): Role.EDITOR,
    ("PATCH", "/api/v1/projects/{project_id}"): Role.EDITOR,
    ("DELETE", "/api/v1/projects/{project_id}"): Role.EDITOR,
    ("GET", "/api/v1/projects/{project_id}/flows"): Role.VIEWER,
    # flows
    ("POST", "/api/v1/flows"): Role.EDITOR,
    ("GET", "/api/v1/flows"): Role.VIEWER,
    ("GET", "/api/v1/flows/{flow_id}"): Role.VIEWER,
    ("PUT", "/api/v1/flows/{flow_id}"): Role.EDITOR,
    ("PATCH", "/api/v1/flows/{flow_id}"): Role.EDITOR,
    ("DELETE", "/api/v1/flows/{flow_id}"): Role.EDITOR,
    ("DELETE", "/api/v1/flows"): Role.EDITOR,
    # event mappings
    ("POST", "/api/v1/event_mappings"): Role.EDITOR,
    ("GET", "/api/v1/event_mappings"): Role.VIEWER,
    ("GET", "/api/v1/event_mappings/{key}"): Role.VIEWER,
    ("PUT", "/api/v1/event_mappings/{key}"): Role.EDITOR,
    ("DELETE", "/api/v1/event_mappings/{key}"): Role.EDITOR,
    # document libraries
    ("POST", "/api/v1/document-libraries"): Role.EDITOR,
    ("GET", "/api/v1/document-libraries"): Role.VIEWER,
    ("GET", "/api/v1/document-libraries/{library_id}"): Role.VIEWER,
    ("PATCH", "/api/v1/document-libraries/{library_id}"): Role.EDITOR,
    ("DELETE", "/api/v1/document-libraries/{library_id}"): Role.EDITOR,
    ("GET", "/api/v1/document-libraries/{library_id}/document-sets"): Role.VIEWER,
    ("PUT", "/api/v1/document-libraries/{library_id}/document-sets"): Role.EDITOR,
    ("DELETE", "/api/v1/document-libraries/{library_id}/document-sets"): Role.EDITOR,
    # document sets
    ("POST", "/api/v1/document-sets"): Role.EDITOR,
    ("GET", "/api/v1/document-sets"): Role.VIEWER,
    ("GET", "/api/v1/document-sets/{document_set_id}"): Role.VIEWER,
    ("PATCH", "/api/v1/document-sets/{document_set_id}"): Role.EDITOR,
    ("DELETE", "/api/v1/document-sets/{document_set_id}"): Role.EDITOR,
    ("GET", "/api/v1/document-sets/{document_set_id}/preview"): Role.VIEWER,
    # documents
    ("GET", "/api/v1/documents/{document_id}"): Role.VIEWER,
    ("POST", "/api/v1/documents/search"): Role.VIEWER,
    # operators and custom operators
    ("GET", "/api/v1/operators/metadata"): Role.VIEWER,
    ("POST", "/api/v1/custom_operators"): Role.ADMIN,
    ("GET", "/api/v1/custom_operators"): Role.VIEWER,
    ("GET", "/api/v1/custom_operators/directory_tree"): Role.VIEWER,
    ("GET", "/api/v1/custom_operators/{operator_id}"): Role.VIEWER,
    ("PATCH", "/api/v1/custom_operators/{operator_id}"): Role.ADMIN,
    ("DELETE", "/api/v1/custom_operators/{operator_id}"): Role.ADMIN,
    # providers
    ("GET", "/api/v1/providers/{provider}/models"): Role.VIEWER,
    # job runs
    ("POST", "/api/v1/job_runs"): Role.EDITOR,
    ("GET", "/api/v1/job_runs"): Role.VIEWER,
    ("GET", "/api/v1/job_runs/{job_run_id}"): Role.VIEWER,
    ("POST", "/api/v1/job_runs/{job_run_id}/cancel"): Role.EDITOR,
    ("DELETE", "/api/v1/job_runs/{job_run_id}"): Role.EDITOR,
    ("GET", "/api/v1/job_runs/{job_run_id}/report"): Role.VIEWER,
    ("GET", "/api/v1/job_runs/{job_run_id}/flow_definition"): Role.VIEWER,
    # validation (read-only POSTs)
    ("POST", "/api/v1/validation/validate_flow"): Role.VIEWER,
    ("POST", "/api/v1/validation/enrich_flow_features"): Role.VIEWER,
    # document classes
    ("GET", "/api/v1/document_classes"): Role.VIEWER,
}


def _enforced_role(*, dependencies: Iterable[object]) -> Role:
    """Return the highest ``require_role`` minimum among ``dependencies`` (viewer if none)."""
    enforced = Role.VIEWER
    for dep in dependencies:
        call = getattr(dep, "dependency", None)
        if call is None or getattr(call, "__qualname__", "") != _GUARD_QUALNAME:
            continue
        minimum = inspect.getclosurevars(call).nonlocals["min_role"]
        enforced = max(enforced, minimum)
    return enforced


def collect_inventory_violations(
    *,
    routes: Iterable[object],
    matrix: dict[tuple[str, str], Role],
    prefix: str = API_PREFIX,
) -> list[str]:
    """Check every ``APIRoute`` under ``prefix`` against the session rule and the matrix.

    Args:
        routes: Application routes (``app.routes``).
        matrix: Reviewed (method, path) -> minimum role mapping.
        prefix: Path prefix whose routes must be guarded.

    Returns:
        One message per violation; empty when the inventory is clean.
    """
    violations: list[str] = []
    seen: set[tuple[str, str]] = set()
    for context in iter_route_contexts(list(routes)):  # type: ignore[arg-type]
        if not isinstance(context.original_route, APIRoute):
            continue
        path = context.path
        if not path or not path.startswith(prefix):
            continue
        has_session = any(dep.dependency is require_session for dep in context.dependencies)
        enforced = _enforced_role(dependencies=context.dependencies)
        for method in sorted(context.methods or ()):
            key = (method, path)
            seen.add(key)
            if not has_session:
                violations.append(f"{method} {path}: lacks the session dependency")
            if key not in matrix:
                violations.append(f"{method} {path}: has no permission matrix entry")
            elif matrix[key] != enforced:
                violations.append(
                    f"{method} {path}: matrix requires {matrix[key].value} but route enforces {enforced.value}"
                )
    violations.extend(f"{method} {path}: matrix entry has no route" for method, path in sorted(set(matrix) - seen))
    return violations


def test_every_api_route_has_session_dependency_and_matrix_entry():
    violations = collect_inventory_violations(routes=real_app.routes, matrix=PERMISSION_MATRIX)

    assert violations == []


def test_matrix_covers_all_three_roles_and_every_write_method():
    roles = set(PERMISSION_MATRIX.values())
    write_methods = {method for method, _ in PERMISSION_MATRIX if method != "GET"}

    assert roles == {Role.VIEWER, Role.EDITOR, Role.ADMIN}
    assert write_methods == {"POST", "PUT", "PATCH", "DELETE"}


def test_docs_endpoints_are_non_api_routes_and_the_only_ones_under_the_prefix():
    non_api_paths = {
        context.path
        for context in iter_route_contexts(real_app.routes)
        if not isinstance(context.original_route, APIRoute) and context.path
    }

    assert {"/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json", "/docs/oauth2-redirect"} <= non_api_paths
    under_prefix = {path for path in non_api_paths if path.startswith(API_PREFIX)}
    assert under_prefix <= EXEMPT_NON_API_ROUTE_PATHS


def test_no_api_route_exists_for_an_exempt_docs_path():
    api_paths = {
        context.path
        for context in iter_route_contexts(real_app.routes)
        if isinstance(context.original_route, APIRoute) and context.path
    }

    assert api_paths.isdisjoint(EXEMPT_NON_API_ROUTE_PATHS)


# --- The inventory can fail ------------------------------------------------------------


def _ok_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_session)])

    @router.get("/things")
    def list_things() -> list[str]:
        return []

    @router.post("/things", dependencies=[Depends(require_role(Role.EDITOR))])
    def create_thing() -> None:
        return None

    app.include_router(router)
    return app


_SMALL_MATRIX: dict[tuple[str, str], Role] = {
    ("GET", "/api/v1/things"): Role.VIEWER,
    ("POST", "/api/v1/things"): Role.EDITOR,
}


def test_inventory_passes_for_a_fully_guarded_small_app():
    assert collect_inventory_violations(routes=_ok_app().routes, matrix=_SMALL_MATRIX) == []


def test_inventory_reports_a_route_added_without_the_session_dependency():
    app = _ok_app()

    @app.get("/api/v1/unguarded")
    def unguarded() -> None:
        return None

    violations = collect_inventory_violations(
        routes=app.routes, matrix={**_SMALL_MATRIX, ("GET", "/api/v1/unguarded"): Role.VIEWER}
    )

    assert violations == ["GET /api/v1/unguarded: lacks the session dependency"]


def test_inventory_reports_a_route_added_without_a_matrix_entry():
    app = _ok_app()
    extra = APIRouter(prefix="/api/v1", dependencies=[Depends(require_session)])

    @extra.delete("/things/{thing_id}", dependencies=[Depends(require_role(Role.EDITOR))])
    def delete_thing(thing_id: str) -> None:
        return None

    app.include_router(extra)

    violations = collect_inventory_violations(routes=app.routes, matrix=_SMALL_MATRIX)

    assert violations == ["DELETE /api/v1/things/{thing_id}: has no permission matrix entry"]


def test_inventory_reports_a_role_guard_weaker_than_the_matrix():
    app = _ok_app()

    violations = collect_inventory_violations(
        routes=app.routes, matrix={**_SMALL_MATRIX, ("POST", "/api/v1/things"): Role.ADMIN}
    )

    assert violations == ["POST /api/v1/things: matrix requires admin but route enforces editor"]


def test_inventory_reports_a_matrix_entry_without_a_route():
    violations = collect_inventory_violations(
        routes=_ok_app().routes, matrix={**_SMALL_MATRIX, ("DELETE", "/api/v1/gone"): Role.EDITOR}
    )

    assert violations == ["DELETE /api/v1/gone: matrix entry has no route"]


def test_inventory_ignores_non_api_routes_and_paths_outside_the_prefix():
    app = _ok_app()

    @app.get("/health")
    def health() -> None:
        return None

    assert collect_inventory_violations(routes=app.routes, matrix=_SMALL_MATRIX) == []


def test_inventory_reports_a_route_added_to_a_router_without_the_session_dependency():
    app = _ok_app()
    bare = APIRouter(prefix="/api/v1")

    @bare.get("/bare")
    def bare_route() -> None:
        return None

    app.include_router(bare)

    violations = collect_inventory_violations(
        routes=app.routes, matrix={**_SMALL_MATRIX, ("GET", "/api/v1/bare"): Role.VIEWER}
    )

    assert violations == ["GET /api/v1/bare: lacks the session dependency"]
