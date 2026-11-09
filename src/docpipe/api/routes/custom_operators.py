# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Custom operator API endpoints."""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi import (
    Path as PathParam,
)

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.guards import require_role
from docpipe.api.auth.roles import Role
from docpipe.api.dependencies import get_custom_operator_service
from docpipe.api.dto.custom_operator_dto import (
    CustomOperatorDeleteResponse,
    CustomOperatorListResponse,
    CustomOperatorResponse,
    DirectoryTreeResponse,
    FileUploadResponse,
)
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    DESCRIPTION_MAX_LENGTH,
    DESCRIPTION_MIN_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    OPERATOR_FILE_MAX_LENGTH,
    UUID_EXAMPLE,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.core.custom_operators.service import CustomOperatorService
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

MAX_OPERATOR_FILE_BYTES = 512 * 1024  # 512 KB limit

# Configure router
# Every route requires a valid bearer token. Uploaded scripts are executable code, and the
# read routes disclose the script inventory and on-disk layout.
custom_operators_router = APIRouter(
    prefix="/custom_operators",
    tags=["Custom Operators"],
    dependencies=[Depends(get_current_user)],
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Invalid input data or validation failure",
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Custom operator not found"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Custom operator conflict"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "Internal server error"},
    },
)

# Parameter Type Annotations
OperatorIdPath = Annotated[
    str,
    PathParam(
        description="Unique identifier for the custom operator (UUID v4)",
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
        examples=[UUID_EXAMPLE],
    ),
]

OperatorNameForm = Annotated[
    str,
    Form(
        description="Human-readable name of the custom operator",
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        examples=["Custom Invoice Extractor"],
    ),
]

OperatorDescriptionForm = Annotated[
    str,
    Form(
        description="Description of the custom operator",
        min_length=DESCRIPTION_MIN_LENGTH,
        max_length=DESCRIPTION_MAX_LENGTH,
        examples=["Custom operator for extracting fields from financial invoices"],
    ),
]

OperatorFileForm = Annotated[
    UploadFile,
    File(
        description="Python operator script file (.py)",
    ),
]

OptionalOperatorNameForm = Annotated[
    str | None,
    Form(
        description="Updated human-readable name of the custom operator",
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        examples=["Custom Invoice Extractor"],
    ),
]

OptionalOperatorDescriptionForm = Annotated[
    str | None,
    Form(
        description="Updated description of the custom operator",
        min_length=DESCRIPTION_MIN_LENGTH,
        max_length=DESCRIPTION_MAX_LENGTH,
        examples=["Custom operator for extracting fields from financial invoices"],
    ),
]

OptionalOperatorFileForm = Annotated[
    UploadFile | None,
    File(
        description="Optional replacement Python operator script file (.py)",
    ),
]


@custom_operators_router.post(
    "",
    dependencies=[Depends(require_role(Role.ADMIN))],
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom operator",
    description="Upload a Python operator script, validate it statically, and store it in the custom operator catalog.",
    responses={
        status.HTTP_201_CREATED: {
            "model": FileUploadResponse,
            "description": "Custom operator created successfully",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Invalid filename, syntax, or operator contract violation",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "Custom operator with the same short_name already exists, or custom operators are disabled "
                "(DOCPIPE_ENABLE_CUSTOM_OPERATORS)"
            ),
        },
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Operator file exceeds the 512 KB size limit",
        },
    },
)
async def create_custom_operator(
    *,
    name: OperatorNameForm,
    description: OperatorDescriptionForm = "",
    operator_file: OperatorFileForm,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> FileUploadResponse:
    """Upload and create a new custom operator."""
    filename = Path(operator_file.filename or "").name
    if not filename or "\x00" in filename or len(filename) > OPERATOR_FILE_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid operator filename",
        )
    if not filename.endswith(".py"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator file must have a .py extension",
        )

    content = await operator_file.read()
    if len(content) > MAX_OPERATOR_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Operator file exceeds the maximum allowed size of {MAX_OPERATOR_FILE_BYTES // 1024} KB",
        )

    with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)

    try:
        created = service.create_operator(
            name=name,
            description=description,
            operator_file_path=tmp_path,
            original_filename=filename,
        )
        logger.info("Created custom operator %s (short_name=%s)", created.id, created.short_name)
        return FileUploadResponse(
            success=True,
            operator_id=created.id or "",
            message="Custom operator created successfully",
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@custom_operators_router.get(
    "",
    response_model=CustomOperatorListResponse,
    status_code=status.HTTP_200_OK,
    summary="List custom operators",
    description="Retrieve all custom operators registered in the catalog.",
    responses={
        status.HTTP_200_OK: {
            "model": CustomOperatorListResponse,
            "description": "List of custom operators retrieved successfully",
        },
    },
)
def list_custom_operators(
    *,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> CustomOperatorListResponse:
    """List all custom operators."""
    operators = service.list_operators()
    operator_dtos = [CustomOperatorResponse.model_validate(op.to_dict()) for op in operators]
    return CustomOperatorListResponse(
        operators=operator_dtos,
        count=len(operator_dtos),
    )


@custom_operators_router.get(
    "/directory_tree",
    response_model=DirectoryTreeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get directory tree",
    description="Retrieve a nested directory tree representation of custom operator files on disk.",
    responses={
        status.HTTP_200_OK: {
            "model": DirectoryTreeResponse,
            "description": "Directory tree retrieved successfully",
        },
    },
)
def get_directory_tree(
    *,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> DirectoryTreeResponse:
    """Return directory tree structure of stored custom operators."""
    tree = service.get_directory_tree()
    return DirectoryTreeResponse(directory_tree=tree)


@custom_operators_router.get(
    "/{operator_id}",
    response_model=CustomOperatorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get custom operator",
    description="Retrieve a single custom operator by its UUID.",
    responses={
        status.HTTP_200_OK: {
            "model": CustomOperatorResponse,
            "description": "Custom operator retrieved successfully",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Custom operator not found",
        },
    },
)
def get_custom_operator(
    *,
    operator_id: OperatorIdPath,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> CustomOperatorResponse:
    """Get custom operator by UUID."""
    operator = service.get_operator(operator_id=operator_id)
    return CustomOperatorResponse.model_validate(operator.to_dict())


@custom_operators_router.patch(
    "/{operator_id}",
    dependencies=[Depends(require_role(Role.ADMIN))],
    response_model=FileUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Update custom operator",
    description="Update metadata or replace the Python script file for an existing custom operator.",
    responses={
        status.HTTP_200_OK: {
            "model": FileUploadResponse,
            "description": "Custom operator updated successfully",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "Invalid input data, invalid script, or attempt to change short_name",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Custom operator not found",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "A replacement file was sent while custom operators are disabled",
        },
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Replacement operator file exceeds the 512 KB size limit",
        },
    },
)
async def update_custom_operator(
    *,
    operator_id: OperatorIdPath,
    name: OptionalOperatorNameForm = None,
    description: OptionalOperatorDescriptionForm = None,
    operator_file: OptionalOperatorFileForm = None,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> FileUploadResponse:
    """Update custom operator metadata or script file."""
    tmp_path: Path | None = None
    if operator_file is not None and operator_file.filename:
        filename = Path(operator_file.filename).name
        if not filename or "\x00" in filename or len(filename) > OPERATOR_FILE_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid operator filename",
            )
        if not filename.endswith(".py"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Operator file must have a .py extension",
            )

        content = await operator_file.read()
        if len(content) > MAX_OPERATOR_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Operator file exceeds the maximum allowed size of {MAX_OPERATOR_FILE_BYTES // 1024} KB",
            )

        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

    try:
        updated = service.update_operator(
            operator_id=operator_id,
            name=name,
            description=description,
            operator_file_path=tmp_path,
            original_filename=Path(operator_file.filename).name if operator_file and operator_file.filename else None,
        )
        logger.info("Updated custom operator %s", operator_id)
        return FileUploadResponse(
            success=True,
            operator_id=updated.id or operator_id,
            message="Custom operator updated successfully",
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


@custom_operators_router.delete(
    "/{operator_id}",
    dependencies=[Depends(require_role(Role.ADMIN))],
    response_model=CustomOperatorDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete custom operator",
    description="Delete a custom operator and its stored files from disk.",
    responses={
        status.HTTP_200_OK: {
            "model": CustomOperatorDeleteResponse,
            "description": "Custom operator deleted successfully",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Custom operator not found",
        },
    },
)
def delete_custom_operator(
    *,
    operator_id: OperatorIdPath,
    service: Annotated[CustomOperatorService, Depends(get_custom_operator_service)],
) -> CustomOperatorDeleteResponse:
    """Delete custom operator by UUID."""
    service.delete_operator(operator_id=operator_id)
    logger.info("Deleted custom operator %s", operator_id)
    return CustomOperatorDeleteResponse(
        success=True,
        operator_id=operator_id,
        message="Custom operator deleted successfully",
    )
