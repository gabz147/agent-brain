"""Context output stays small without weakening the shared writer."""
import json
import subprocess
import sys

from test_vault import Fixture, HEADER, SECTIONS
import vault_core as core
import vault_sources as sources
from vault_recall import session_brief
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

    def test_session_brief_is_capped_read_only_navigation(self):
        self.assertIn("no vault at", session_brief(self.vault, self.directory))
        (self.vault.root / "VAULT-INDEX.md").write_text(HEADER.replace("type: log", "type: index") + "\n# Map\n", encoding="utf-8")
        self.assertIn("no sessions recorded yet", session_brief(self.vault, self.directory))
        sections = dict(SECTIONS, **{"What Got Done": ["Did the thing"]})
        for time, topic, marker, open_next in (("3:42 PM", "First topic", "<!-- b1 -->", "Finish the adapter"),
                                               ("4:42 PM", "Second topic", "<!-- b2 -->", "Ship it " * 60)):
            op = core.daily_operation(self.vault, "2026-09-05", time, topic, sections, "astra", marker, open_next)
            self.vault.commit([op], "astra", "fixture")
        priorities = self.vault.root / "Active Priorities.md"
        items = "".join(f"- Item {n} " + "detail " * 40 + "`touched: 2026-09-01`\n" for n in range(10))
        priorities.write_text(HEADER + "\n# Active Priorities\n\n## Active Now\n" + items + "\n## Next\n- None\n", encoding="utf-8")
        stale = (core.now() - __import__("datetime").timedelta(days=30)).isoformat()
        (self.directory / "hook-errors.jsonl").write_text(json.dumps({"at": core.now().isoformat(), "hook": "Stop", "error": "x"}) + "\n"
                                                           + json.dumps({"at": stale, "hook": "Stop", "error": "old"}) + "\n" + "not json\n", encoding="utf-8")
        before = {p: p.read_bytes() for p in self.vault.root.rglob("*.md")}
        text = session_brief(self.vault, self.directory)
        self.assertLessEqual(len(text.encode("utf-8")), 700)
        self.assertIn("open: Ship it", text)
        self.assertIn("Last session: Session 2", text)
        self.assertIn("Hook errors: 1 in the last 7 days", text)
        self.assertIn("navigation, not evidence", text)
        self.assertNotIn("touched:", text)
        self.assertEqual(before, {p: p.read_bytes() for p in self.vault.root.rglob("*.md")})
        roomy = session_brief(self.vault, self.directory, cap=4000)
        self.assertIn("Before that: Session 1", roomy)
        self.assertIn("Active Now: Item 0", roomy)
        # Newest by date, not by path: the January folder sorts before December's.
        for day, open_next in (("2026-12-31", "Finish the December task"), ("2027-01-01", "Start the January task")):
            op = core.daily_operation(self.vault, day, "3:00 PM", "Turn of the year", sections, "astra", f"<!-- {day} -->", open_next)
            self.vault.commit([op], "astra", "fixture")
        self.assertTrue(session_brief(self.vault, self.directory).startswith("Brain: last day 2027-01-01; open: Start the January task"))
        # A long multibyte Open line still leaves room for the hook-error line under the byte cap.
        op = core.daily_operation(self.vault, "2027-01-02", "3:00 PM", "Wide", sections, "astra", "<!-- wide -->", "\u6f22" * 300)
        self.vault.commit([op], "astra", "fixture")
        wide = session_brief(self.vault, self.directory)
        self.assertLessEqual(len(wide.encode("utf-8")), 700)
        self.assertIn("Hook errors: 1", wide)
        args = ["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups), "session-brief"]
        self.assertIsInstance(main(args), str)
        child = subprocess.run([sys.executable, str(core.HERE / "vaultctl.py"), *args], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertTrue(child.stdout.startswith("Brain: last day 2027-01-02"), child.stdout)
        # An unreadable newest note is reported, never passed off as an empty history.
        broken = self.vault.path(core.daily_path("2027-01-03"))
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_bytes(b"---\nstatus: active\n---\n# Caf\xe9\n")
        self.assertIn("could not read the latest daily note", session_brief(self.vault, self.directory))

    def test_attested_checkpoint_from_flags_for_any_agent(self):
        base = ["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups), "checkpoint"]
        flags = ["--source", "opencode", "--model", "gpt-5.6", "--session", "oc-1", "--topic", "Adapter work",
                 "--done", "Wrote the manifest", "--done", "Ran the fixtures", "--next", "Wire the gate",
                 "--touched", "[[Agent Brain]]", "--open", "Verify on a second machine", "--day", "2026-09-06", "--time", "4:10 PM", "--summary"]
        summary = main(base + flags)
        self.assertEqual(summary["tier"], "attested")
        self.assertEqual(summary["writer_model"], "gpt-5.6")
        self.assertEqual(summary["provider"], "opencode")
        daily = self.vault.path(core.daily_path("2026-09-06"))
        text = daily.read_text(encoding="utf-8")
        self.assertIn("## Session 1 \u2014 4:10 PM: Adapter work \u2014 `gpt-5.6`", text)
        self.assertIn("- Wrote the manifest\n- Ran the fixtures", text)
        self.assertIn("**Open for tomorrow:** Verify on a second machine", text)
        receipt = sources.verified_receipts(self.vault, "opencode", "oc-1")[0]
        self.assertEqual(receipt["id"], summary["id"])
        self.assertEqual(receipt["model_source"], "self-report")
        self.assertEqual(receipt["evidence"][0]["kind"], "attested")
        self.assertEqual(receipt["ranges"], [])
        # Replaying the identical flags returns the same receipt and appends nothing.
        before = daily.read_bytes()
        self.assertEqual(main(base + flags)["id"], summary["id"])
        self.assertEqual(before, daily.read_bytes())
        # A trivial attested turn records a receipt and writes nothing.
        trivial = main(base + ["--source", "opencode", "--model", "gpt-5.6", "--session", "oc-2", "--trivial", "Answered a question from memory"])
        self.assertEqual(trivial["disposition"], "trivial")
        self.assertEqual(before, daily.read_bytes())
        # Guards: no model, flags mixed with JSON, a transcript without its source, an agent name as model.
        with self.assertRaisesRegex(core.VaultError, "--model"):
            main(base + ["--source", "opencode", "--topic", "x", "--done", "y"])
        with self.assertRaisesRegex(core.VaultError, "not both"):
            main(base + ["--source", "opencode", "--model", "gpt-5.6", "--topic", "x", "--done", "y", "--input", "payload.json"])
        with self.assertRaisesRegex(core.VaultError, "--source claude|codex"):
            main(base + ["--transcript", str(self.transcript()), "--topic", "x", "--done", "y"])
        with self.assertRaises(core.VaultError):
            main(base + ["--source", "opencode", "--model", "codex", "--topic", "x", "--done", "y"])

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
