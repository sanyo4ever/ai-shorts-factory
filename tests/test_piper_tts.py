from filmstudio.services.piper_tts import normalize_text_for_piper


def test_normalize_text_for_piper_transliterates_ukrainian_latin_text() -> None:
    normalized = normalize_text_for_piper(
        "Pryvit, yak spravy?",
        language="uk",
    )
    assert normalized.normalized_text == "привіт, як справи?"
    assert normalized.changed is True
    assert normalized.kind == "uk_latn_to_cyrl+lowercase"


def test_normalize_text_for_piper_keeps_cyrillic_text() -> None:
    normalized = normalize_text_for_piper(
        "Привіт, як справи?",
        language="uk",
    )
    assert normalized.normalized_text == "привіт, як справи?"
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
