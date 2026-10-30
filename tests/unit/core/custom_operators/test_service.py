"""Unit tests for CustomOperatorService."""

import uuid
from pathlib import Path

import pytest

from docpipe.core.constants.constants import DocpipeConstants, OrchestratorType
from docpipe.core.custom_operators.file_store import LocalFileStore
from docpipe.core.custom_operators.models import CustomOperator, CustomOperatorStatus
from docpipe.core.custom_operators.service import CUSTOM_OPERATORS_COLLECTION, CustomOperatorService
from docpipe.core.orchestration.operator_factory import OperatorFactoryProvider
from docpipe.exceptions.docpipe_exceptions import (
    CustomOperatorAlreadyExistsException,
    CustomOperatorInvalidDataException,
    CustomOperatorNotFoundException,
)
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage

SAMPLE_OP_CODE = """
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
import pyarrow as pa

class SampleCustomOperator(AbstractOperator):
    short_name = "sample_custom_op"
    category = OperatorCategory.Quality
    owner = "custom"

    def transform(self, table: pa.Table):
        return [table], {}

    @staticmethod
    def get_metadata():
        return {"short_name": "sample_custom_op"}
"""


@pytest.fixture
def custom_operator_service(tmp_path: Path) -> CustomOperatorService:
    """Fixture providing an isolated CustomOperatorService."""
    file_store = LocalFileStore(base_dir=tmp_path / "custom_operators")
    metadata_storage = KeyValueFileSystemStorage(base_dir=tmp_path)
    return CustomOperatorService(file_store=file_store, metadata_storage=metadata_storage)


class TestCustomOperatorServiceCreate:
    """Test suite for create_operator."""

    def test_create_operator_success(self, *, custom_operator_service: CustomOperatorService, tmp_path: Path) -> None:
        """Test creating a valid custom operator."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        operator = custom_operator_service.create_operator(
            name="Sample Custom Operator",
            description="A sample test operator",
            operator_file_path=op_file,
        )

        assert operator.id is not None
        assert operator.name == "Sample Custom Operator"
        assert operator.short_name == "sample_custom_op"
        assert operator.status == CustomOperatorStatus.VALIDATED
        assert operator.created_at is not None
        assert operator.metadata["category"] == "Quality"

    def test_create_operator_duplicate_short_name_raises_conflict(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Test duplicate short_name raises CustomOperatorAlreadyExistsException."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        custom_operator_service.create_operator(
            name="Op 1",
            description="First operator",
            operator_file_path=op_file,
        )

        with pytest.raises(CustomOperatorAlreadyExistsException, match="already exists"):
            custom_operator_service.create_operator(
                name="Op 2",
                description="Second operator with same short_name",
                operator_file_path=op_file,
            )

    def test_create_operator_empty_name_raises_exception(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Test empty name raises CustomOperatorInvalidDataException."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="Operator name cannot be empty"):
            custom_operator_service.create_operator(
                name="   ",
                description="desc",
                operator_file_path=op_file,
            )


class TestCustomOperatorServiceGetAndList:
    """Test suite for get_operator and list_operators."""

    def test_get_operator_by_id(self, *, custom_operator_service: CustomOperatorService, tmp_path: Path) -> None:
        """Test retrieving custom operator by valid UUID."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Sample Op",
            description="desc",
            operator_file_path=op_file,
        )
        assert created.id is not None

        retrieved = custom_operator_service.get_operator(operator_id=created.id)
        assert retrieved.id == created.id
        assert retrieved.short_name == created.short_name

    def test_get_operator_invalid_uuid_raises_exception(
        self, *, custom_operator_service: CustomOperatorService
    ) -> None:
        """Test malformed UUID raises CustomOperatorInvalidDataException."""
        with pytest.raises(CustomOperatorInvalidDataException, match="must be a valid UUID v4"):
            custom_operator_service.get_operator(operator_id="invalid-uuid-123")

    def test_get_operator_nonexistent_uuid_raises_not_found(
        self, *, custom_operator_service: CustomOperatorService
    ) -> None:
        """Test non-existent UUID raises CustomOperatorNotFoundException."""
        random_uuid = str(uuid.uuid4())
        with pytest.raises(CustomOperatorNotFoundException, match="not found"):
            custom_operator_service.get_operator(operator_id=random_uuid)

    def test_list_operators_marks_missing_file_as_invalid(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Test list_operators consistency check when operator file was deleted from disk."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Sample Op",
            description="desc",
            operator_file_path=op_file,
        )
        assert created.id is not None

        # Manually delete file directory from disk to simulate external deletion
        custom_operator_service.file_store.delete(operator_id=created.id)

        operators = custom_operator_service.list_operators()
        assert len(operators) == 1
        assert operators[0].status == CustomOperatorStatus.INVALID
        assert "not found on disk" in operators[0].message


class TestCustomOperatorServiceUpdate:
    """Test suite for update_operator."""

    def test_update_metadata_only(self, *, custom_operator_service: CustomOperatorService, tmp_path: Path) -> None:
        """Test updating name and description without replacing file."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Original Name",
            description="Original Desc",
            operator_file_path=op_file,
        )
        assert created.id is not None

        updated = custom_operator_service.update_operator(
            operator_id=created.id,
            name="Updated Name",
            description="Updated Desc",
        )
        assert updated.name == "Updated Name"
        assert updated.description == "Updated Desc"
        assert updated.short_name == created.short_name

    def test_update_with_file_replacement(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Test replacing operator file with same short_name."""
        op_file1 = tmp_path / "sample_op_v1.py"
        op_file1.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Original Name",
            description="Original Desc",
            operator_file_path=op_file1,
        )
        assert created.id is not None

        # Create updated file with same short_name
        op_file2 = tmp_path / "sample_op_v2.py"
        op_file2.write_text(SAMPLE_OP_CODE.replace("Quality", "Extract"), encoding="utf-8")

        updated = custom_operator_service.update_operator(
            operator_id=created.id,
            operator_file_path=op_file2,
        )
        assert updated.operator_file == "sample_op_v2.py"
        assert updated.metadata["category"] == "Extract"

    def test_update_file_with_different_short_name_raises_exception(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Test attempting to change short_name via update raises CustomOperatorInvalidDataException."""
        op_file1 = tmp_path / "sample_op_v1.py"
        op_file1.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Original Name",
            description="Original Desc",
            operator_file_path=op_file1,
        )
        assert created.id is not None

        # Create updated file with different short_name
        op_file2 = tmp_path / "sample_op_v2.py"
        op_file2.write_text(SAMPLE_OP_CODE.replace("sample_custom_op", "different_op"), encoding="utf-8")

        with pytest.raises(CustomOperatorInvalidDataException, match="Cannot change short_name"):
            custom_operator_service.update_operator(
                operator_id=created.id,
                operator_file_path=op_file2,
            )


class TestCustomOperatorServiceDelete:
    """Test suite for delete_operator."""

    def test_delete_operator_success(self, *, custom_operator_service: CustomOperatorService, tmp_path: Path) -> None:
        """Test deleting operator removes both metadata and files."""
        op_file = tmp_path / "sample_op.py"
        op_file.write_text(SAMPLE_OP_CODE, encoding="utf-8")

        created = custom_operator_service.create_operator(
            name="Op to Delete",
            description="desc",
            operator_file_path=op_file,
        )
        assert created.id is not None

        custom_operator_service.delete_operator(operator_id=created.id)

        with pytest.raises(CustomOperatorNotFoundException):
            custom_operator_service.get_operator(operator_id=created.id)

        assert custom_operator_service.file_store.get_operator_dir(operator_id=created.id) is None


class _RecordingOperatorFactory:
    """Stand-in for the cached runtime OperatorFactory that records refresh calls."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.refresh_calls = 0
        self.error = error

    def refresh_operators(self) -> None:
        """Record the call and optionally fail like a broken custom operator package would."""
        self.refresh_calls += 1
        if self.error is not None:
            raise self.error


def _install_operator_factory(
    *, monkeypatch: pytest.MonkeyPatch, factory: _RecordingOperatorFactory
) -> list[dict[str, object]]:
    """Make OperatorFactoryProvider hand out factory and return the recorded lookup kwargs."""
    lookups: list[dict[str, object]] = []

    def get_operator_factory(**kwargs: object) -> _RecordingOperatorFactory:
        lookups.append(kwargs)
        return factory

    monkeypatch.setattr(OperatorFactoryProvider, "get_operator_factory", staticmethod(get_operator_factory))
    return lookups


def _create_sample_operator(
    *, service: CustomOperatorService, directory: Path, code: str = SAMPLE_OP_CODE, filename: str = "sample_op.py"
) -> CustomOperator:
    """Create an operator from code written to directory and return it."""
    op_file = directory / filename
    op_file.write_text(code, encoding="utf-8")
    return service.create_operator(name="Sample Op", description="desc", operator_file_path=op_file)


class TestCustomOperatorServiceDefaults:
    """Test suite for the default storage wiring."""

    def test_default_storages_live_under_data_path(self, *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Without injected storages, files and metadata are kept below DOCPIPE_DATA_PATH."""
        monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path))
        service = CustomOperatorService()

        created = _create_sample_operator(service=service, directory=tmp_path)

        assert created.id is not None
        assert (tmp_path / "custom_operators" / created.id / "sample_op.py").is_file()
        assert (tmp_path / CUSTOM_OPERATORS_COLLECTION / f"{created.id}.json").is_file()
        assert service.get_operator(operator_id=created.id).status == CustomOperatorStatus.VALIDATED


class TestCustomOperatorServiceIdValidation:
    """Test suite for operator_id format validation."""

    @pytest.mark.parametrize(
        "operator_id",
        [
            "7c9e6679-7425-40de-944b-e07fc1f90ae7".replace("-", ""),
            "urn:uuid:7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "{7c9e6679-7425-40de-944b-e07fc1f90ae7}",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ],
    )
    def test_non_canonical_or_non_v4_uuid_is_rejected(
        self, *, custom_operator_service: CustomOperatorService, operator_id: str
    ) -> None:
        """Only the canonical hyphenated form of a version 4 UUID is accepted as operator_id."""
        with pytest.raises(CustomOperatorInvalidDataException, match="must be a valid UUID v4") as exc_info:
            custom_operator_service.get_operator(operator_id=operator_id)

        assert exc_info.value.field_name == "operator_id"

    def test_delete_rejects_invalid_uuid(self, *, custom_operator_service: CustomOperatorService) -> None:
        """delete_operator validates the id before touching any storage."""
        with pytest.raises(CustomOperatorInvalidDataException, match="must be a valid UUID v4"):
            custom_operator_service.delete_operator(operator_id="../custom_operators")


class TestCustomOperatorServiceFactoryRefresh:
    """Test suite for refreshing the runtime operator factory."""

    def test_create_update_delete_refresh_python_operator_factory(
        self, *, custom_operator_service: CustomOperatorService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Every file-changing operation refreshes the cached python operator factory once."""
        factory = _RecordingOperatorFactory()
        lookups = _install_operator_factory(monkeypatch=monkeypatch, factory=factory)

        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        assert created.id is not None
        assert factory.refresh_calls == 1

        custom_operator_service.update_operator(operator_id=created.id, name="Renamed")
        assert factory.refresh_calls == 1

        replacement = tmp_path / "sample_op_v2.py"
        replacement.write_text(SAMPLE_OP_CODE, encoding="utf-8")
        custom_operator_service.update_operator(operator_id=created.id, operator_file_path=replacement)
        assert factory.refresh_calls == 2

        custom_operator_service.delete_operator(operator_id=created.id)
        assert factory.refresh_calls == 3
        assert lookups == [{"orchestrator": OrchestratorType.PYTHON}] * 3

    def test_create_succeeds_when_factory_refresh_fails(
        self, *, custom_operator_service: CustomOperatorService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A failing factory refresh is logged and does not undo or fail the stored operator."""
        factory = _RecordingOperatorFactory(error=ImportError("broken custom operator package"))
        _install_operator_factory(monkeypatch=monkeypatch, factory=factory)

        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)

        assert factory.refresh_calls == 1
        assert created.id is not None
        stored = custom_operator_service.get_operator(operator_id=created.id)
        assert stored.status == CustomOperatorStatus.VALIDATED
        assert stored.short_name == "sample_custom_op"


class TestCustomOperatorServiceConsistency:
    """Test suite for collision checks and disk consistency of stored operators."""

    def test_create_operators_with_distinct_short_names(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """Operators with different short_names coexist and are all listed."""
        first = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        second = _create_sample_operator(
            service=custom_operator_service,
            directory=tmp_path,
            code=SAMPLE_OP_CODE.replace("sample_custom_op", "second_custom_op"),
            filename="second_op.py",
        )

        listed = {op.id: op.short_name for op in custom_operator_service.list_operators()}

        assert listed == {first.id: "sample_custom_op", second.id: "second_custom_op"}

    def test_get_operator_marks_missing_directory_as_invalid(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """An operator whose storage directory vanished is reported INVALID."""
        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        assert created.id is not None
        custom_operator_service.file_store.delete(operator_id=created.id)

        operator = custom_operator_service.get_operator(operator_id=created.id)

        assert operator.status == CustomOperatorStatus.INVALID
        assert operator.message == "operator file not found on disk"

    def test_get_operator_marks_missing_file_as_invalid(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """An operator whose directory exists but whose script file is gone is reported INVALID."""
        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        assert created.id is not None
        op_dir = custom_operator_service.file_store.get_operator_dir(operator_id=created.id)
        assert op_dir is not None
        (op_dir / created.operator_file).unlink()

        operator = custom_operator_service.get_operator(operator_id=created.id)

        assert operator.status == CustomOperatorStatus.INVALID
        assert operator.message == "operator file not found on disk"

    def test_list_operators_skips_unparseable_record(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """A stored record that cannot be turned into a model is skipped; valid operators are still listed."""
        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        broken_id = str(uuid.uuid4())
        custom_operator_service.metadata_storage.save_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=broken_id,
            data={"id": broken_id, "name": "Broken", "short_name": "broken", "created_at": "not-a-timestamp"},
        )

        operators = custom_operator_service.list_operators()

        assert [op.id for op in operators] == [created.id]

    def test_update_metadata_only_requires_operator_directory(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """A metadata-only update of an operator without storage directory fails and keeps the record."""
        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)
        assert created.id is not None
        custom_operator_service.file_store.delete(operator_id=created.id)

        with pytest.raises(CustomOperatorNotFoundException, match=r"directory .* not found on disk"):
            custom_operator_service.update_operator(operator_id=created.id, name="Renamed")

        record = custom_operator_service.metadata_storage.get_record(
            collection=CUSTOM_OPERATORS_COLLECTION, key=created.id
        )
        assert record is not None
        assert record["name"] == "Sample Op"


class TestCustomOperatorServiceDeleteAndTree:
    """Test suite for deleting unknown operators and the directory tree."""

    def test_delete_unknown_operator_raises_not_found(self, *, custom_operator_service: CustomOperatorService) -> None:
        """Deleting an id without metadata record raises CustomOperatorNotFoundException."""
        unknown_id = str(uuid.uuid4())

        with pytest.raises(CustomOperatorNotFoundException, match="not found") as exc_info:
            custom_operator_service.delete_operator(operator_id=unknown_id)

        assert exc_info.value.operator_id == unknown_id

    def test_get_directory_tree_lists_stored_operator_file(
        self, *, custom_operator_service: CustomOperatorService, tmp_path: Path
    ) -> None:
        """The directory tree shows each operator directory with its stored script."""
        created = _create_sample_operator(service=custom_operator_service, directory=tmp_path)

        tree = custom_operator_service.get_directory_tree()

        assert tree["name"] == "custom_operators"
        op_dir = next(child for child in tree["children"] if child["name"] == created.id)
        assert op_dir["type"] == "directory"
        source_size = (tmp_path / "sample_op.py").stat().st_size
        assert op_dir["children"] == [{"name": "sample_op.py", "type": "file", "size": source_size}]
