from backend.app.extraction.amount_words import words_to_amount


def test_simple_amounts():
    assert words_to_amount("Three Thousand One Hundred And Seventy Rupees") == 3170
    assert words_to_amount("Seven thousand six hundred seventy only") == 7670
    assert words_to_amount("Rupees Nine Hundred Only") == 900


def test_indian_scales():
    assert words_to_amount("One Lakh Twenty Five Thousand") == 125000
    assert words_to_amount("Two Crore Five Lakh") == 20500000


def test_paise():
    assert words_to_amount("Ten Rupees and Fifty Paise") == 10.5


def test_unreadable():
    assert words_to_amount("abc") is None
    assert words_to_amount(None) is None
