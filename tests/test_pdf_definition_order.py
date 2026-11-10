"""Displaced formula labels require unique matching visual definitions."""
from test_pdf_validation import URL
from app.services.pdf_validation_layout import repair_definition_labels
from app.services.pdf_validation_worker import compare_documents


TEXT = "A\nB\nC\n25 (1) The range of penalties applies to each violation.\nis the base penalty.\nis the multiplier.\nis the daily amount."
RUNS = [(48, 300, "A", 12), (64, 300, "is the base penalty.", 12),
        (48, 220, "B", 12), (64, 220, "is the multiplier.", 12),
        (48, 140, "C", 12), (64, 140, "is the daily amount.", 12)]


def test_labels_move_to_their_unique_visual_definitions():
    text, changed = repair_definition_labels(TEXT, RUNS)
    assert changed and text.startswith("25 (1)")
    assert "A is the base penalty." in text and "B is the multiplier." in text and "C is the daily amount." in text


def test_ambiguous_or_unpositioned_labels_are_preserved():
    assert repair_definition_labels(TEXT, RUNS + [(48, 100, "A", 12)]) == (TEXT, False)
    assert repair_definition_labels(TEXT, RUNS[:-1]) == (TEXT, False)


def test_real_formula_letter_changes_are_still_compared():
    expected, _ = repair_definition_labels(TEXT, RUNS)
    actual, _ = repair_definition_labels(TEXT.replace("A\n", "X\n", 1),
        [(x, y, "X" if value == "A" else value, size) for x, y, value, size in RUNS])
    def document(text):
        return {"title": "Synthetic Regulations", "complete": True, "units": [{"text": "Synthetic Regulations\n" + text, "page": 1}]}
    result = compare_documents(document(actual), document(expected), URL)
    assert result["status"] == "mismatch" and len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["expected"][slice(*finding["expected_change"])] == "A"
    assert finding["actual"][slice(*finding["actual_change"])] == "X"
