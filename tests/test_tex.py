"""Signes des PDF LaTeX : puces, « × », « œ » et signes mathématiques à la traduction."""

from iris import translate
from iris.pdf_text import TEX_CHARACTERS, tex_font_characters


def test_symbol_font_and_text_font_read_the_same_code_differently():
    bullet, times = chr(0x88), chr(0xD6)
    spans = [
        ("F47", bullet + times),
        ("F42", "manoeuvre " + chr(0xF7)),
        ("F42", "Österreich"),
        ("Charis", chr(0xF7)),
    ]
    fixed = tex_font_characters(spans)
    assert fixed["F47"][times] == "×"
    assert fixed["F47"][bullet] == "•"
    assert fixed["F42"][chr(0xF7)] == "œ"
    assert times not in fixed["F42"]  # un vrai « Ö » reste un « Ö »
    assert "Charis" not in fixed
    assert TEX_CHARACTERS[bullet] == "•"


def test_math_signs_survive_a_model_that_drops_them():
    def forgetful(text):
        return text.replace("∼", "")

    result = translate.protect("Une part de ∼2,4 % du total.", [], forgetful)
    assert "∼2,4 %" in result


def test_english_gets_a_decimal_point_after_a_sign():
    assert translate._SIGNED_DECIMAL.sub(r"\1.\2", "∼23,6 %") == "∼23.6 %"
    assert translate._SIGNED_DECIMAL.sub(r"\1.\2", "∼2 900") == "∼2 900"
