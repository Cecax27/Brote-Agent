import os
import time
from unittest.mock import patch

import pytest

from app.actions.models import AddJournalEntryPayload, CreateWateringSchedulePayload
from app.actions.models import payload_digest
from app.actions.registry import resolve_action
from app.actions.tokens import (
    InvalidActionError,
    TokenAuthError,
    _nonce_store,
    issue_confirm_token,
    verify_confirm_token,
)

SIGNING_SECRET = "test-signing-secret"


class TestPayloadDigest:
    def test_stable_output(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        a = payload_digest(payload, "plant-1")
        b = payload_digest(payload, "plant-1")
        assert a == b

    def test_changes_with_payload(self) -> None:
        a = payload_digest({"freq": 1}, "p1")
        b = payload_digest({"freq": 2}, "p1")
        assert a != b

    def test_changes_with_plant_id(self) -> None:
        p = {"freq": 1}
        a = payload_digest(p, "p1")
        b = payload_digest(p, "p2")
        assert a != b


class TestResolveAction:
    def test_resolve_watering_schedule(self) -> None:
        spec = resolve_action("create_watering_schedule")
        assert spec is not None
        assert spec.action_type == "create_watering_schedule"
        assert spec.table == "watering_schedules"
        assert spec.operation == "insert"

    def test_resolve_journal_entry(self) -> None:
        spec = resolve_action("add_journal_entry")
        assert spec is not None
        assert spec.table == "journal_entries"

    def test_unknown_action_returns_none(self) -> None:
        assert resolve_action("delete_plant") is None
        assert resolve_action("") is None


class TestCreateWateringSchedulePayload:
    def test_valid(self) -> None:
        p = CreateWateringSchedulePayload(
            frequency_days=7,
            next_due_at="2025-06-01T00:00:00Z",
        )
        assert p.frequency_days == 7

    def test_rejects_zero_frequency(self) -> None:
        with pytest.raises(Exception):
            CreateWateringSchedulePayload(frequency_days=0, next_due_at="2025-06-01T00:00:00Z")

    def test_rejects_negative_frequency(self) -> None:
        with pytest.raises(Exception):
            CreateWateringSchedulePayload(
                frequency_days=-1, next_due_at="2025-06-01T00:00:00Z"
            )


class TestAddJournalEntryPayload:
    def test_valid(self) -> None:
        p = AddJournalEntryPayload(content="Riega cada 7 días")
        assert p.content == "Riega cada 7 días"

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(Exception):
            AddJournalEntryPayload(content="")


class TestConfirmToken:
    def teardown_method(self) -> None:
        _nonce_store.clear()

    def test_valid_round_trip(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule",
            "plant-1",
            payload,
            "user-1",
            SIGNING_SECRET,
        )
        verify_confirm_token(
            token,
            "create_watering_schedule",
            "plant-1",
            payload,
            "user-1",
            SIGNING_SECRET,
        )

    def test_tampered_signature_raises(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule", "plant-1", payload, "user-1", SIGNING_SECRET
        )
        tampered = token[:-3] + "XXX"
        with pytest.raises(TokenAuthError):
            verify_confirm_token(
                tampered,
                "create_watering_schedule",
                "plant-1",
                payload,
                "user-1",
                SIGNING_SECRET,
            )

    def test_sub_mismatch_raises(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule", "plant-1", payload, "user-1", SIGNING_SECRET
        )
        with pytest.raises(TokenAuthError):
            verify_confirm_token(
                token,
                "create_watering_schedule",
                "plant-1",
                payload,
                "user-2",
                SIGNING_SECRET,
            )

    def test_expired_token_raises(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule",
            "plant-1",
            payload,
            "user-1",
            SIGNING_SECRET,
            ttl_seconds=0,
        )
        time.sleep(0.01)
        with pytest.raises(TokenAuthError):
            verify_confirm_token(
                token,
                "create_watering_schedule",
                "plant-1",
                payload,
                "user-1",
                SIGNING_SECRET,
            )

    def test_replay_after_consume_raises(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule", "plant-1", payload, "user-1", SIGNING_SECRET
        )
        verify_confirm_token(
            token, "create_watering_schedule", "plant-1", payload, "user-1", SIGNING_SECRET
        )
        with pytest.raises(TokenAuthError):
            verify_confirm_token(
                token,
                "create_watering_schedule",
                "plant-1",
                payload,
                "user-1",
                SIGNING_SECRET,
            )

    def test_payload_altered_raises_invalid_action(self) -> None:
        payload = {"frequency_days": 7, "next_due_at": "2025-06-01T00:00:00Z"}
        token = issue_confirm_token(
            "create_watering_schedule", "plant-1", payload, "user-1", SIGNING_SECRET
        )
        altered = {"frequency_days": 7, "next_due_at": "2025-06-02T00:00:00Z"}
        # Payload hash won't match → TokenAuthError (bad signature)
        with pytest.raises(TokenAuthError):
            verify_confirm_token(
                token,
                "create_watering_schedule",
                "plant-1",
                altered,
                "user-1",
                SIGNING_SECRET,
            )
