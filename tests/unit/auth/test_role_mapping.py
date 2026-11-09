# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the group-to-role mapping and its YAML reader."""

import pytest

from docpipe.api.auth.config import AuthSettings
from docpipe.api.auth.role_mapping import resolve_role
from docpipe.api.auth.roles import Role
from docpipe.core.constants.constants import EnvironmentVariables

_EDITOR_DN = "cn=Pipeline Editors,ou=groups,dc=example,dc=com"
_ADMIN_DN = "cn=Pipeline Admins,ou=groups,dc=example,dc=com"

_MAPPING = {
    Role.VIEWER: (),
    Role.EDITOR: (_EDITOR_DN, "oidc-editors"),
    Role.ADMIN: (_ADMIN_DN,),
}


class TestResolveRole:
    def test_mapped_group_grants_role(self):
        role = resolve_role(groups=["oidc-editors"], role_mapping=_MAPPING, default_role=Role.VIEWER)

        assert role is Role.EDITOR

    def test_unmapped_user_gets_default_role(self):
        role = resolve_role(groups=["something-else"], role_mapping=_MAPPING, default_role=Role.VIEWER)

        assert role is Role.VIEWER

    def test_no_groups_gets_default_role(self):
        assert resolve_role(groups=[], role_mapping=_MAPPING, default_role=Role.VIEWER) is Role.VIEWER

    def test_configured_default_role_applies(self):
        role = resolve_role(groups=[], role_mapping=_MAPPING, default_role=Role.EDITOR)

        assert role is Role.EDITOR

    def test_highest_role_wins(self):
        role = resolve_role(groups=[_EDITOR_DN, _ADMIN_DN], role_mapping=_MAPPING, default_role=Role.VIEWER)

        assert role is Role.ADMIN

    def test_exact_match_is_case_sensitive_by_default(self):
        role = resolve_role(groups=["OIDC-EDITORS"], role_mapping=_MAPPING, default_role=Role.VIEWER)

        assert role is Role.VIEWER

    def test_case_insensitive_matching_for_ldap_dns(self):
        role = resolve_role(
            groups=[_ADMIN_DN.upper()], role_mapping=_MAPPING, default_role=Role.VIEWER, case_insensitive=True
        )

        assert role is Role.ADMIN

    def test_whitespace_is_trimmed_on_both_sides(self):
        mapping = {Role.EDITOR: ("  oidc-editors ",)}

        role = resolve_role(groups=["\toidc-editors  "], role_mapping=mapping, default_role=Role.VIEWER)

        assert role is Role.EDITOR

    def test_blank_group_never_matches_blank_mapping_entry(self):
        mapping = {Role.ADMIN: ("",)}

        role = resolve_role(groups=["", "   "], role_mapping=mapping, default_role=Role.VIEWER)

        assert role is Role.VIEWER

    def test_non_string_groups_are_ignored(self):
        role = resolve_role(
            groups=[1, None, "oidc-editors"],  # type: ignore[list-item]
            role_mapping=_MAPPING,
            default_role=Role.VIEWER,
        )

        assert role is Role.EDITOR


class TestYamlRoleMapping:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in (
            EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_VIEWER,
            EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_EDITOR,
            EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_ADMIN,
        ):
            monkeypatch.delenv(name, raising=False)

    @staticmethod
    def _write_config(*, tmp_path, monkeypatch, text: str):
        config_file = tmp_path / "docling-pipelines-config.yaml"
        config_file.write_text(text, encoding="utf-8")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(config_file))
        return config_file

    def test_yaml_lists_are_read_for_every_role(self, tmp_path, monkeypatch):
        self._write_config(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            text=(
                "auth:\n"
                "  role_mapping:\n"
                "    viewer: [readers]\n"
                "    editor:\n"
                "      - editors\n"
                "      - ' power users '\n"
                "    admin: ['cn=admins,dc=example,dc=com']\n"
            ),
        )

        mapping = AuthSettings.from_env().role_mapping

        assert mapping == {
            Role.VIEWER: ("readers",),
            Role.EDITOR: ("editors", "power users"),
            Role.ADMIN: ("cn=admins,dc=example,dc=com",),
        }

    def test_env_variable_wins_per_role(self, tmp_path, monkeypatch):
        self._write_config(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            text="auth:\n  role_mapping:\n    editor: [yaml-editors]\n    admin: [yaml-admins]\n",
        )
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_EDITOR, "env-editors;env-more")

        mapping = AuthSettings.from_env().role_mapping

        assert mapping[Role.EDITOR] == ("env-editors", "env-more")
        assert mapping[Role.ADMIN] == ("yaml-admins",)
        assert mapping[Role.VIEWER] == ()

    def test_missing_file_yields_empty_mapping(self, tmp_path, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(tmp_path / "absent.yaml"))

        assert AuthSettings.from_env().role_mapping == {Role.VIEWER: (), Role.EDITOR: (), Role.ADMIN: ()}

    def test_file_without_auth_section_yields_empty_mapping(self, tmp_path, monkeypatch):
        self._write_config(tmp_path=tmp_path, monkeypatch=monkeypatch, text="assets_management: {}\n")

        assert AuthSettings.from_env().role_mapping[Role.ADMIN] == ()

    def test_malformed_yaml_yields_empty_mapping(self, tmp_path, monkeypatch):
        self._write_config(tmp_path=tmp_path, monkeypatch=monkeypatch, text="auth: [unclosed\n")

        assert AuthSettings.from_env().role_mapping[Role.EDITOR] == ()

    def test_changed_file_is_re_read(self, tmp_path, monkeypatch):
        config_file = self._write_config(
            tmp_path=tmp_path, monkeypatch=monkeypatch, text="auth:\n  role_mapping:\n    editor: [first]\n"
        )
        assert AuthSettings.from_env().role_mapping[Role.EDITOR] == ("first",)

        config_file.write_text("auth:\n  role_mapping:\n    editor: [second-longer]\n", encoding="utf-8")

        assert AuthSettings.from_env().role_mapping[Role.EDITOR] == ("second-longer",)
