from app.conversations.titles import derive_title


class TestDeriveTitle:
    def test_short_message_returns_whole(self) -> None:
        result = derive_title("Hola Flora", 48)
        assert result == "Hola Flora"

    def test_message_exactly_at_cap_returns_whole(self) -> None:
        msg = "A" * 48
        result = derive_title(msg, 48)
        assert result == msg
        assert not result.endswith("…")

    def test_long_message_truncates_at_word_boundary(self) -> None:
        msg = "Hola Flora, ¿cómo va mi Monstera? Necesito saber más cosas sobre cómo cuidarla bien."
        result = derive_title(msg, 48)
        assert result is not None
        assert len(result) <= 51  # 48 + "…" at most
        assert result.endswith("…")
        assert not result.rstrip("…").endswith(" ")
        split_pos = result.rstrip("…").rfind(" ")
        assert split_pos > 0

    def test_no_spaces_longer_than_cap(self) -> None:
        msg = "PalabraMuyLargaSinEspaciosParaProbarQueNoHayDondeCortar"
        result = derive_title(msg, 10)
        assert result is not None
        assert len(result) <= 11
        assert result.endswith("…")

    def test_empty_string_returns_none(self) -> None:
        assert derive_title("", 48) is None

    def test_whitespace_only_returns_none(self) -> None:
        assert derive_title("   ", 48) is None

    def test_message_fits_exactly_at_cap_word_boundary(self) -> None:
        msg = "Hola como estas"  # 16 chars
        result = derive_title(msg, 16)
        assert result == msg
        assert not result.endswith("…")
