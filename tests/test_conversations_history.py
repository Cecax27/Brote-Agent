from datetime import UTC, datetime

from app.conversations.history import format_history_block, trim_to_budget
from app.conversations.models import Message

DT = datetime(2025, 7, 29, 12, 0, 0, tzinfo=UTC)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, created_at=DT)  # type: ignore[arg-type]


class TestFormatHistoryBlock:
    def test_empty_for_no_messages(self) -> None:
        assert format_history_block([]) == ""

    def test_labels_are_correct(self) -> None:
        msgs = [_msg("user", "Hola"), _msg("assistant", "¡Hola!")]
        block = format_history_block(msgs)
        assert "Usuario: Hola" in block
        assert "Flora: ¡Hola!" in block
        assert block.startswith("Historial de la conversación")

    def test_order_is_chronological(self) -> None:
        msgs = [_msg("user", "Primero"), _msg("assistant", "Segundo")]
        block = format_history_block(msgs)
        pos_user = block.index("Primero")
        pos_asst = block.index("Segundo")
        assert pos_user < pos_asst

    def test_skips_empty_content(self) -> None:
        msgs = [_msg("user", ""), _msg("assistant", "Respuesta")]
        block = format_history_block(msgs)
        assert "Usuario:" not in block
        assert "Flora: Respuesta" in block

    def test_empty_when_all_messages_empty(self) -> None:
        msgs = [_msg("user", "   "), _msg("assistant", "")]
        assert format_history_block(msgs) == ""


class TestTrimToBudget:
    def test_returns_all_when_under_budget(self) -> None:
        msgs = [_msg("user", "A"), _msg("assistant", "B")]
        result = trim_to_budget(msgs, max_messages=10, max_chars=100)
        assert len(result) == 2

    def test_drops_oldest_first_for_message_cap(self) -> None:
        msgs = [
            _msg("user", "A"),
            _msg("assistant", "B"),
            _msg("user", "C"),
        ]
        result = trim_to_budget(msgs, max_messages=2, max_chars=1000)
        assert len(result) == 2
        assert result[0].content == "B"
        assert result[1].content == "C"

    def test_drops_oldest_first_for_char_cap(self) -> None:
        msgs = [
            _msg("user", "A" * 30),
            _msg("assistant", "B" * 30),
            _msg("user", "C" * 20),
        ]
        result = trim_to_budget(msgs, max_messages=10, max_chars=55)
        assert len(result) == 2
        assert result[0].content == "B" * 30
        assert result[1].content == "C" * 20

    def test_most_recent_always_survives(self) -> None:
        msgs = [
            _msg("user", "X" * 1000),
            _msg("assistant", "Y"),
        ]
        result = trim_to_budget(msgs, max_messages=10, max_chars=50)
        assert len(result) == 1
        assert result[0].content == "Y"
