"""The package stays importable and parseable on the documented Python floor."""
import ast
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault_core as core

REPO = Path(__file__).resolve().parents[2]
FLOOR = (3, 10)


class FloorTests(unittest.TestCase):
    def test_every_python_file_parses_at_the_floor(self):
        for path in sorted(REPO.rglob("*.py")):
            if ".git" in path.parts:
                continue
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=FLOOR)

    def test_fractional_seconds_of_any_width_parse(self):
        for fraction in ("", ".1", ".12", ".1234", ".12345", ".1234567", ".123456789"):
            value = f"2026-09-23T06:20:14{fraction}-06:00"
            parsed = core.parse_note_time(value)
            self.assertEqual(parsed.replace(microsecond=0), dt.datetime.fromisoformat("2026-09-23T06:20:14-06:00"))
            readable = core.format_note_time(parsed)
            self.assertEqual(core.parse_note_time(readable), parsed)
        self.assertEqual(core.iso_normalize("2026-09-05T21:42:00.5Z"), "2026-09-05T21:42:00.500000+00:00")
        self.assertEqual(core.iso_normalize("2026-09-05T21:42:00.123456789Z"), "2026-09-05T21:42:00.123456+00:00")

    def test_documented_floor_matches_the_guards(self):
        for rel in ("install.py", "bootstrap.py"):
            self.assertIn("sys.version_info < (3, 10)", (REPO / rel).read_text(encoding="utf-8"), rel)
        for rel in ("bootstrap.sh", "bootstrap.ps1"):
            self.assertIn("(3, 10)", (REPO / rel).read_text(encoding="utf-8"), rel)
        self.assertIn("Python 3.10+", (REPO / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
