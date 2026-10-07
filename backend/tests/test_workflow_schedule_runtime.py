from datetime import datetime, timezone

import pytest


@pytest.mark.parametrize("expression", [
    "0 9 * * 0",
    "*/15 */2 * * 1",
    "5 12 1 6 4",
])
def test_workflow_cron_accepts_supported_expressions(expression):
    from app.api.routers.workflow import _valid_cron

    assert _valid_cron(expression)


@pytest.mark.parametrize("expression", [
    "",
    "0 9 * *",
    "60 9 * * 0",
    "*/0 9 * * 0",
    "0 24 * * 0",
    "0 9 * * 7",
    "0-5 9 * * 0",
])
def test_workflow_cron_rejects_unsupported_or_out_of_range_fields(expression):
    from app.api.routers.workflow import _valid_cron

    assert not _valid_cron(expression)


def test_scheduler_checks_weekdays_with_monday_as_zero():
    from app.services.monitoring_scheduler import _cron_is_due

    monday_morning = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    assert _cron_is_due("0 9 * * 0", monday_morning)
    assert not _cron_is_due("0 9 * * 1", monday_morning)


def test_scheduler_does_not_repeat_a_workflow_within_a_matching_minute():
    from app.services.monitoring_scheduler import _has_run_this_minute

    scheduled_tick = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    assert _has_run_this_minute(scheduled_tick, scheduled_tick.replace(second=45))
    assert not _has_run_this_minute(scheduled_tick, scheduled_tick.replace(minute=1))
    assert not _has_run_this_minute(None, scheduled_tick)
