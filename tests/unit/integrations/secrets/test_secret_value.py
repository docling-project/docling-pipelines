# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the opaque SecretValue wrapper (task B.1)."""

import copy
import json
import logging
import pickle

import pytest

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.integrations.secrets import SecretValue, secret_json_default

CANARY = "canary-s3cr3t-value-4242"  # pragma: allowlist secret


@pytest.fixture
def secret() -> SecretValue:
    return SecretValue(value=CANARY)


class TestSecretValueMasking:
    def test_repr_str_format_are_masked(self, secret: SecretValue) -> None:
        assert CANARY not in repr(secret)
        assert CANARY not in str(secret)
        assert CANARY not in format(secret)
        assert CANARY not in format(secret, ">20")
        assert CANARY not in f"{secret}"
        assert CANARY not in f"{secret!r}"
        assert CANARY not in "%s" % secret  # noqa: UP031
        assert CANARY not in "%r" % secret  # noqa: UP031
        assert CANARY not in "{}".format(secret)  # noqa: UP032
        assert CANARY not in str([secret])
        assert CANARY not in str({"k": secret})

    def test_logging_does_not_leak(self, secret: SecretValue, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG):
            logging.getLogger("test_secret_value").info("value=%s repr=%r", secret, secret)
        assert CANARY not in caplog.text

    def test_reveal_returns_value(self, secret: SecretValue) -> None:
        assert secret.reveal() == CANARY

    def test_is_not_a_str(self, secret: SecretValue) -> None:
        assert not isinstance(secret, str)

    def test_immutable(self, secret: SecretValue) -> None:
        with pytest.raises(AttributeError):
            secret.extra = "x"  # type: ignore[attr-defined]
        with pytest.raises(AttributeError):
            secret._value = "x"
        with pytest.raises(AttributeError):
            del secret._value

    def test_no_instance_dict(self, secret: SecretValue) -> None:
        assert not hasattr(secret, "__dict__")


class TestSecretValueSerialization:
    @pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
    def test_pickle_refused(self, secret: SecretValue, protocol: int) -> None:
        with pytest.raises(TypeError):
            pickle.dumps(secret, protocol=protocol)

    def test_copy_does_not_expose_value(self, secret: SecretValue) -> None:
        for clone in (copy.copy(secret), copy.deepcopy(secret), copy.deepcopy({"k": [secret]})["k"][0]):
            assert isinstance(clone, SecretValue)
            assert CANARY not in repr(clone)
            assert clone.reveal() == CANARY

    def test_json_dumps_without_default_raises(self, secret: SecretValue) -> None:
        with pytest.raises(TypeError):
            json.dumps({"password": secret})

    def test_json_dumps_with_default_masks(self, secret: SecretValue) -> None:
        out = json.dumps({"password": secret}, default=secret_json_default)
        assert CANARY not in out
        assert json.loads(out) == {"password": "***"}

    def test_json_default_still_rejects_other_types(self) -> None:
        with pytest.raises(TypeError):
            secret_json_default(object())


class TestSecretValueOperators:
    def test_join_raises(self, secret: SecretValue) -> None:
        with pytest.raises(TypeError):
            "".join(secret)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            "".join([secret])  # type: ignore[list-item]

    def test_iter_and_len_raise(self, secret: SecretValue) -> None:
        with pytest.raises(TypeError):
            iter(secret)
        with pytest.raises(TypeError):
            len(secret)
        with pytest.raises(TypeError):
            list(secret)

    def test_concatenation_unsupported(self, secret: SecretValue) -> None:
        with pytest.raises(TypeError):
            _ = "Bearer " + secret  # type: ignore[operator]
        with pytest.raises(TypeError):
            _ = secret + "x"  # type: ignore[operator]

    def test_eq_against_str_is_false(self, secret: SecretValue) -> None:
        assert (secret == CANARY) is False
        assert (CANARY == secret) is False
        assert (secret != CANARY) is True

    def test_eq_is_identity_based(self, secret: SecretValue) -> None:
        other = SecretValue(value=CANARY)
        assert secret == secret
        assert secret != other

    def test_hash_is_identity_based(self, secret: SecretValue) -> None:
        other = SecretValue(value=CANARY)
        assert hash(secret) == hash(secret)
        assert hash(secret) != hash(CANARY)
        assert len({secret, other}) == 2


class TestResolveEnvVarPassthrough:
    def test_returns_same_instance(self, secret: SecretValue) -> None:
        assert resolve_env_var(secret) is secret

    def test_home_reference_value_is_not_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/home/someone")
        wrapped = SecretValue(value="${HOME}")
        assert resolve_env_var(wrapped) is wrapped
        assert wrapped.reveal() == "${HOME}"

    def test_dollar_prefixed_secret_does_not_raise_or_leak(self) -> None:
        wrapped = SecretValue(value="$ecret_Value_98765")
        # A plain str would raise ValueError("Environment variable ecret_Value_98765 is not set").
        assert resolve_env_var(wrapped) is wrapped
        assert wrapped.reveal() == "$ecret_Value_98765"

    def test_uppercase_secret_is_not_replaced_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_PASSWORD", "different-from-the-secret")
        wrapped = SecretValue(value="MY_PASSWORD")
        # A plain str would be replaced by the environment value.
        assert resolve_env_var(wrapped) is wrapped
        assert wrapped.reveal() == "MY_PASSWORD"

    def test_plain_str_behavior_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_PASSWORD", "from-env")
        assert resolve_env_var("MY_PASSWORD") == "from-env"
        assert resolve_env_var("literal") == "literal"
