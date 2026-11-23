# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Trust classes and AST descriptors: untrusted operator files are never executed by the discovery path."""

from collections.abc import Generator
from pathlib import Path

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory
from docpipe.core.orchestration.operator_factory import OperatorFactory
from docpipe.core.orchestration.operator_loader.adapters.filesystem_adapter import (
    FilesystemAdapter,
    classify_filesystem_path,
)
from docpipe.core.orchestration.operator_loader.loader_service import CustomOperatorLoader
from docpipe.core.orchestration.operator_loader.ports.operator_source import TrustClass
from docpipe.core.orchestration.operator_loader.untrusted_descriptor import (
    UntrustedOperatorDescriptor,
    build_untrusted_descriptor,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider

# Module-level side effects that an uploaded script could attempt. Each runs before anything else in the file.
CANARY_OPERATOR = """
import os
import urllib.request

open({marker!r}, "w").write("executed")
os.environ["D2_CANARY"] = "executed"
urllib.request.urlopen("http://127.0.0.1:9/never")

import pyarrow as pa
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory


class CanaryOp(AbstractOperator):
    short_name = "canary_op"
    category = OperatorCategory.Functional
    owner = DocpipeConstants.OWNER_CUSTOM

    def transform(self, table: pa.Table, file_name=None):
        return [table], {{"ran": True}}

    @staticmethod
    def get_metadata():
        return {{"label": "Canary", "secret_fields": ["api_key"]}}
"""

# Same file without the network call, so that importing it succeeds when execution is legitimate.
HARMLESS_CANARY_OPERATOR = CANARY_OPERATOR.replace('urllib.request.urlopen("http://127.0.0.1:9/never")', "")


class _Provider(SecretProvider):
    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        return "unused"

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_state(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    clear_providers()
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path / "data"))
    monkeypatch.delenv("D2_CANARY", raising=False)
    yield
    clear_providers()


@pytest.fixture
def upload_dir(*, tmp_path: Path) -> Path:
    """The directory the API stores uploaded operators in, derived from the data path like ``LocalFileStore``."""
    path = tmp_path / "data" / "custom_operators" / "op-1"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def marker(*, tmp_path: Path) -> Path:
    return tmp_path / "executed.marker"


def _write_canary(*, directory: Path, marker: Path, source: str = CANARY_OPERATOR) -> Path:
    path = directory / "canary_op.py"
    path.write_text(source.format(marker=str(marker)), encoding="utf-8")
    return path


def _assert_not_executed(*, marker: Path) -> None:
    import os

    assert not marker.exists()
    assert "D2_CANARY" not in os.environ


class TestTrustClassification:
    def test_upload_store_is_untrusted(self, *, upload_dir: Path) -> None:
        assert classify_filesystem_path(path=upload_dir) == TrustClass.UNTRUSTED
        assert FilesystemAdapter(str(upload_dir.parent)).trust_class == TrustClass.UNTRUSTED

    def test_other_filesystem_paths_are_deployer_installed(self, *, tmp_path: Path) -> None:
        deployer_dir = tmp_path / "deployer_ops"
        deployer_dir.mkdir()

        assert FilesystemAdapter(str(deployer_dir)).trust_class == TrustClass.DEPLOYER_INSTALLED

    def test_prefix_sibling_of_the_upload_store_is_not_untrusted(self, *, tmp_path: Path, upload_dir: Path) -> None:
        sibling = tmp_path / "data" / "custom_operators_extra"
        sibling.mkdir()

        assert classify_filesystem_path(path=sibling) == TrustClass.DEPLOYER_INSTALLED

    def test_explicit_trust_class_overrides_the_path_rule(self, *, tmp_path: Path) -> None:
        adapter = FilesystemAdapter(str(tmp_path), trust_class=TrustClass.UNTRUSTED)

        assert adapter.trust_class == TrustClass.UNTRUSTED


class TestUntrustedFilesAreNotExecuted:
    def test_listing_describes_the_file_without_executing_it(self, *, upload_dir: Path, marker: Path) -> None:
        _write_canary(directory=upload_dir, marker=marker)

        infos = FilesystemAdapter(str(upload_dir.parent)).list_operators()

        assert [(i.short_name, i.name, i.category, i.trust_class) for i in infos] == [
            ("canary_op", "CanaryOp", "Functional", TrustClass.UNTRUSTED)
        ]
        assert infos[0].static_metadata == {"label": "Canary", "secret_fields": ["api_key"]}
        _assert_not_executed(marker=marker)

    def test_adapter_refuses_to_import_untrusted_files(self, *, upload_dir: Path, marker: Path) -> None:
        path = _write_canary(directory=upload_dir, marker=marker)
        adapter = FilesystemAdapter(str(upload_dir.parent))
        info = adapter.list_operators()[0]

        with pytest.raises(PermissionError):
            adapter.load_operator(operator_info=info)
        with pytest.raises(PermissionError):
            adapter._load_module_from_file(file_path=path)
        _assert_not_executed(marker=marker)

    def test_loader_registers_a_descriptor_not_the_class(self, *, upload_dir: Path, marker: Path) -> None:
        _write_canary(directory=upload_dir, marker=marker)
        loader = CustomOperatorLoader.from_paths([str(upload_dir.parent)])

        loaded = loader.validate_and_load(builtin_operators={})

        descriptor = loaded["canary_op"]
        assert issubclass(descriptor, UntrustedOperatorDescriptor)
        assert issubclass(descriptor, AbstractOperator)
        assert descriptor.short_name == "canary_op"
        assert descriptor.category == OperatorCategory.Functional
        assert descriptor.owner == DocpipeConstants.OWNER_CUSTOM
        assert descriptor.trust_class == TrustClass.UNTRUSTED
        assert descriptor.get_metadata()["secret_fields"] == ["api_key"]
        assert descriptor.get_metadata()["label"] == "Canary"
        assert descriptor.is_available() is True
        assert descriptor.get_required_features() == []
        _assert_not_executed(marker=marker)

    def test_factory_refresh_does_not_execute_and_keeps_replacing_custom_entries(
        self, *, upload_dir: Path, marker: Path
    ) -> None:
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        assert "canary_op" not in factory.operators

        _write_canary(directory=upload_dir, marker=marker)
        factory.refresh_operators()

        assert "canary_op" in factory.operators
        _assert_not_executed(marker=marker)

        (upload_dir / "canary_op.py").unlink()
        factory.refresh_operators()

        assert "canary_op" not in factory.operators
        _assert_not_executed(marker=marker)

    def test_flow_validation_instantiation_does_not_execute(self, *, upload_dir: Path, marker: Path) -> None:
        _write_canary(directory=upload_dir, marker=marker)
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        descriptor = factory.operators["canary_op"]

        operator = descriptor(config={DocpipeConstants.VALIDATING_FLOW: True})
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])

        assert isinstance(operator, descriptor)
        assert errors == []
        _assert_not_executed(marker=marker)

    def test_s3_style_untrusted_adapter_outside_the_store_is_not_executed(
        self, *, tmp_path: Path, marker: Path
    ) -> None:
        cache = tmp_path / "s3cache"
        cache.mkdir()
        _write_canary(directory=cache, marker=marker)

        infos = FilesystemAdapter(str(cache), trust_class=TrustClass.UNTRUSTED).list_operators()

        assert [i.short_name for i in infos] == ["canary_op"]
        _assert_not_executed(marker=marker)

    def test_invalid_untrusted_file_is_skipped_without_executing_it(self, *, upload_dir: Path, marker: Path) -> None:
        (upload_dir / "bad.py").write_text(f"open({str(marker)!r}, 'w')\nclass NotAnOperator: ...\n", encoding="utf-8")

        assert FilesystemAdapter(str(upload_dir.parent)).list_operators() == []
        _assert_not_executed(marker=marker)


class TestDescriptorExecution:
    def test_execution_imports_the_real_class_only_when_a_node_is_constructed(
        self, *, upload_dir: Path, marker: Path
    ) -> None:
        _write_canary(directory=upload_dir, marker=marker, source=HARMLESS_CANARY_OPERATOR)
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        descriptor = factory.operators["canary_op"]
        assert not marker.exists()

        operator = descriptor(config={})

        assert marker.exists()
        assert type(operator).__name__ == "CanaryOp"
        assert not isinstance(operator, UntrustedOperatorDescriptor)

    def test_execution_is_refused_while_a_secret_provider_is_registered(
        self, *, upload_dir: Path, marker: Path
    ) -> None:
        _write_canary(directory=upload_dir, marker=marker, source=HARMLESS_CANARY_OPERATOR)
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        register_provider(name="hashicorp", provider=_Provider())

        with pytest.raises(DocpipeException, match="not permitted"):
            factory.operators["canary_op"](config={})

        assert not marker.exists()

    def test_validation_reports_not_permitted_while_a_secret_provider_is_registered(
        self, *, upload_dir: Path, marker: Path
    ) -> None:
        _write_canary(directory=upload_dir, marker=marker)
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        register_provider(name="hashicorp", provider=_Provider())

        operator = factory.operators["canary_op"](config={DocpipeConstants.VALIDATING_FLOW: True})
        errors: list[str] = []
        operator.validate(errors=errors, warnings=[], available_features=[])

        assert len(errors) == 1
        assert "not permitted" in errors[0]
        _assert_not_executed(marker=marker)

    def test_changed_file_that_no_longer_defines_the_operator_is_rejected_at_execution(
        self, *, upload_dir: Path, marker: Path
    ) -> None:
        path = _write_canary(directory=upload_dir, marker=marker, source=HARMLESS_CANARY_OPERATOR)
        factory = OperatorFactory("python", [str(upload_dir.parent)], enable_custom_operators=True)
        path.write_text("x = 1\n", encoding="utf-8")

        with pytest.raises(DocpipeException, match="no longer defines"):
            factory.operators["canary_op"](config={})

    def test_descriptors_do_not_share_state(self) -> None:
        from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo

        first = build_untrusted_descriptor(
            operator_info=OperatorInfo(
                name="A", short_name="a", module_path="a.py", category="Quality", source_location="x"
            )
        )
        second = build_untrusted_descriptor(
            operator_info=OperatorInfo(
                name="B", short_name="b", module_path="b.py", category="Extract", source_location="x"
            )
        )

        first.get_metadata()["label"] = "mutated"  # type: ignore[index]

        assert first.get_metadata()["label"] == "a"
        assert second.get_metadata()["label"] == "b"
        assert first.short_name == "a" and second.short_name == "b"


class TestDeployerInstalledStillExecutes:
    def test_filesystem_path_outside_the_upload_store_is_imported(self, *, tmp_path: Path, marker: Path) -> None:
        deployer_dir = tmp_path / "deployer_ops"
        deployer_dir.mkdir()
        _write_canary(directory=deployer_dir, marker=marker, source=HARMLESS_CANARY_OPERATOR)

        loaded = CustomOperatorLoader.from_paths([str(deployer_dir)]).validate_and_load(builtin_operators={})

        assert marker.exists()
        assert not issubclass(loaded["canary_op"], UntrustedOperatorDescriptor)
        assert loaded["canary_op"].__name__ == "CanaryOp"
