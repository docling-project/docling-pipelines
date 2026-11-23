# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for DocpipeConfigLoader."""

from __future__ import annotations

import pytest
import yaml

from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


@pytest.fixture(autouse=True)
def reset_loader():
    """Reset the singleton cache before and after every test."""
    DocpipeConfigLoader.reset()
    yield
    DocpipeConfigLoader.reset()


class TestDocpipeConfigLoaderGetConfig:
    def test_returns_empty_dict_when_no_file(self, *, tmp_path, monkeypatch):
        """Returns {} when DOCPIPE_CONFIG_PATH points to a nonexistent file."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        assert DocpipeConfigLoader.get_config() == {}

    def test_parses_yaml_file(self, *, tmp_path, monkeypatch):
        """Returns parsed dict when a valid YAML file is found."""
        config = {"global_storage": {"type": "duckdb"}, "job_management": {"storage": {"type": "duckdb"}}}
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        result = DocpipeConfigLoader.get_config()
        assert result["global_storage"]["type"] == "duckdb"
        assert result["job_management"]["storage"]["type"] == "duckdb"

    def test_returns_empty_dict_on_invalid_yaml(self, *, tmp_path, monkeypatch):
        """Returns {} (and does not raise) when the YAML is malformed."""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("key: [\nnot: valid yaml: {")

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        result = DocpipeConfigLoader.get_config()
        assert result == {}

    def test_returns_empty_dict_for_empty_yaml_file(self, *, tmp_path, monkeypatch):
        """Returns {} when the YAML file exists but is empty."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        assert DocpipeConfigLoader.get_config() == {}

    def test_caches_result_after_first_call(self, *, tmp_path, monkeypatch):
        """The file is read only once; subsequent calls return the same object."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump({"key": "value"}, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        first = DocpipeConfigLoader.get_config()
        second = DocpipeConfigLoader.get_config()
        assert first is second

    def test_reset_clears_cache(self, *, tmp_path, monkeypatch):
        """After reset(), the next call re-reads the file."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump({"version": 1}, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        first = DocpipeConfigLoader.get_config()
        DocpipeConfigLoader.reset()

        # Overwrite the file with different content
        with config_path.open("w") as fh:
            yaml.dump({"version": 2}, fh)

        second = DocpipeConfigLoader.get_config()
        assert first is not second
        assert second["version"] == 2


class TestDocpipeConfigLoaderGet:
    def test_returns_value_for_existing_key(self, *, tmp_path, monkeypatch):
        """get() returns the value for a known top-level key."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump({"global_storage": {"type": "filesystem"}}, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        result = DocpipeConfigLoader.get(key="global_storage")
        assert result == {"type": "filesystem"}

    def test_returns_default_for_missing_key(self, *, tmp_path, monkeypatch):
        """get() returns the supplied default for an absent key."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        result = DocpipeConfigLoader.get(key="missing_key", default={"fallback": True})
        assert result == {"fallback": True}

    def test_returns_none_default_when_not_specified(self, *, tmp_path, monkeypatch):
        """get() returns None when default is not provided and key is absent."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        assert DocpipeConfigLoader.get(key="no_such_key") is None


class TestDocpipeConfigLoaderGetStorage:
    """Tests for DocpipeConfigLoader.get_storage()."""

    def test_service_specific_storage_takes_precedence(self, *, tmp_path, monkeypatch):
        """Service-specific storage config is returned when present."""
        config = {
            "global_storage": {"type": "duckdb", "config": {"base_dir": "/global"}},
            "incremental_metadata": {"storage": {"type": "filesystem", "config": {"base_dir": "/service"}}},
        }
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="incremental_metadata")

        assert storage_type == "filesystem"
        assert storage_config == {"base_dir": "/service"}

    def test_global_storage_used_when_no_service_specific(self, *, tmp_path, monkeypatch):
        """Falls back to global_storage when service has no storage block."""
        config = {
            "global_storage": {"type": "duckdb", "config": {"base_dir": "/global"}},
            "incremental_metadata": {"some_other_key": "value"},
        }
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="incremental_metadata")

        assert storage_type == "duckdb"
        assert storage_config == {"base_dir": "/global"}

    def test_default_filesystem_when_no_config_at_all(self, *, tmp_path, monkeypatch):
        """Falls back to 'filesystem' default when neither service nor global config exists."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="incremental_metadata")

        assert storage_type == "filesystem"
        assert storage_config == {}

    def test_returns_empty_config_when_storage_block_has_no_config_key(self, *, tmp_path, monkeypatch):
        """Returns empty dict for config when the storage block has no 'config' sub-key."""
        config = {
            "incremental_metadata": {"storage": {"type": "filesystem"}},
        }
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="incremental_metadata")

        assert storage_type == "filesystem"
        assert storage_config == {}

    def test_global_storage_config_is_returned_when_no_service_key_in_yaml(self, *, tmp_path, monkeypatch):
        """Service key is entirely absent; global_storage is the only fallback."""
        config = {
            "global_storage": {"type": "duckdb", "config": {}},
        }
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="job_run_report")

        assert storage_type == "duckdb"
        assert storage_config == {}

    def test_default_used_when_both_service_and_global_are_absent(self, *, tmp_path, monkeypatch):
        """When config has unrelated keys only, default filesystem is used."""
        config = {"some_section": {"key": "value"}}
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(config, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="flow_definition_snapshot")

        assert storage_type == "filesystem"
        assert storage_config == {}

    def test_default_type_overrides_builtin_default(self, *, tmp_path, monkeypatch):
        """default_type replaces 'filesystem' only when neither service nor global config sets a type."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="job_management", default_type="inmemory")

        assert storage_type == "inmemory"
        assert storage_config == {}

    def test_default_type_ignored_when_global_storage_configured(self, *, tmp_path, monkeypatch):
        """global_storage still wins over default_type."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump({"global_storage": {"type": "duckdb", "config": {}}}, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, _ = DocpipeConfigLoader.get_storage(key="job_management", default_type="inmemory")

        assert storage_type == "duckdb"

    def test_service_block_without_type_falls_back_to_global_type(self, *, tmp_path, monkeypatch):
        """A service block with only config keeps its config and borrows the global type."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump(
                {
                    "global_storage": {"type": "duckdb", "config": {"base_dir": "./global"}},
                    "job_management": {"storage": {"config": {"base_dir": "./svc"}}},
                },
                fh,
            )
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="job_management", default_type="inmemory")

        assert storage_type == "duckdb"
        assert storage_config == {"base_dir": "./svc"}

    def test_service_block_without_type_falls_back_to_default_type(self, *, tmp_path, monkeypatch):
        """With no global type either, default_type is used."""
        config_path = tmp_path / "config.yaml"
        with config_path.open("w") as fh:
            yaml.dump({"job_management": {"storage": {"config": {"base_dir": "./svc"}}}}, fh)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        storage_type, storage_config = DocpipeConfigLoader.get_storage(key="job_management", default_type="inmemory")

        assert storage_type == "inmemory"
        assert storage_config == {"base_dir": "./svc"}
