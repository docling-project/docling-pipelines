"""Tests for the context-local session info helpers in docpipe.core.models.session_info.

Each test runs in a fresh copy of the current context, so the ContextVar starts unset there
and nothing leaks into other tests.
"""

import contextvars

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.models.session_info import (
    SessionInfo,
    get_session_info,
    session_info_var,
    set_session_info,
    update_session_info,
)


def _in_fresh_context(func):
    """Run func in a copied context in which no session info has been set yet."""

    def runner():
        session_info_var.set(None)
        return func()

    return contextvars.copy_context().run(runner)


class TestUpdateSessionInfo:
    def test_updates_known_attributes_of_the_current_session(self):
        def scenario():
            current = SessionInfo(job_id="job-old", job_run_id="run-old", flow_id="flow-1")
            set_session_info(current)

            updated = update_session_info(job_id="job-new", job_run_id="run-new")

            return current, updated, get_session_info()

        current, updated, active = _in_fresh_context(scenario)

        assert updated is current
        assert active is current
        assert (current.job_id, current.job_run_id, current.flow_id) == ("job-new", "run-new", "flow-1")
        assert current.get_common_log_arguments() == {
            DocpipeConstants.JOB_ID: "job-new",
            DocpipeConstants.JOB_RUN_ID: "run-new",
        }

    def test_ignores_keys_that_are_not_session_attributes(self):
        def scenario():
            set_session_info(SessionInfo(job_id="job-1"))
            return update_session_info(job_id="job-2", not_a_session_field="ignored")

        updated = _in_fresh_context(scenario)

        assert updated.job_id == "job-2"
        assert not hasattr(updated, "not_a_session_field")

    def test_creates_a_default_session_when_none_is_set(self):
        def scenario():
            updated = update_session_info(job_run_id="run-1")
            return updated, session_info_var.get()

        updated, stored = _in_fresh_context(scenario)

        assert stored is updated
        assert updated.job_run_id == "run-1"
        assert updated.job_id is None
        assert updated.transaction_id == DocpipeConstants.DEFAULT_TRANSACTION_ID

    def test_without_arguments_returns_the_session_unchanged(self):
        def scenario():
            current = SessionInfo(job_id="job-1", track_perf=True)
            set_session_info(current)
            return current, update_session_info()

        current, updated = _in_fresh_context(scenario)

        assert updated is current
        assert (updated.job_id, updated.track_perf) == ("job-1", True)
