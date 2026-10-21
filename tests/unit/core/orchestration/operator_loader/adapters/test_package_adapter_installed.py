"""PackageAdapter tests against a real package "installed" into a temporary sys.path entry.

The package directory and its .dist-info (version + docpipe.operators entry points) live in
tmp_path, so importlib.metadata discovers it exactly like an installed distribution.
"""

import importlib
import importlib.metadata
import sys
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from docpipe.core.orchestration.operator_loader.adapters.package_adapter import PackageAdapter
from docpipe.core.orchestration.operator_loader.loader_service import CustomOperatorLoader
from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo

_OPERATOR = '''

class {name}(AbstractOperator):
    """{name} from the installed package."""

    short_name: str = "{short_name}"
    category: OperatorCategory = OperatorCategory.Functional
    owner: str = "custom"

    def transform(self, table, file_name=None):
        return [table], {{}}
'''
_NAMELESS = '''

class NamelessOp(AbstractOperator):
    """Declares no short_name, so discovery skips it."""

    def transform(self, table, file_name=None):
        return [table], {}
'''
_HEADER = "from docpipe.core.operators.abstract_operator import AbstractOperator, OperatorCategory\n"


def _install(site: Path, package: str, *, entry_points: str, with_operators_module: bool = True) -> None:
    pkg = site / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    if with_operators_module:
        (pkg / "operators.py").write_text(
            _HEADER
            + _OPERATOR.format(name="ModuleOp", short_name="module_op")
            + _OPERATOR.format(name="SharedOp", short_name="shared_op")
            + _NAMELESS
        )
    (pkg / "extra.py").write_text(
        _HEADER + _OPERATOR.format(name="ExtraOp", short_name="extra_op") + "\nNOT_AN_OPERATOR = 42\n"
    )
    dist = site / f"{package}-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text(entry_points.format(package=package))


_ENTRY_POINTS = """[docpipe.operators]
extra = {package}.extra:ExtraOp
shared = {package}.operators:SharedOp
extra_again = {package}.extra:ExtraOp
nameless = {package}.operators:NamelessOp
not_an_operator = {package}.extra:NOT_AN_OPERATOR
broken = {package}.missing:Nope
foreign = some_other_package.ops:ForeignOp
"""


@pytest.fixture
def installed(tmp_path: Path, monkeypatch) -> Iterator[str]:
    """Install a uniquely named operator package and remove its modules afterwards."""
    package = f"acme_ops_{uuid.uuid4().hex[:8]}"
    _install(tmp_path, package, entry_points=_ENTRY_POINTS)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield package
    for name in [m for m in sys.modules if m == package or m.startswith(f"{package}.")]:
        del sys.modules[name]


@pytest.fixture
def installed_without_entry_points(tmp_path: Path, monkeypatch) -> Iterator[str]:
    """Install an operator package whose distribution declares no entry points."""
    package = f"acme_ops_{uuid.uuid4().hex[:8]}"
    _install(tmp_path, package, entry_points="")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield package
    for name in [m for m in sys.modules if m == package or m.startswith(f"{package}.")]:
        del sys.modules[name]


@pytest.fixture
def installed_with_aliased_entry_point(tmp_path: Path, monkeypatch) -> Iterator[str]:
    """Install a package whose entry point exports a locally defined class by alias."""
    package = f"acme_ops_{uuid.uuid4().hex[:8]}"
    _install(
        tmp_path,
        package,
        entry_points="[docpipe.operators]\nalias = {package}.operators:AliasOp\n",
        with_operators_module=False,
    )
    (tmp_path / package / "operators.py").write_text(
        _HEADER + _OPERATOR.format(name="ActualOp", short_name="actual_op") + "\nAliasOp = ActualOp\ndel ActualOp\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield package
    for name in [m for m in sys.modules if m == package or m.startswith(f"{package}.")]:
        del sys.modules[name]


class TestDiscovery:
    """Entry points first, then module inspection, de-duplicated by short_name."""

    def test_lists_operators_from_entry_points_and_module(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)

        operators = {op.short_name: op for op in adapter.list_operators()}

        assert set(operators) == {"extra_op", "shared_op", "module_op"}
        assert operators["extra_op"].module_path == f"{installed}.extra:ExtraOp"
        assert operators["shared_op"].module_path == f"{installed}.operators:SharedOp"
        assert {op.source_location for op in operators.values()} == {f"package:{installed}"}

    def test_entry_point_failure_still_allows_module_inspection(self, installed: str, monkeypatch) -> None:
        def _broken_entry_points(**kwargs):
            raise RuntimeError("metadata is corrupt")

        monkeypatch.setattr(importlib.metadata, "entry_points", _broken_entry_points)

        operators = PackageAdapter(package_name=installed).list_operators()

        assert {op.short_name for op in operators} == {"module_op", "shared_op"}

    def test_module_inspection_failure_still_returns_entry_points(self, installed: str, monkeypatch) -> None:
        adapter = PackageAdapter(package_name=installed)
        real_import = importlib.import_module

        def _import(name: str, *args, **kwargs):
            if name == adapter.full_module_path:
                raise ImportError("operators module was removed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", _import)

        assert {op.short_name for op in adapter.list_operators()} == {"extra_op", "shared_op"}


class TestLoading:
    """load_operator, its cache and clear_cache."""

    def test_loads_module_inspected_operator_without_entry_points(self, installed_without_entry_points: str) -> None:
        adapter = PackageAdapter(package_name=installed_without_entry_points)
        info = next(op for op in adapter.list_operators() if op.short_name == "module_op")

        assert info.module_path == f"{installed_without_entry_points}.operators:ModuleOp"
        assert adapter.load_operator(operator_info=info).__name__ == f"{installed_without_entry_points}.operators"

    def test_resolves_each_discovered_class_from_real_package(self, installed_without_entry_points: str) -> None:
        adapter = PackageAdapter(package_name=installed_without_entry_points)

        loaded = CustomOperatorLoader(sources=[adapter]).validate_and_load(builtin_operators={})
        module = importlib.import_module(f"{installed_without_entry_points}.operators")

        assert loaded["module_op"] is module.ModuleOp
        assert loaded["shared_op"] is module.SharedOp

    def test_entry_point_selects_named_class_in_multi_operator_module(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = next(op for op in adapter.list_operators() if op.short_name == "shared_op")

        loaded = CustomOperatorLoader(sources=[adapter]).load_and_validate_operator(info, adapter)

        assert loaded is not None
        assert loaded is importlib.import_module(f"{installed}.operators").SharedOp

    def test_entry_point_alias_remains_loadable(self, installed_with_aliased_entry_point: str) -> None:
        adapter = PackageAdapter(package_name=installed_with_aliased_entry_point)
        info = next(op for op in adapter.list_operators() if op.short_name == "actual_op")

        loaded = CustomOperatorLoader(sources=[adapter]).load_and_validate_operator(info, adapter)

        assert info.name == "ActualOp"
        assert loaded is not None
        assert loaded.__name__ == "ActualOp"

    def test_module_inspection_uses_loadable_alias(self, installed_with_aliased_entry_point: str) -> None:
        adapter = PackageAdapter(package_name=installed_with_aliased_entry_point)
        info = next(op for op in adapter._discover_via_module_inspection() if op.short_name == "actual_op")

        assert info.module_path == f"{installed_with_aliased_entry_point}.operators:AliasOp"
        assert CustomOperatorLoader(sources=[adapter]).load_and_validate_operator(info, adapter).__name__ == "ActualOp"

    def test_stale_named_metadata_is_reported_without_loading_another_class(
        self, installed_without_entry_points: str, caplog
    ) -> None:
        adapter = PackageAdapter(package_name=installed_without_entry_points)
        info = next(op for op in adapter.list_operators() if op.short_name == "module_op")
        stale = replace(info, name="MissingOp")
        loader = CustomOperatorLoader(sources=[adapter])

        assert loader.load_and_validate_operator(stale, adapter) is None
        assert "Operator class 'MissingOp'" in caplog.text
        assert loader.load_and_validate_operator(info, adapter).__name__ == "ModuleOp"

    def test_loads_entry_point_module_and_caches_it(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = next(op for op in adapter.list_operators() if op.short_name == "extra_op")

        module = adapter.load_operator(operator_info=info)

        assert module.__name__ == f"{installed}.extra"
        assert (
            adapter.load_operator(operator_info=OperatorInfo(**{**info.__dict__, "module_path": module.__name__}))
            is module
        )
        assert adapter.validate_operator(module=module, operator_info=info).valid

    def test_named_module_path_hits_cache(self, installed: str, monkeypatch) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = next(op for op in adapter.list_operators() if op.short_name == "extra_op")
        imported = []
        original = importlib.import_module

        def import_module(name, *args, **kwargs):
            imported.append(name)
            return original(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", import_module)

        first = adapter.load_operator(operator_info=info)
        second = adapter.load_operator(operator_info=info)

        assert second is first
        assert imported == [f"{installed}.extra"]
        assert adapter._loaded_modules == {f"{installed}.extra": first}

    def test_loads_plain_module_path(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = OperatorInfo(
            name="ExtraOp", short_name="extra_op", module_path=f"{installed}.extra", category="x", source_location="x"
        )

        assert adapter.load_operator(operator_info=info).__name__ == f"{installed}.extra"
        assert CustomOperatorLoader(sources=[adapter]).load_and_validate_operator(info, adapter).__name__ == "ExtraOp"

    def test_unknown_module_raises_import_error(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = OperatorInfo(
            name="Ghost", short_name="ghost", module_path=f"{installed}.ghost:Ghost", category="x", source_location="x"
        )

        with pytest.raises(ImportError, match=f"Failed to load operator module '{installed}.ghost'"):
            adapter.load_operator(operator_info=info)

    def test_clear_cache_tolerates_modules_already_unloaded(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = next(op for op in adapter.list_operators() if op.short_name == "extra_op")
        module = adapter.load_operator(operator_info=info)
        del sys.modules[module.__name__]

        adapter.clear_cache()

        assert adapter._loaded_modules == {}

    def test_clear_cache_forgets_loaded_modules(self, installed: str) -> None:
        adapter = PackageAdapter(package_name=installed)
        info = next(op for op in adapter.list_operators() if op.short_name == "extra_op")
        module = adapter.load_operator(operator_info=info)

        adapter.clear_cache()

        assert module.__name__ not in sys.modules
        assert adapter._loaded_modules == {}
        reloaded = adapter.load_operator(operator_info=info)
        assert reloaded is not module


class TestConstructionErrors:
    """Package checks in __init__."""

    def test_package_that_is_not_installed(self) -> None:
        with pytest.raises(ImportError, match="Package 'acme_not_installed' is not installed"):
            PackageAdapter(package_name="acme_not_installed")

    def test_installed_metadata_without_importable_package(self, tmp_path: Path, monkeypatch) -> None:
        package = f"acme_ghost_{uuid.uuid4().hex[:8]}"
        dist = tmp_path / f"{package}-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        with pytest.raises(ImportError, match=f"Failed to import package '{package}'"):
            PackageAdapter(package_name=package)

    def test_missing_operator_module(self, tmp_path: Path, monkeypatch) -> None:
        package = f"acme_noops_{uuid.uuid4().hex[:8]}"
        _install(tmp_path, package, entry_points="", with_operators_module=False)
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        try:
            with pytest.raises(ValueError, match=f"Operator module 'operators' not found in package '{package}'"):
                PackageAdapter(package_name=package)
        finally:
            sys.modules.pop(package, None)

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("", "must be a non-empty string"),
            ("acme..ops", "path traversal"),
            ("acme/ops", "path traversal"),
            ("acme.", "cannot have empty parts"),
            ("acme.1ops", "Part '1ops' contains invalid characters"),
        ],
    )
    def test_invalid_package_names(self, name: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            PackageAdapter(package_name=name)
