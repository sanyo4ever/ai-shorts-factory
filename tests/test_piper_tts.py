from filmstudio.services.piper_tts import normalize_text_for_piper


def test_normalize_text_for_piper_transliterates_ukrainian_latin_text() -> None:
    normalized = normalize_text_for_piper(
        "Pryvit, yak spravy?",
        language="uk",
    )

    assert normalized.normalized_text == "\u043f\u0440\u0438\u0432\u0456\u0442, \u044f\u043a \u0441\u043f\u0440\u0430\u0432\u0438?"
    assert normalized.changed is True
    assert normalized.kind == "uk_latn_to_cyrl+lowercase"


def test_normalize_text_for_piper_keeps_cyrillic_text() -> None:
    normalized = normalize_text_for_piper(
        "\u041f\u0440\u0438\u0432\u0456\u0442, \u044f\u043a \u0441\u043f\u0440\u0430\u0432\u0438?",
        language="uk",
    )

    assert normalized.normalized_text == "\u043f\u0440\u0438\u0432\u0456\u0442, \u044f\u043a \u0441\u043f\u0440\u0430\u0432\u0438?"
    assert normalized.changed is True
    assert normalized.kind == "lowercase"


def test_normalize_text_for_piper_leaves_non_uk_text_unchanged() -> None:
    normalized = normalize_text_for_piper(
        "Hello there",
        language="en",
    )

    assert normalized.normalized_text == "Hello there"
    assert normalized.changed is False
    assert normalized.kind == "identity"


def test_normalize_text_for_piper_repairs_utf8_mojibake_before_lowercasing() -> None:
    mojibake = "\u041f\u0440\u0438\u0432\u0456\u0442, \u0442\u0430\u0442\u0443!".encode("utf-8").decode("latin1")

    normalized = normalize_text_for_piper(
        mojibake,
        language="uk",
    )

    assert normalized.normalized_text == "\u043f\u0440\u0438\u0432\u0456\u0442, \u0442\u0430\u0442\u0443!"
    assert normalized.changed is True
    assert normalized.kind == "utf8_mojibake_repair+lowercase"


def test_normalize_text_for_piper_strips_guillemets_for_ukrainian_tts() -> None:
    normalized = normalize_text_for_piper(
        "\u00ab\u0421\u0438\u043d\u0443, \u0433\u043e\u0442\u043e\u0432\u0438\u0439?\u00bb",
        language="uk",
    )

    assert normalized.normalized_text == "\u0441\u0438\u043d\u0443, \u0433\u043e\u0442\u043e\u0432\u0438\u0439?"
    assert normalized.changed is True
    assert normalized.kind == "strip_quotes+lowercase"
