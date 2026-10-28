"""Unit tests for Custom Operator API routes."""

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.dependencies import get_custom_operator_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.custom_operators import custom_operators_router
from docpipe.core.custom_operators.models import CustomOperator, CustomOperatorStatus
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.exceptions.docpipe_exceptions import (
    CustomOperatorAlreadyExistsException,
    CustomOperatorNotFoundException,
    DocpipeException,
)


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock CustomOperatorService."""
    return MagicMock(spec=CustomOperatorService)


@pytest.fixture
def app(mock_service: MagicMock) -> FastAPI:
    """Create a FastAPI application with custom operators router and exception handlers."""
    test_app = FastAPI()
    test_app.include_router(custom_operators_router)
    test_app.dependency_overrides[get_custom_operator_service] = lambda: mock_service

    test_app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    test_app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    test_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    test_app.add_exception_handler(Exception, generic_exception_handler)

    return test_app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a TestClient with dependency overrides."""
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


class TestCreateCustomOperatorEndpoint:
    """Test suite for POST /custom_operators."""

    def test_create_custom_operator_success(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test uploading a valid custom operator returns 201."""
        op_id = str(uuid.uuid4())
        mock_service.create_operator.return_value = CustomOperator(
            id=op_id,
            name="My Custom Op",
            description="desc",
            short_name="my_custom_op",
            status=CustomOperatorStatus.VALIDATED,
            message="Valid",
            operator_file="my_custom_op.py",
        )

        file_content = b"# valid python code"
        response = client.post(
            "/custom_operators",
            data={"name": "My Custom Op", "description": "desc"},
            files={"operator_file": ("my_custom_op.py", io.BytesIO(file_content), "text/x-python")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["operator_id"] == op_id

    def test_create_custom_operator_invalid_extension_returns_400(self, *, client: TestClient) -> None:
        """Test uploading a non-.py file returns 400."""
        response = client.post(
            "/custom_operators",
            data={"name": "My Custom Op"},
            files={"operator_file": ("my_custom_op.txt", io.BytesIO(b"not py"), "text/plain")},
        )
        assert response.status_code == 400

    def test_create_custom_operator_already_exists_returns_409(
        self, *, client: TestClient, mock_service: MagicMock
    ) -> None:
        """Test duplicate short_name returns 409 Conflict."""
        mock_service.create_operator.side_effect = CustomOperatorAlreadyExistsException(
            message="Operator already exists",
            short_name="dup_op",
        )

        response = client.post(
            "/custom_operators",
            data={"name": "Dup Op"},
            files={"operator_file": ("dup_op.py", io.BytesIO(b"# code"), "text/x-python")},
        )
        assert response.status_code == 409


class TestGetAndListCustomOperatorEndpoints:
    """Test suite for GET /custom_operators and GET /custom_operators/{id}."""

    def test_list_custom_operators_returns_200(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test listing custom operators returns 200 with count."""
        op_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        mock_service.list_operators.return_value = [
            CustomOperator(
                id=op_id,
                name="Op 1",
                description="desc 1",
                short_name="op_1",
                status=CustomOperatorStatus.VALIDATED,
                message="Valid",
                operator_file="op_1.py",
                created_at=now,
                updated_at=now,
            )
        ]

        response = client.get("/custom_operators")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["operators"]) == 1
        assert data["operators"][0]["id"] == op_id

    def test_get_custom_operator_by_id_returns_200(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test retrieving custom operator by ID returns 200."""
        op_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        mock_service.get_operator.return_value = CustomOperator(
            id=op_id,
            name="Op 1",
            description="desc 1",
            short_name="op_1",
            status=CustomOperatorStatus.VALIDATED,
            message="Valid",
            operator_file="op_1.py",
            created_at=now,
            updated_at=now,
        )

        response = client.get(f"/custom_operators/{op_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == op_id
        assert data["short_name"] == "op_1"

    def test_get_custom_operator_not_found_returns_404(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test retrieving missing operator returns 404."""
        op_id = str(uuid.uuid4())
        mock_service.get_operator.side_effect = CustomOperatorNotFoundException(message="Not found", operator_id=op_id)

        response = client.get(f"/custom_operators/{op_id}")
        assert response.status_code == 404

    def test_get_directory_tree_returns_200(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test GET /custom_operators/directory_tree returns 200."""
        mock_service.get_directory_tree.return_value = {
            "name": "custom_operators",
            "type": "directory",
            "children": [],
        }

        response = client.get("/custom_operators/directory_tree")
        assert response.status_code == 200
        data = response.json()
        assert "directory_tree" in data
        assert data["directory_tree"]["name"] == "custom_operators"


class TestUpdateAndDeleteCustomOperatorEndpoints:
    """Test suite for PATCH and DELETE /custom_operators/{id}."""

    def test_update_custom_operator_returns_200(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test PATCH /custom_operators/{id} returns 200."""
        op_id = str(uuid.uuid4())
        mock_service.update_operator.return_value = CustomOperator(
            id=op_id,
            name="Updated Name",
            description="Updated Desc",
            short_name="op_1",
            status=CustomOperatorStatus.VALIDATED,
            message="Updated",
            operator_file="op_1.py",
        )

        response = client.patch(
            f"/custom_operators/{op_id}",
            data={"name": "Updated Name"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["operator_id"] == op_id

    def test_delete_custom_operator_returns_200(self, *, client: TestClient, mock_service: MagicMock) -> None:
        """Test DELETE /custom_operators/{id} returns 200."""
        op_id = str(uuid.uuid4())
        mock_service.delete_operator.return_value = None

        response = client.delete(f"/custom_operators/{op_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["operator_id"] == op_id


class TestOperatorFileValidation:
    """Filename, extension and size limits on create and update, and temp-file handling on update."""

    @pytest.mark.parametrize(
        ("filename", "content", "status_code", "detail"),
        [
            ("a" * 253 + ".py", b"# code", 400, "Invalid operator filename"),
            ("big_op.py", b"#" * (512 * 1024 + 1), 413, "maximum allowed size of 512 KB"),
        ],
        ids=["name-too-long", "too-large"],
    )
    def test_create_rejects_invalid_files(
        self,
        *,
        client: TestClient,
        mock_service: MagicMock,
        filename: str,
        content: bytes,
        status_code: int,
        detail: str,
    ) -> None:
        response = client.post(
            "/custom_operators",
            data={"name": "Op"},
            files={"operator_file": (filename, io.BytesIO(content), "text/x-python")},
        )

        assert response.status_code == status_code
        assert detail in response.text
        mock_service.create_operator.assert_not_called()

    @pytest.mark.parametrize(
        ("filename", "content", "status_code", "detail"),
        [
            ("a" * 253 + ".py", b"# code", 400, "Invalid operator filename"),
            ("op.txt", b"# code", 400, "must have a .py extension"),
            ("big_op.py", b"#" * (512 * 1024 + 1), 413, "maximum allowed size of 512 KB"),
        ],
        ids=["name-too-long", "not-python", "too-large"],
    )
    def test_update_rejects_invalid_files(
        self,
        *,
        client: TestClient,
        mock_service: MagicMock,
        filename: str,
        content: bytes,
        status_code: int,
        detail: str,
    ) -> None:
        response = client.patch(
            f"/custom_operators/{uuid.uuid4()}",
            files={"operator_file": (filename, io.BytesIO(content), "text/x-python")},
        )

        assert response.status_code == status_code
        assert detail in response.text
        mock_service.update_operator.assert_not_called()

    def test_update_with_file_passes_temp_copy_and_removes_it(
        self, *, client: TestClient, mock_service: MagicMock
    ) -> None:
        op_id = str(uuid.uuid4())
        seen: dict[str, Any] = {}

        def _update(**kwargs: Any) -> CustomOperator:
            path: Path = kwargs["operator_file_path"]
            seen.update(kwargs, exists=path.exists(), content=path.read_bytes())
            return CustomOperator(
                id=op_id,
                name="Op",
                description="",
                short_name="op",
                status=CustomOperatorStatus.VALIDATED,
                message="Updated",
                operator_file="new_op.py",
            )

        mock_service.update_operator.side_effect = _update

        response = client.patch(
            f"/custom_operators/{op_id}",
            files={"operator_file": ("new_op.py", io.BytesIO(b"class NewOp: ...\n"), "text/x-python")},
        )

        assert response.status_code == 200
        assert (seen["exists"], seen["content"], seen["original_filename"]) == (
            True,
            b"class NewOp: ...\n",
            "new_op.py",
        )
        assert not seen["operator_file_path"].exists()
