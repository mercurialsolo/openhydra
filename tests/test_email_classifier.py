"""Tests for email classification heuristics."""

from __future__ import annotations

from openhydra.channels.email.classifier import EmailCategory, classify_email


class TestClassifySpam:
    def test_lottery_spam(self):
        result = classify_email(
            sender="scam@example.com",
            subject="You won the lottery!",
            body="Congratulations winner!",
        )
        assert result == EmailCategory.SPAM

    def test_pharmacy_spam(self):
        result = classify_email(
            sender="pills@example.com",
            subject="Cheap Viagra pills",
        )
        assert result == EmailCategory.SPAM

    def test_nigerian_prince(self):
        result = classify_email(
            sender="prince@example.com",
            subject="Urgent: Nigerian inheritance",
            body="I am a Nigerian prince with a million dollars",
        )
        assert result == EmailCategory.SPAM

    def test_allowed_senders_filter(self):
        result = classify_email(
            sender="unknown@evil.com",
            subject="Hello",
            allowed_senders=["friend@good.com"],
        )
        assert result == EmailCategory.SPAM

    def test_allowed_sender_passes(self):
        result = classify_email(
            sender="friend@good.com",
            subject="Hello",
            allowed_senders=["friend@good.com"],
        )
        assert result == EmailCategory.ACTIONABLE

    def test_allowed_sender_substring_match(self):
        result = classify_email(
            sender="John <friend@good.com>",
            subject="Hello",
            allowed_senders=["friend@good.com"],
        )
        assert result == EmailCategory.ACTIONABLE


class TestClassifyFyi:
    def test_noreply_sender(self):
        result = classify_email(
            sender="noreply@github.com",
            subject="New commit pushed",
        )
        assert result == EmailCategory.FYI

    def test_no_reply_with_dash(self):
        result = classify_email(
            sender="no-reply@service.com",
            subject="Your receipt",
        )
        assert result == EmailCategory.FYI

    def test_notifications_sender(self):
        result = classify_email(
            sender="notifications@slack.com",
            subject="New message",
        )
        assert result == EmailCategory.FYI

    def test_fyi_subject(self):
        result = classify_email(
            sender="colleague@work.com",
            subject="FYI: Project update",
        )
        assert result == EmailCategory.FYI

    def test_newsletter_subject(self):
        result = classify_email(
            sender="news@blog.com",
            subject="Weekly Newsletter - Issue 42",
        )
        assert result == EmailCategory.FYI

    def test_notification_subject(self):
        result = classify_email(
            sender="system@corp.com",
            subject="Notification: Build completed",
        )
        assert result == EmailCategory.FYI


class TestClassifyActionable:
    def test_normal_email(self):
        result = classify_email(
            sender="boss@company.com",
            subject="Please review this PR",
            body="Can you take a look at the changes?",
        )
        assert result == EmailCategory.ACTIONABLE

    def test_empty_body(self):
        result = classify_email(
            sender="user@example.com",
            subject="Quick question",
        )
        assert result == EmailCategory.ACTIONABLE

    def test_empty_allowed_senders_allows_all(self):
        result = classify_email(
            sender="anyone@anywhere.com",
            subject="Hello",
            allowed_senders=[],
        )
        assert result == EmailCategory.ACTIONABLE

    def test_none_allowed_senders_allows_all(self):
        result = classify_email(
            sender="anyone@anywhere.com",
            subject="Hello",
            allowed_senders=None,
        )
        assert result == EmailCategory.ACTIONABLE
