"""Email classifier — fast keyword heuristics, no LLM."""

from __future__ import annotations

import re
from enum import Enum


class EmailCategory(Enum):
    ACTIONABLE = "actionable"
    FYI = "fyi"
    SPAM = "spam"


# Spam patterns (subject or body)
_SPAM_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"(lottery|sweepstakes|you\s+won|congratulations.*winner)",
        r"(pharmacy|viagra|cialis|pills|medication\s+offer)",
        r"(nigerian|prince|inheritance|million\s+dollars)",
        r"(click\s+here\s+now|act\s+now|limited\s+time\s+offer)",
        r"(unsubscribe|bulk\s+mail|mass\s+mailing)",
    ]
]

# FYI sender patterns
_FYI_SENDER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"no-?reply@",
        r"noreply@",
        r"notifications?@",
        r"mailer-daemon@",
        r"postmaster@",
    ]
]

# FYI subject patterns
_FYI_SUBJECT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^(FYI|FW|Fwd):",
        r"newsletter",
        r"notification",
        r"digest",
        r"weekly\s+update",
        r"monthly\s+report",
        r"automated\s+report",
    ]
]


def classify_email(
    sender: str,
    subject: str,
    body: str = "",
    allowed_senders: list[str] | None = None,
) -> EmailCategory:
    """Classify an email using keyword heuristics.

    Args:
        sender: Email address of the sender.
        subject: Email subject line.
        body: Email body text (optional).
        allowed_senders: If non-empty, emails from senders not in this list
            are classified as SPAM.

    Returns:
        EmailCategory indicating the classification.
    """
    # Allowed senders filter
    if allowed_senders:
        sender_lower = sender.lower()
        if not any(s.lower() in sender_lower for s in allowed_senders):
            return EmailCategory.SPAM

    # Spam detection
    text = f"{subject} {body}"
    for pattern in _SPAM_PATTERNS:
        if pattern.search(text):
            return EmailCategory.SPAM

    # FYI: no-reply senders
    for pattern in _FYI_SENDER_PATTERNS:
        if pattern.search(sender):
            return EmailCategory.FYI

    # FYI: subject patterns
    for pattern in _FYI_SUBJECT_PATTERNS:
        if pattern.search(subject):
            return EmailCategory.FYI

    return EmailCategory.ACTIONABLE
