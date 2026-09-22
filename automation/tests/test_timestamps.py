"""Write times are automatic, timezone-aware and compatible with old notes."""
import datetime as dt
from unittest.mock import patch

from test_vault import Fixture, HEADER, SECTIONS
import vault_core as core


class TimestampTests(Fixture):
    def test_legacy_dates_and_explicit_timezones(self):
        for value in ("2026-08-01", "2026-09-22T18:04:05-06:00",
                      "2026-09-22T18:04:05+05:30", "2026-09-23T00:04:05Z"):
            with self.subTest(value=value):
                self.assertEqual(core.validate(HEADER.replace("2026-08-01", value)), [])
        for value in ("2026-02-29T18:04:05-06:00", "2026-09-22T25:04:05Z",
                      "2026-09-22T18:04:05", "2026-09-22T18:04-06:00",
                      "2026-09-22T18:04:05+25:00", "2026-09-22T18:04:05+05:99"):
            with self.subTest(value=value):
                self.assertTrue(core.validate(HEADER.replace("2026-08-01", value)))

    def test_write_update_noop_and_replay_times(self):
        first = dt.datetime.fromisoformat("2026-09-22T18:04:05-06:00")
        later = first + dt.timedelta(minutes=7)
        op = {"path": "reference.md", "expected_sha256": None,
              "content": HEADER + "\nOriginal\n"}
        with patch.object(core, "now", return_value=first):
            self.vault.commit([op], "astra", "create", transaction_id="timestamp-create")
        info = self.vault.inspect("reference.md")
        self.assertEqual(core.frontmatter(info["text"])[0]["updated"], first.isoformat())
        with patch.object(core, "now", return_value=later):
            self.vault.commit([op], "astra", "create", transaction_id="timestamp-create")
            result = self.vault.commit([dict(op, expected_sha256=info["sha256"],
                                            content=info["text"])], "astra", "no change")
            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(self.vault.inspect("reference.md"), info)
            self.vault.commit([{"path": "reference.md", "expected_sha256": info["sha256"],
                                "edits": [{"old": "Original", "new": "Changed"}]}], "opus 5", "edit")
        fields, _ = core.frontmatter(self.vault.inspect("reference.md")["text"])
        self.assertEqual(fields["updated"], later.isoformat())
        self.assertEqual(fields["updated_by"], "opus 5")
        self.assertEqual(set(fields), set(core.SCHEMA["required"]))

    def test_daily_backfill_uses_write_time_and_preserves_history(self):
        at = dt.datetime.fromisoformat("2026-09-22T18:04:05-06:00")
        with patch.object(core, "now", return_value=at):
            _, path = self.daily(day="2026-09-05")
        before = self.vault.inspect(path)["text"]
        old_sessions = before[before.index("## Session"):]
        with patch.object(core, "now", return_value=at + dt.timedelta(hours=1)):
            op = core.daily_operation(self.vault, "2026-09-05", "4:42 PM", "Later event",
                                      SECTIONS, "astra", "<!-- timestamp-second -->")
            self.vault.commit([op], "astra", "append")
        after = self.vault.inspect(path)["text"]
        self.assertEqual(core.frontmatter(after)[0]["updated"], "2026-09-22T19:04:05-06:00")
        self.assertIn("# Saturday, September 5, 2026", after)
        self.assertTrue(after[after.index("## Session"):].startswith(old_sessions))
