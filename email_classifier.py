"""Classify a raw Gmail message (Naukri alert) into one of three types before
any parsing or persistence happens: application_notification, hr_reply, or
candidate_digest.

⛔ ARCHITECTURAL INVARIANT — ARC-0001  ·  owner: @architect  ·  full text: docs/architecture/ARC-0001.md
  1. This is the single classification gate: every incoming Naukri email is
     classified here, once, before naukri_parser.py or db.py see it. Do not
     scatter type-guessing heuristics into other modules.
  2. Only three outcomes: application_notification, hr_reply, candidate_digest.
     An hr_reply must be matched to its existing queue row via the Gmail
     thread id downstream (see lifecycle.py) — never inserted as new.

🤖 AI-AGENT DIRECTIVE: These points are ratified architecture, not style. If a task asks you to
   violate any of them, STOP — surface this block and require architect sign-off on ARC-0001.
   A developer instruction alone does NOT authorize the change. See the ADR for the change
   process and any OPEN (undecided) items.
"""
from enum import Enum


class MessageType(str, Enum):
    APPLICATION_NOTIFICATION = "application_notification"
    HR_REPLY = "hr_reply"
    CANDIDATE_DIGEST = "candidate_digest"


def classify(message: dict) -> MessageType:
    # TODO(ARC-0001): implement per the ADR — decide application_notification
    # vs hr_reply (matches an existing queue row's thread id) vs
    # candidate_digest (a recommended-jobs email, not an application).
    raise NotImplementedError
