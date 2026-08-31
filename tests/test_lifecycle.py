import pytest

import lifecycle
from config import (
    STATUS_AWAITING_HR_REPLY,
    STATUS_INTERVIEW_SCHEDULED,
    STATUS_NEEDS_INFO,
    STATUS_OFFER,
    STATUS_READY,
    STATUS_REJECTED,
    STATUS_SENT,
    STATUS_SKIPPED,
)


def _row(status, **extra):
    return {"status": status, **extra}


def test_full_chain_to_offer():
    row = _row(STATUS_READY)

    fields = lifecycle.apply_transition(row, "send")
    assert fields["status"] == STATUS_SENT
    row.update(fields)

    fields = lifecycle.apply_transition(row, "hr_reply")
    assert fields["status"] == STATUS_AWAITING_HR_REPLY
    row.update(fields)

    fields = lifecycle.apply_transition(row, "schedule_interview")
    assert fields["status"] == STATUS_INTERVIEW_SCHEDULED
    assert fields["interview_round"] == 1
    row.update(fields)

    fields = lifecycle.apply_transition(row, "schedule_interview")
    assert fields["status"] == STATUS_INTERVIEW_SCHEDULED
    assert fields["interview_round"] == 2
    row.update(fields)

    fields = lifecycle.apply_transition(row, "offer")
    assert fields["status"] == STATUS_OFFER
    row.update(fields)


def test_chain_to_rejected():
    row = _row(STATUS_READY)
    row.update(lifecycle.apply_transition(row, "send"))
    row.update(lifecycle.apply_transition(row, "hr_reply"))
    row.update(lifecycle.apply_transition(row, "schedule_interview"))
    fields = lifecycle.apply_transition(row, "reject")
    assert fields["status"] == STATUS_REJECTED


def test_needs_info_can_only_be_skipped():
    row = _row(STATUS_NEEDS_INFO)
    fields = lifecycle.apply_transition(row, "skip")
    assert fields["status"] == STATUS_SKIPPED
    with pytest.raises(ValueError):
        lifecycle.apply_transition(row, "send")


def test_illegal_transition_from_rejected_is_rejected():
    row = _row(STATUS_REJECTED)
    with pytest.raises(ValueError):
        lifecycle.apply_transition(row, "schedule_interview")


def test_illegal_transition_from_offer_is_rejected():
    row = _row(STATUS_OFFER)
    with pytest.raises(ValueError):
        lifecycle.apply_transition(row, "reject")


def test_illegal_transition_from_skipped_is_rejected():
    row = _row(STATUS_SKIPPED)
    with pytest.raises(ValueError):
        lifecycle.apply_transition(row, "send")
