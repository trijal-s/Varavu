from eval.compare import compare_value


def test_numbers_within_half_rupee():
    assert compare_value(2300, 2300.0) == "correct"
    assert compare_value(2300, 2300.4) == "correct"
    assert compare_value(2300, 2301) == "wrong"


def test_text_ignores_case_and_spaces():
    assert compare_value("PREET PALACE", "Preet  Palace") == "correct"


def test_empty_outcomes():
    assert compare_value(None, "") == "both_empty"
    assert compare_value(840, None) == "missed"
    assert compare_value(None, 0.0) == "invented"
    assert compare_value("unknown", "cash") == "invented"
