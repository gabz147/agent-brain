"""Context output stays small without weakening the shared writer."""
import json
import subprocess
import sys

from test_vault import Fixture, SECTIONS
import vault_core as core
import vault_sources as sources
from vaultctl import daily_context, main, receipt_summary


class ContextTests(Fixture):
    def test_daily_locator_is_read_only_and_omits_long_bodies(self):
        _, path = self.daily()
        sections = dict(SECTIONS, **{"What Got Done": ["Large evidence " * 20000]})
        op = core.daily_operation(self.vault, "2026-09-05", "4:42 PM", "Second", sections,
                                  "astra", "<!-- second -->", "Verify second")
        self.vault.commit([op], "astra", "fixture")
        before = self.vault.path(path).read_bytes()
        result = daily_context(self.vault, path)
        self.assertEqual(len(result["sessions"]), 2)
        self.assertEqual(result["sha256"], core.sha(before))
        self.assertIn("Verify second", result["open_next"])
        self.assertLess(len(json.dumps(result)), 1200)
        for row in result["sessions"]:
            self.assertEqual(before.decode().splitlines()[row["line"] - 1], row["heading"])
        self.assertEqual(before, self.vault.path(path).read_bytes())

    def test_missing_daily_and_invalid_paths(self):
        result = daily_context(self.vault, core.daily_path("2026-09-06"))
        self.assertFalse(result["exists"])
        self.assertIsNone(result["sha256"])
        for path in ("note.md", "../2026-09-06.md", "09 - Archive/Old Memory/2026-09-06.md"):
            with self.assertRaises(core.VaultError):
                daily_context(self.vault, path)

    def test_daily_locator_skips_fenced_examples_and_rejects_bad_schema(self):
        _, path = self.daily()
        file = self.vault.path(path)
        file.write_text(file.read_text(encoding="utf-8") + "\n```md\n## Session 999 example\n```\n", encoding="utf-8")
        self.assertEqual(len(daily_context(self.vault, path)["sessions"]), 1)
        file.write_text("bad schema", encoding="utf-8")
        with self.assertRaises(core.VaultError):
            daily_context(self.vault, path)

    def test_real_cli_summary_keeps_complete_verified_receipt_and_retry(self):
        transcript = self.transcript()
        units = list(sources.stream_units(transcript, "codex", "session-1"))
        payload = self.base / "payload.json"
        payload.write_text(json.dumps(self.proposal(units)), encoding="utf-8")
        args = ["--vault", str(self.vault.root), "--state", str(self.vault.state),
                "--backups", str(self.vault.backups), "checkpoint", "--source", "codex",
                "--session", "session-1", "--transcript", str(transcript), "--input", str(payload)]
        child = subprocess.run([sys.executable, str(core.HERE / "vaultctl.py"), *args, "--summary"],
                               capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        summary = json.loads(child.stdout)
        receipt = sources.verified_receipts(self.vault, "codex", "session-1")[0]
        self.assertEqual(summary, receipt_summary(receipt))
        self.assertTrue(receipt["ranges"])
        self.assertIn("### What Got Done", receipt["anchors"][0]["text"])
        daily = self.vault.path(receipt["anchors"][0]["path"])
        before = daily.read_bytes()
        self.assertEqual(main(args)["id"], summary["id"])
        self.assertEqual(before, daily.read_bytes())
        with self.assertRaises(core.VaultError):
            self.vault.commit([{"path": str(daily), "expected_sha256": core.sha(before),
                                "edits": [{"old": "Verified the tested change.", "new": "Rewrite history"}]}],
                              "astra", "must fail")
