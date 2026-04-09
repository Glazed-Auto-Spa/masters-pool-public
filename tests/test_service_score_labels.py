from __future__ import annotations

import unittest

from app.service import _normalize_event_entry, _score_outcome_key, _score_outcome_label


class TestServiceScoreLabels(unittest.TestCase):
    def test_other_maps_to_shit_ton(self) -> None:
        key = _score_outcome_key(score_type="OTHER", strokes=10, par=4)
        self.assertEqual(key, "SHIT_TON")
        self.assertEqual(_score_outcome_label(key), "Shit Ton")

    def test_snowman_detected_by_eight_strokes(self) -> None:
        key = _score_outcome_key(score_type="", strokes=8, par=5)
        self.assertEqual(key, "SNOWMAN")
        self.assertEqual(_score_outcome_label(key), "Snowman")

    def test_quad_detected_by_plus_four(self) -> None:
        key = _score_outcome_key(score_type="", strokes=9, par=5)
        self.assertEqual(key, "QUAD")
        self.assertEqual(_score_outcome_label(key), "Quad")

    def test_normalize_event_entry_rewrites_legacy_other_label(self) -> None:
        entry = {"message": "Fred Couples Other on hole 15 (R1).", "type": "movement", "causal": True}
        normalized = _normalize_event_entry(entry)
        self.assertEqual(normalized["message"], "Fred Couples Shit Ton on hole 15 (R1).")


if __name__ == "__main__":
    unittest.main()
