import tempfile
from pathlib import Path
import unittest

from entry_tagger import EntryTagger
from recommender import build_recommendation


class GuardrailInvariantTest(unittest.TestCase):
    def test_validator_gui_ineligible_and_boot_timeout_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gui").mkdir(parents=True, exist_ok=True)
            (root / "godotengain/engainos").mkdir(parents=True, exist_ok=True)

            (root / "check_boundaries_precise.py").write_text("def run():\n    return True\n")
            (root / "gui/old_zw_gui_enhanced.py").write_text("import tkinter\n")
            (root / "godotengain/engainos/launch_engine.py").write_text(
                "import socket\n"
                "if __name__ == '__main__':\n"
                "    print('boot')\n"
            )

            chosen = [
                {
                    "path": "check_boundaries_precise.py",
                    "coverage": {"cover_ratio": 0.9},
                    "in_engine_scope": False,
                },
                {
                    "path": "gui/old_zw_gui_enhanced.py",
                    "coverage": {"cover_ratio": 0.8},
                    "in_engine_scope": False,
                },
                {
                    "path": "godotengain/engainos/launch_engine.py",
                    "coverage": {"cover_ratio": 0.7},
                    "in_engine_scope": True,
                    "trace_timed_out": True,
                    "trace_mode": "import-only",
                },
            ]

            tagger = EntryTagger(root, {"chosen": chosen})
            tagged = {e["path"]: e for e in tagger.tag_all()}

            self.assertFalse(tagged["check_boundaries_precise.py"]["eligible_for_primary"])
            self.assertFalse(tagged["gui/old_zw_gui_enhanced.py"]["eligible_for_primary"])
            self.assertTrue(tagged["godotengain/engainos/launch_engine.py"]["eligible_for_primary"])

            rec = build_recommendation(tagged["godotengain/engainos/launch_engine.py"])
            self.assertEqual(rec["label"], "low-confidence")
            self.assertIn("timeout/import-only", rec["guidance"])
            self.assertNotEqual(rec["label"], "confirmed")


if __name__ == "__main__":
    unittest.main()
