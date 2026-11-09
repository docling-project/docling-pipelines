# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the in-process login throttle."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from docpipe.api.middleware import rate_limit
from docpipe.api.middleware.rate_limit import (
    MAX_TRACKED_KEYS,
    PAIR_LOCKOUT_SECONDS,
    PAIR_LOCKOUT_THRESHOLD,
    RATE_LIMIT_MAX_ATTEMPTS,
    RATE_LIMIT_WINDOW_SECONDS,
    _login_attempts,
    _pair_state,
    check_login_rate_limit,
    get_client_ip,
    login_retry_after,
    record_failed_login,
    reset_login_failures,
)


class FakeClock:
    """Controllable replacement for ``time.monotonic`` inside the rate limit module."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def clear_state():
    """Reset the shared state before each test."""
    rate_limit.reset_all_state()
    yield
    rate_limit.reset_all_state()


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(monotonic=fake.monotonic))
    return fake


def _fail(*, client_ip: str, count: int, username: str | None = None) -> None:
    """Record ``count`` failures, using a different username each time unless one is given."""
    for index in range(count):
        record_failed_login(client_ip=client_ip, username=username or f"user-{index}")


def _request(*, peer: str | None, forwarded_for: str | None = None) -> MagicMock:
    request = MagicMock()
    request.client = SimpleNamespace(host=peer) if peer else None
    request.headers = {"x-forwarded-for": forwarded_for} if forwarded_for is not None else {}
    return request


class TestPerAddressFailureWindow:
    def test_first_attempt_is_allowed(self):
        assert check_login_rate_limit(client_ip="1.2.3.4") is True

    def test_check_does_not_record(self):
        for _ in range(RATE_LIMIT_MAX_ATTEMPTS * 3):
            assert check_login_rate_limit(client_ip="1.2.3.4") is True
        assert not _login_attempts

    def test_failures_up_to_max_still_allow_the_next_attempt(self):
        _fail(client_ip="1.2.3.4", count=RATE_LIMIT_MAX_ATTEMPTS - 1)
        assert check_login_rate_limit(client_ip="1.2.3.4") is True

    def test_attempt_after_max_failures_is_rejected(self):
        _fail(client_ip="1.2.3.4", count=RATE_LIMIT_MAX_ATTEMPTS)
        assert check_login_rate_limit(client_ip="1.2.3.4") is False

    def test_different_addresses_are_tracked_independently(self):
        _fail(client_ip="10.0.0.1", count=RATE_LIMIT_MAX_ATTEMPTS)
        assert check_login_rate_limit(client_ip="10.0.0.1") is False
        assert check_login_rate_limit(client_ip="10.0.0.2") is True

    def test_window_expiry_reopens_the_address(self, clock):
        _fail(client_ip="5.5.5.5", count=RATE_LIMIT_MAX_ATTEMPTS)
        assert check_login_rate_limit(client_ip="5.5.5.5") is False

        clock.advance(RATE_LIMIT_WINDOW_SECONDS + 1)

        assert check_login_rate_limit(client_ip="5.5.5.5") is True
        assert "5.5.5.5" not in _login_attempts

    def test_sliding_window_reopens_when_oldest_failure_leaves(self, clock):
        record_failed_login(client_ip="6.6.6.6", username="a")
        clock.advance(30)
        _fail(client_ip="6.6.6.6", count=RATE_LIMIT_MAX_ATTEMPTS - 1)
        assert check_login_rate_limit(client_ip="6.6.6.6") is False

        clock.advance(RATE_LIMIT_WINDOW_SECONDS - 30 + 1)  # first failure is now out of the window

        assert check_login_rate_limit(client_ip="6.6.6.6") is True

    def test_retry_after_counts_down_to_the_window_end(self, clock):
        _fail(client_ip="7.7.7.7", count=RATE_LIMIT_MAX_ATTEMPTS)
        assert login_retry_after(client_ip="7.7.7.7") == RATE_LIMIT_WINDOW_SECONDS + 1

        clock.advance(40)

        assert login_retry_after(client_ip="7.7.7.7") == RATE_LIMIT_WINDOW_SECONDS - 40 + 1

    def test_retry_after_is_zero_when_allowed(self):
        assert login_retry_after(client_ip="8.8.8.8") == 0

    def test_constants_are_sensible(self):
        assert RATE_LIMIT_MAX_ATTEMPTS > 0
        assert RATE_LIMIT_WINDOW_SECONDS > 0
        assert PAIR_LOCKOUT_THRESHOLD > 0
        assert PAIR_LOCKOUT_SECONDS > RATE_LIMIT_WINDOW_SECONDS


class TestPairLockout:
    def test_consecutive_failures_lock_the_pair_for_five_minutes(self, clock):
        _fail(client_ip="1.1.1.1", count=PAIR_LOCKOUT_THRESHOLD, username="alice")
        # Let the per-address window lapse so only the pair lockout is left.
        clock.advance(RATE_LIMIT_WINDOW_SECONDS + 1)

        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is False
        assert login_retry_after(client_ip="1.1.1.1", username="alice") == PAIR_LOCKOUT_SECONDS - 61 + 1
        assert check_login_rate_limit(client_ip="1.1.1.1", username="bob") is True

        clock.advance(PAIR_LOCKOUT_SECONDS)

        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is True

    def test_below_threshold_does_not_lock_the_pair(self):
        _fail(client_ip="1.1.1.1", count=PAIR_LOCKOUT_THRESHOLD - 1, username="alice")
        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is True

    def test_a_second_address_is_not_locked_out(self):
        _fail(client_ip="1.1.1.1", count=PAIR_LOCKOUT_THRESHOLD, username="alice")

        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is False
        assert check_login_rate_limit(client_ip="2.2.2.2", username="alice") is True

    def test_username_key_ignores_case_and_padding(self):
        for name in ("Alice", "ALICE", " alice ", "alice", "aLiCe"):
            record_failed_login(client_ip="1.1.1.1", username=name)
        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is False

    def test_success_clears_consecutive_failures(self, clock):
        _fail(client_ip="1.1.1.1", count=PAIR_LOCKOUT_THRESHOLD - 1, username="alice")
        reset_login_failures(client_ip="1.1.1.1", username="alice")
        clock.advance(RATE_LIMIT_WINDOW_SECONDS + 1)  # leave only the pair streak in play
        record_failed_login(client_ip="1.1.1.1", username="alice")

        assert _pair_state[("1.1.1.1", "alice")].failures == 1
        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is True

    def test_lockout_is_not_extended_by_checks(self, clock):
        _fail(client_ip="1.1.1.1", count=PAIR_LOCKOUT_THRESHOLD, username="alice")
        clock.advance(RATE_LIMIT_WINDOW_SECONDS + 1)
        for _ in range(20):
            check_login_rate_limit(client_ip="1.1.1.1", username="alice")

        clock.advance(PAIR_LOCKOUT_SECONDS - RATE_LIMIT_WINDOW_SECONDS)

        assert check_login_rate_limit(client_ip="1.1.1.1", username="alice") is True


class TestBounds:
    def test_expired_entries_are_pruned(self, clock):
        for index in range(50):
            record_failed_login(client_ip=f"10.0.0.{index}", username=f"user-{index}")
        clock.advance(PAIR_LOCKOUT_SECONDS + 1)

        check_login_rate_limit(client_ip="9.9.9.9")

        assert not _login_attempts
        assert not _pair_state

    def test_tracked_keys_are_capped(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "MAX_TRACKED_KEYS", 20)
        for index in range(100):
            record_failed_login(client_ip=f"10.0.{index}.1", username=f"user-{index}")

        assert len(_login_attempts) <= 20
        assert len(_pair_state) <= 20
        assert MAX_TRACKED_KEYS >= 20  # production cap is not lowered by the test

    def test_concurrent_failures_are_all_counted(self):
        threads = [
            threading.Thread(target=record_failed_login, kwargs={"client_ip": "3.3.3.3", "username": "alice"})
            for _ in range(40)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(_login_attempts["3.3.3.3"]) == 40


class TestGetClientIp:
    def test_uses_tcp_peer_by_default(self):
        request = _request(peer="10.1.1.1", forwarded_for="6.6.6.6")
        assert get_client_ip(request=request, trust_proxy_headers=False) == "10.1.1.1"

    def test_uses_rightmost_forwarded_entry_when_trusted(self):
        request = _request(peer="10.1.1.1", forwarded_for="6.6.6.6, 7.7.7.7, 203.0.113.9")
        assert get_client_ip(request=request, trust_proxy_headers=True) == "203.0.113.9"

    def test_spoofed_leading_entry_is_ignored(self):
        request = _request(peer="10.1.1.1", forwarded_for="1.2.3.4, 203.0.113.9")
        assert get_client_ip(request=request, trust_proxy_headers=True) != "1.2.3.4"

    def test_falls_back_to_peer_without_header(self):
        request = _request(peer="10.1.1.1")
        assert get_client_ip(request=request, trust_proxy_headers=True) == "10.1.1.1"

    def test_falls_back_to_peer_for_empty_header(self):
        request = _request(peer="10.1.1.1", forwarded_for=" , ")
        assert get_client_ip(request=request, trust_proxy_headers=True) == "10.1.1.1"

    def test_unknown_when_no_peer(self):
        assert get_client_ip(request=_request(peer=None), trust_proxy_headers=False) == "unknown"
