# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the per-run secret registry, the scrubber, and HMAC cache keys."""

import base64
import json
import logging
from collections.abc import Generator
from typing import Any
from urllib.parse import quote, quote_plus

import pytest

from docpipe.integrations.secrets import registry as registry_module
from docpipe.integrations.secrets.registry import (
    MASK,
    SCRUB_FAILURE_PLACEHOLDER,
    SecretRegistry,
    cache_key_digest,
    clear_run,
    get_registry,
    register_secret,
    scrub,
    scrub_value,
)

# pragma: allowlist nextline secret
PASSWORD = 'p@ss w/ord"&=+'
RUN = "run-1"


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    get_registry().clear_all()
    yield
    get_registry().clear_all()


class TestRegistration:
    def test_raw_value_is_scrubbed(self) -> None:
        register_secret(value=PASSWORD, run_id=RUN)
        assert scrub(f"connect with {PASSWORD} now") == f"connect with {MASK} now"

    @pytest.mark.parametrize(
        "encode",
        [
            quote,
            quote_plus,
            lambda text: json.dumps(text)[1:-1],
            lambda text: base64.b64encode(text.encode()).decode(),
            lambda text: base64.urlsafe_b64encode(text.encode()).decode(),
            lambda text: base64.b64encode(text.encode()).decode().rstrip("="),
        ],
        ids=["percent", "plus", "json", "base64", "urlsafe-base64", "unpadded-base64"],
    )
    def test_encoded_forms_are_scrubbed(self, encode: Any) -> None:
        register_secret(value=PASSWORD, run_id=RUN)
        encoded = encode(PASSWORD)
        assert encoded not in scrub(f"url?x={encoded}&y=1")

    def test_empty_value_is_never_registered(self) -> None:
        assert register_secret(value="", run_id=RUN) == 0
        assert not get_registry().has_entries()
        assert scrub("an ordinary line") == "an ordinary line"

    def test_short_value_is_registered(self) -> None:
        register_secret(value="ab", run_id=RUN)
        assert scrub("xaby") == f"x{MASK}y"

    def test_longest_form_wins_over_a_prefix_value(self) -> None:
        register_secret(value="abc", run_id=RUN)
        register_secret(value="abcdef", run_id=RUN)
        assert scrub("abcdef") == MASK

    def test_structured_value_registers_json_and_every_leaf(self) -> None:
        # pragma: allowlist nextline secret
        register_secret(value={"private_key": "KEY-MATERIAL", "nested": {"id": "LEAF-9"}}, run_id=RUN)
        text = scrub('{"private_key": "KEY-MATERIAL"} LEAF-9')
        assert "KEY-MATERIAL" not in text
        assert "LEAF-9" not in text

    def test_run_defaults_to_the_session_run_id(self) -> None:
        from docpipe.core.models.session_info import create_session_info

        create_session_info(job_run_id="run-session")
        register_secret(value="session-secret")
        clear_run()
        assert scrub("session-secret") == "session-secret"


class TestLifetime:
    def test_clear_run_drops_only_that_run(self) -> None:
        register_secret(value="first-secret", run_id="a")
        register_secret(value="second-secret", run_id="b")
        clear_run(run_id="a")
        assert scrub("first-secret second-secret") == f"first-secret {MASK}"

    def test_clear_run_empties_the_registry(self) -> None:
        register_secret(value=PASSWORD, run_id=RUN)
        clear_run(run_id=RUN)
        assert not get_registry().has_entries()
        assert scrub(PASSWORD) == PASSWORD

    def test_clear_unknown_run_is_a_noop(self) -> None:
        clear_run(run_id="never-existed")


class TestFailClosed:
    def test_scrubber_failure_returns_the_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        register_secret(value=PASSWORD, run_id=RUN)

        def boom(*, text: str) -> str:
            raise RuntimeError("scrubber broke")

        monkeypatch.setattr(registry_module.get_registry(), "scrub_text", boom)
        assert scrub(f"leaks {PASSWORD}") == SCRUB_FAILURE_PLACEHOLDER

    def test_scrub_value_failure_returns_the_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        register_secret(value=PASSWORD, run_id=RUN)

        def boom(*, text: str) -> str:
            raise RuntimeError("scrubber broke")

        monkeypatch.setattr(registry_module.get_registry(), "scrub_text", boom)
        assert scrub_value({"message": PASSWORD}) == SCRUB_FAILURE_PLACEHOLDER


class TestScrubValue:
    def test_walks_dicts_lists_tuples_and_keys(self) -> None:
        register_secret(value="SECRET-1", run_id=RUN)
        value = {"a": ["x SECRET-1", ("SECRET-1",)], "SECRET-1": 3, "n": 7}
        assert scrub_value(value) == {"a": [f"x {MASK}", (MASK,)], MASK: 3, "n": 7}

    def test_returns_input_when_nothing_is_registered(self) -> None:
        value = {"a": 1}
        assert scrub_value(value) is value


class TestCacheKeyDigest:
    def test_digest_contains_no_substring_of_the_secret(self) -> None:
        digest = cache_key_digest(namespace="t", parts=["client-secret-value"], run_id=RUN)
        assert len(digest) == 64
        assert "client" not in digest
        assert "secret" not in digest

    def test_digest_is_stable_within_a_run(self) -> None:
        first = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        assert first == cache_key_digest(namespace="t", parts=["s"], run_id=RUN)

    def test_digest_differs_between_runs(self) -> None:
        assert cache_key_digest(namespace="t", parts=["s"], run_id="a") != cache_key_digest(
            namespace="t", parts=["s"], run_id="b"
        )

    def test_digest_differs_after_the_run_is_cleared(self) -> None:
        before = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        clear_run(run_id=RUN)
        assert before != cache_key_digest(namespace="t", parts=["s"], run_id=RUN)

    def test_digest_differs_by_namespace_and_value(self) -> None:
        base = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        assert base != cache_key_digest(namespace="u", parts=["s"], run_id=RUN)
        assert base != cache_key_digest(namespace="t", parts=["s2"], run_id=RUN)

    def test_digest_is_not_an_unsalted_hash(self) -> None:
        import hashlib

        digest = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        assert digest != hashlib.sha256(b"s").hexdigest()

    def test_digest_is_absent_from_debug_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        digest = cache_key_digest(namespace="t", parts=["s"], run_id=RUN)
        assert digest not in caplog.text


class TestRegistryClass:
    def test_derive_forms_never_contains_the_empty_string(self) -> None:
        assert "" not in SecretRegistry.derive_forms(value="a")

    def test_registry_instances_are_independent(self) -> None:
        local = SecretRegistry()
        local.register(run_id=RUN, value="local-only")
        assert scrub("local-only") == "local-only"
        assert local.scrub_text(text="local-only") == MASK
