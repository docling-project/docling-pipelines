# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for mapping OIDC ``groups`` / ``roles`` claims to roles per provider."""

from unittest.mock import AsyncMock, patch

import pytest

from docpipe.api.auth.dependencies import LOCAL_PRINCIPAL_USERNAME
from docpipe.api.auth.oauth2_config import AzureADOAuth2Config, GoogleOAuth2Config, OAuth2Config
from docpipe.api.auth.oauth2_provider import (
    AzureADOAuth2Provider,
    GenericOIDCProvider,
    GoogleOAuth2Provider,
    OAuth2Provider,
    group_claim_names,
)
from docpipe.api.auth.roles import Role
from docpipe.exceptions.docpipe_exceptions import ExternalServiceError

_EDITORS = "pipeline-editors"
_ADMINS = "pipeline-admins"


@pytest.fixture(autouse=True)
def _role_mapping(monkeypatch):
    monkeypatch.setenv("DOCPIPE_AUTH_ROLE_MAPPING_EDITOR", _EDITORS)
    monkeypatch.setenv("DOCPIPE_AUTH_ROLE_MAPPING_ADMIN", _ADMINS)
    monkeypatch.delenv("DOCPIPE_AUTH_ROLE_MAPPING_VIEWER", raising=False)
    monkeypatch.delenv("DOCPIPE_AUTH_DEFAULT_ROLE", raising=False)
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", "/nonexistent/docling-pipelines-config.yaml")


def _config(**overrides) -> OAuth2Config:
    return OAuth2Config(
        oauth2_enabled=True,
        oauth2_client_id="client",
        oauth2_client_secret="secret",  # pragma: allowlist secret
        **overrides,
    )


async def _extract(provider: OAuth2Provider, payload: dict) -> list[Role]:
    with patch.object(provider, "validate_id_token", new_callable=AsyncMock, return_value=payload):
        user = await provider.extract_user_from_token({"id_token": "id-token"})
    return user.roles


class TestGenericProvider:
    @pytest.mark.asyncio
    async def test_groups_claim_maps_to_role(self):
        roles = await _extract(
            GenericOIDCProvider(_config()), {"preferred_username": "u", "groups": ["other", _EDITORS]}
        )

        assert roles == [Role.EDITOR]

    @pytest.mark.asyncio
    async def test_roles_claim_is_the_fallback(self):
        roles = await _extract(GenericOIDCProvider(_config()), {"preferred_username": "u", "roles": [_ADMINS]})

        assert roles == [Role.ADMIN]

    @pytest.mark.asyncio
    async def test_groups_claim_wins_over_roles_claim(self):
        payload = {"preferred_username": "u", "groups": [_EDITORS], "roles": [_ADMINS]}

        assert await _extract(GenericOIDCProvider(_config()), payload) == [Role.EDITOR]

    @pytest.mark.asyncio
    async def test_highest_role_wins(self):
        payload = {"preferred_username": "u", "groups": [_EDITORS, _ADMINS]}

        assert await _extract(GenericOIDCProvider(_config()), payload) == [Role.ADMIN]

    @pytest.mark.asyncio
    async def test_configured_claim_replaces_the_defaults(self):
        provider = GenericOIDCProvider(_config(oauth2_group_claim="memberships"))
        payload = {"preferred_username": "u", "memberships": [_EDITORS], "groups": [_ADMINS]}

        assert await _extract(provider, payload) == [Role.EDITOR]

    @pytest.mark.asyncio
    async def test_string_claim_value_is_accepted(self):
        payload = {"preferred_username": "u", "groups": f"  {_EDITORS} "}

        assert await _extract(GenericOIDCProvider(_config()), payload) == [Role.EDITOR]

    @pytest.mark.asyncio
    async def test_oidc_group_identifiers_are_case_sensitive(self):
        payload = {"preferred_username": "u", "groups": [_EDITORS.upper()]}

        assert await _extract(GenericOIDCProvider(_config()), payload) == [Role.VIEWER]

    @pytest.mark.asyncio
    async def test_userinfo_fallback_maps_groups(self):
        provider = GenericOIDCProvider(_config())
        with patch.object(
            provider,
            "get_user_info",
            new_callable=AsyncMock,
            return_value={"sub": "abc", "groups": [_ADMINS]},
        ):
            user = await provider.extract_user_from_token({"access_token": "access"})

        assert user.roles == [Role.ADMIN]

    @pytest.mark.asyncio
    async def test_no_claim_leaves_viewer(self):
        assert await _extract(GenericOIDCProvider(_config()), {"preferred_username": "u"}) == [Role.VIEWER]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("claim", [None, 42, {"a": 1}, []])
    async def test_malformed_claim_leaves_viewer(self, claim):
        payload = {"preferred_username": "u", "groups": claim}

        assert await _extract(GenericOIDCProvider(_config()), payload) == [Role.VIEWER]


class TestAzureProvider:
    @pytest.mark.asyncio
    async def test_groups_claim_maps_to_role(self):
        provider = AzureADOAuth2Provider(AzureADOAuth2Config(oauth2_enabled=True, oauth2_client_id="c"))
        payload = {"preferred_username": "u@corp.example", "groups": ["11111111-2222", _ADMINS]}

        assert await _extract(provider, payload) == [Role.ADMIN]

    @pytest.mark.asyncio
    async def test_overage_without_groups_claim_leaves_viewer(self):
        provider = AzureADOAuth2Provider(AzureADOAuth2Config(oauth2_enabled=True, oauth2_client_id="c"))
        payload = {
            "preferred_username": "u@corp.example",
            "_claim_names": {"groups": "src1"},
            "_claim_sources": {"src1": {"endpoint": "https://graph.example/users/x/getMemberObjects"}},
        }

        assert await _extract(provider, payload) == [Role.VIEWER]


class TestGoogleProvider:
    @pytest.mark.asyncio
    async def test_google_sends_no_group_claim_so_user_is_viewer(self):
        provider = GoogleOAuth2Provider(GoogleOAuth2Config(oauth2_enabled=True, oauth2_client_id="c"))
        payload = {"email": "u@gmail.com", "name": "U"}

        assert await _extract(provider, payload) == [Role.VIEWER]


class TestConfigurationAndSafety:
    def test_default_claim_order_is_groups_then_roles(self):
        assert group_claim_names(config=_config()) == ("groups", "roles")

    def test_configured_claim_is_used_alone(self):
        assert group_claim_names(config=_config(oauth2_group_claim=" memberships ")) == ("memberships",)

    @pytest.mark.asyncio
    async def test_configured_default_role_applies(self, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_DEFAULT_ROLE", "editor")

        assert await _extract(GenericOIDCProvider(_config()), {"preferred_username": "u"}) == [Role.EDITOR]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("provider_cls", "payload"),
        [
            (GenericOIDCProvider, {"preferred_username": LOCAL_PRINCIPAL_USERNAME}),
            (GoogleOAuth2Provider, {"email": LOCAL_PRINCIPAL_USERNAME}),
            (AzureADOAuth2Provider, {"preferred_username": LOCAL_PRINCIPAL_USERNAME}),
        ],
    )
    async def test_reserved_username_is_rejected(self, provider_cls, payload):
        provider = provider_cls(_config())

        with pytest.raises(ExternalServiceError):
            await _extract(provider, payload)
