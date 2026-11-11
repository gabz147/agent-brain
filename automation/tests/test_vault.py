import datetime as dt
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CONTRIB = Path(__file__).resolve().parents[2] / "contrib" / "windows-audit"
import vault_core as core
import vault_capture as capture
import vault_sources as sources
import vault_hooks as hooks
import vault_hygiene
from vault_hygiene import age_priorities, hygiene

HEADER = "---\nstatus: active\nproject: personal\ntype: log\nupdated_by: codex\nupdated: 2026-08-01\n---\n"
TEMPLATE = HEADER + "\n# {{date:dddd, MMMM D, YYYY}}\n\n**Open for tomorrow:** None\n\n## Index\n\n## Session 1 — {{time:h:mm A}}: Manual entry — `human`\n"
SECTIONS = {key: ["None"] for key in core.SCHEMA["daily_sections"]}
SECTIONS["What Got Done"] = ["Verified the tested change."]


def uncovered(vault, path, provider, session_id):
    """Transcript units no verified receipt covers: what a coverage check of that session would still owe."""
    covered = {unit for receipt in sources.verified_receipts(vault, provider, session_id) for unit in receipt["units"]}
    return [unit for unit in sources.stream_units(path, provider, session_id) if unit["id"] not in covered]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.vault = core.Vault(self.base / "Brain", self.base / "state", self.base / "backups")
        self.vault.root.mkdir()
        self.directory = self.base / "automation"
        self.directory.mkdir()
        template = self.vault.root / "01 - Daily Notes/Daily Note Template.md"
        template.parent.mkdir()
        template.write_text(TEMPLATE, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def daily(self, marker="<!-- vault-capture:one -->", day="2026-09-05", topic="Verified work"):
        op = core.daily_operation(self.vault, day, "3:42 PM", topic, SECTIONS, "astra", marker)
        return self.vault.commit([op], "astra", "test"), op["path"]

    def transcript(self, provider="codex", text="Please verify the working change.", model="gpt-6-astra"):
        path = self.base / (provider + ".jsonl")
        stamp = "2026-09-05T21:42:00Z"
        if provider == "codex":
            rows = [{"type": "session_meta", "timestamp": stamp, "payload": {"id": "session-1"}},
                    {"type": "turn_context", "timestamp": stamp, "payload": {"model": model}},
                    {"type": "event_msg", "timestamp": stamp, "payload": {"type": "user_message", "message": text}},
                    {"type": "response_item", "timestamp": stamp, "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "Verified the working change with evidence."}]}}]
        else:
            rows = [{"type": "user", "timestamp": stamp, "sessionId": "session-1", "origin": {"kind": "human"}, "uuid": "turn-1", "message": {"content": text}},
                    {"type": "assistant", "timestamp": stamp, "sessionId": "session-1", "message": {"model": model, "content": [{"type": "text", "text": "Verified the working change with evidence."}]}}]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def proposal(self, units, disposition="captured"):
        return {"disposition": disposition, "reason": "Verified source contains durable work." if disposition == "captured" else "Read-only explanation without a durable change.",
                "evidence": [{"unit_id": units[0]["id"], "quote": units[0]["text"][:30]}],
                "days": [{"day": units[-1]["day"], "time": units[-1]["time"], "topic": "Verified work", "sections": SECTIONS}] if disposition == "captured" else [],
                "operations": [], "anchors": []}


class SchemaTests(Fixture):
    def test_current_and_historical_signatures(self):
        for signer in ("astra", "opus 5", "sol", "human", "automation", "unknown-model", "claude", "codex"):
            self.assertEqual(core.validate(HEADER.replace("updated_by: codex", "updated_by: " + signer)), [])

    def test_missing_fences(self):
        self.assertTrue(core.validate("# Missing metadata"))
        self.assertTrue(core.validate(HEADER.replace("---\n", "", 1)))

    def test_duplicate_keys(self):
        self.assertTrue(core.validate(HEADER.replace("status: active", "status: active\nstatus: completed")))

    def test_impossible_dates(self):
        for day in ("2026-99-99", "2026-02-29", "2026-9-1"):
            self.assertTrue(core.validate(HEADER.replace("2026-08-01", day)))

    def test_aliases(self):
        for aliases in ('aliases: ["A", "B"]', "aliases:\n  - A\n  - B", "aliases: Alias"):
            self.assertEqual(core.validate(HEADER.replace("status: active", aliases + "\nstatus: active")), [])

    def test_unknown_key_and_daily_pins(self):
        self.assertTrue(core.validate(HEADER.replace("status: active", "status: active\nowner: anyone")))
        self.assertTrue(core.validate(HEADER.replace("project: personal", "project: meta"), "01 - Daily Notes/2026-09-05.md"))

    def test_model_labels(self):
        self.assertEqual(core.model_label("gpt-6-astra"), "gpt-6-astra")  # no shipped label map: the exact lowercase id
        self.assertEqual(core.model_label("claude-opus-5"), "opus 5")
        # A release date, a context suffix and a cloud wrapper are not part of the model.
        self.assertEqual(core.model_label("claude-opus-4-20250514"), "opus 4")
        self.assertEqual(core.model_label("claude-opus-5-5[1m]"), "opus 5.5")
        self.assertEqual(core.model_label("us.anthropic.claude-sonnet-4-5-20250929-v1:0"), "sonnet 4.5")
        self.assertEqual(core.model_label("claude-3-5-sonnet-20241022"), "sonnet 3.5")
        self.assertEqual(core.model_label("claude-sonnet-4-6"), "sonnet 4.6")
        for model in (None, "codex", "claude"):
            with self.assertRaises(core.VaultError):
                core.model_label(model)


class CommitTests(Fixture):
    def test_daily_append_preserves_all_old_session_bytes(self):
        _, path = self.daily()
        before = self.vault.inspect(path)["text"]
        old_sessions = before[before.index("## Session"):].encode()
        op = core.daily_operation(self.vault, "2026-09-05", "4:42 PM", "Later work", SECTIONS, "opus 5", "<!-- vault-capture:two -->")
        self.vault.commit([op], "opus 5", "append")
        after = self.vault.inspect(path)["text"]
        self.assertTrue(after[after.index("## Session"):].encode().startswith(old_sessions))
        self.assertIn("## Session 2", after)
        self.assertIn("updated_by: opus 5", after)
        self.assertEqual(core.parse_note_time(core.frontmatter(after)[0]["updated"]).date(), core.now().date())
        self.assertIn("# Saturday, September 5, 2026", after)

    def test_existing_daily_full_replacement_rejected(self):
        _, path = self.daily()
        info = self.vault.inspect(path)
        with self.assertRaises(core.VaultError):
            self.vault.commit([{"path": path, "expected_sha256": info["sha256"], "content": info["text"]}], "astra", "replace")

    def test_old_session_edit_rejected(self):
        _, path = self.daily()
        info = self.vault.inspect(path)
        with self.assertRaises(core.VaultError):
            self.vault.commit([{"path": path, "expected_sha256": info["sha256"], "edits": [{"old": "### Notes Touched", "new": "### Changed"}]}], "astra", "edit")

    def test_arbitrary_append_rejected(self):
        _, path = self.daily()
        info = self.vault.inspect(path)
        with self.assertRaises(core.VaultError):
            self.vault.commit([{"path": path, "expected_sha256": info["sha256"], "append": "\nRandom correction without a session\n"}], "astra", "bad append")

    def test_path_and_frozen_containment(self):
        for path in ("../escape.md", str(self.base / "outside.md"), "09 - Archive/Old Memory/frozen.md", ".obsidian/config.md", "script.py"):
            with self.assertRaises(core.VaultError):
                self.vault.path(path)

    def test_compare_and_swap_conflict(self):
        _, path = self.daily()
        op = core.daily_operation(self.vault, "2026-09-05", "4:42 PM", "Later work", SECTIONS, "astra", "<!-- vault-capture:two -->")
        with self.vault.path(path).open("ab") as out:
            out.write(b"\n")
        with self.assertRaises(core.Conflict):
            self.vault.commit([op], "astra", "conflict")

    def test_marker_idempotence(self):
        self.daily()
        self.assertIsNone(core.daily_operation(self.vault, "2026-09-05", "3:42 PM", "Verified work", SECTIONS, "astra", "<!-- vault-capture:one -->"))

    def test_snapshot_restore_exact_bytes_and_saves_current(self):
        path = self.vault.root / "reference.md"
        before = ("\ufeff" + HEADER.replace("\n", "\r\n") + "Original\r\n").encode("utf-8")
        path.write_bytes(before)
        result = self.vault.commit([{"path": "reference.md", "expected_sha256": core.sha(before), "edits": [{"old": "Original", "new": "Updated"}]}], "astra", "update")
        current = path.read_bytes()
        restore = self.vault.restore(result["transaction_id"], "reference.md", core.sha(current))
        self.assertEqual(path.read_bytes(), before)
        snapshot = json.loads((self.vault.backups / restore["transaction_id"] / "manifest.json").read_text())
        self.assertEqual((self.vault.backups / restore["transaction_id"] / snapshot["files"][0]["before"]).read_bytes(), current)

    def test_partial_commit_resume(self):
        operations = [{"path": name, "expected_sha256": None, "content": HEADER + name} for name in ("one.md", "two.md")]
        real = core.atomic_bytes
        def fail_second(path, data):
            if Path(path) == self.vault.root / "two.md":
                raise OSError("injected disk error")
            return real(path, data)
        with patch.object(core, "atomic_bytes", side_effect=fail_second):
            with self.assertRaises(core.VaultError) as stopped:
                self.vault.commit(operations, "astra", "partial", "test-transaction")
        # The error names the transaction, and hygiene keeps reporting it until it is finished.
        self.assertIn("stopped after 1 of 2 notes", str(stopped.exception))
        self.assertIn("resume test-transaction", str(stopped.exception))
        self.assertTrue((self.vault.root / "one.md").exists())
        self.assertFalse((self.vault.root / "two.md").exists())
        self.assertEqual([row["transaction_id"] for row in self.vault.unfinished()], ["test-transaction"])
        self.assertIn("Unfinished vault transaction test-transaction", json.dumps(hygiene(self.vault, check_parity=False)["issues"]))
        result = self.vault.resume("test-transaction")
        self.assertEqual(result["status"], "committed")
        self.assertTrue((self.vault.root / "two.md").exists())
        self.assertEqual(self.vault.unfinished(), [])
        self.assertEqual(self.vault.resume("test-transaction")["status"], "committed")
        with self.assertRaises(core.VaultError):
            self.vault.commit(operations, "opus 5", "different", "test-transaction")

    def test_refused_operation_leaves_no_snapshot_folder(self):
        operations = [{"path": "one.md", "expected_sha256": None, "content": HEADER + "one"},
                      {"path": "two.md", "expected_sha256": None, "content": "no frontmatter"}]
        with self.assertRaises(core.VaultError):
            self.vault.commit(operations, "astra", "bad second", "refused-transaction")
        self.assertFalse((self.vault.backups / "refused-transaction").exists())
        self.assertFalse((self.vault.root / "one.md").exists())

    def test_conflict_before_any_write_is_abandoned_and_the_same_id_can_be_prepared_again(self):
        self.vault.commit([{"path": "one.md", "expected_sha256": None, "content": HEADER + "one"}], "astra", "new")
        info = self.vault.inspect("one.md")
        operation = [{"path": "one.md", "expected_sha256": info["sha256"], "append": "more\n"}]
        real = core.atomic_json

        def edit_outside(path, data):
            # Another writer changes the note after the manifest is prepared and before it is applied.
            real(path, data)
            if Path(path).name == "manifest.json" and data.get("status") == "prepared":
                (self.vault.root / "one.md").write_text(info["text"] + "outside edit\n", encoding="utf-8")
        with patch.object(core, "atomic_json", side_effect=edit_outside):
            with self.assertRaises(core.Conflict):
                self.vault.commit(operation, "astra", "append", "raced-transaction")
        manifest = json.loads((self.vault.backups / "raced-transaction/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "abandoned")
        self.assertEqual(self.vault.unfinished(), [])
        fresh = self.vault.inspect("one.md")
        result = self.vault.commit([{"path": "one.md", "expected_sha256": fresh["sha256"], "append": "more\n"}], "astra", "append", "raced-transaction")
        self.assertEqual(result["status"], "committed")
        self.assertIn("outside edit\nmore\n", self.vault.inspect("one.md")["text"].replace("\r\n", "\n"))

    def test_untouched_note_keeps_its_writer_and_time(self):
        self.vault.commit([{"path": "one.md", "expected_sha256": None, "content": HEADER + "one"}], "astra", "new")
        info = self.vault.inspect("one.md")
        again = self.vault.commit([{"path": "one.md", "expected_sha256": info["sha256"]}], "opus 5", "no change")
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(self.vault.inspect("one.md")["sha256"], info["sha256"])

    def test_snapshot_prune_keeps_each_notes_newest_and_unfinished_transactions(self):
        import os
        for number in range(3):
            info = self.vault.inspect("one.md")
            self.vault.commit([{"path": "one.md", "expected_sha256": info["sha256"], "content": HEADER + f"version {number}"}], "astra", "edit", f"tx-{number}")
        self.vault.commit([{"path": "two.md", "expected_sha256": None, "content": HEADER + "two"}], "astra", "new", "tx-two")
        old = dt.datetime(2026, 1, 1).timestamp()
        for name in ("tx-0", "tx-1", "tx-2", "tx-two"):
            manifest = self.vault.backups / name / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["time"] = "2026-01-01T00:00:00+00:00"
            if name == "tx-0":
                data["status"] = "interrupted"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            os.utime(manifest.parent, (old, old))
        preview = vault_hygiene.snapshots(self.vault, prune=True, keep_days=30)
        self.assertEqual((preview["outcome"], preview["removable"], preview["unfinished"]), ("preview", 1, ["tx-0"]))
        self.assertTrue((self.vault.backups / "tx-1").exists())
        applied = vault_hygiene.snapshots(self.vault, prune=True, keep_days=30, apply=True)
        self.assertEqual((applied["outcome"], applied["remaining"]), ("pruned", 3))
        self.assertEqual(sorted(p.name for p in self.vault.backups.iterdir()), ["tx-0", "tx-2", "tx-two"])
        self.assertEqual(vault_hygiene.snapshots(self.vault)["transactions"], 3)

    def test_backfill_does_not_replace_later_open_line(self):
        _, path = self.daily()
        op = core.daily_operation(self.vault, "2026-09-05", "1:42 PM", "Earlier work", SECTIONS, "astra", "<!-- vault-capture:early -->", "Earlier next action")
        self.vault.commit([op], "astra", "earlier")
        self.assertNotIn("**Open for tomorrow:** Earlier", self.vault.inspect(path)["text"])


class SourceTests(Fixture):
    def test_both_models_and_turn_boundaries(self):
        for provider, model in (("codex", "gpt-6-astra"), ("claude", "claude-opus-5")):
            units = list(sources.stream_units(self.transcript(provider, model=model), provider, "session-1"))
            self.assertEqual(len(units), 2)
            self.assertEqual(units[-1]["model"], model)
            self.assertIsNotNone(units[-1]["turn_key"])

    def test_hidden_reasoning_excluded(self):
        path = self.transcript()
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"type": "response_item", "timestamp": "2026-09-05T21:42:00Z", "payload": {"type": "message", "role": "assistant", "channel": "analysis", "content": [{"type": "output_text", "text": "private reasoning"}]}}) + "\n")
        self.assertNotIn("private reasoning", json.dumps(list(sources.stream_units(path, "codex", "session-1"))))

    def test_long_event_fragments_reconstruct_without_loss(self):
        text = "abcdefghijklmnopqrstuvwxyz" * 2000
        units = list(sources.stream_units(self.transcript(text=text), "codex", "session-1"))
        self.assertEqual("".join(u["text"] for u in units if u["role"] == "user"), text)
        self.assertEqual(len({u["id"] for u in units}), len(units))

    def test_partial_final_line_waits(self):
        path = self.transcript()
        with path.open("ab") as out:
            out.write(b'{"partial":')
        self.assertEqual(len(list(sources.stream_units(path, "codex", "session-1"))), 2)

    def test_session_mismatch_rejected(self):
        with self.assertRaises(core.VaultError):
            list(sources.stream_units(self.transcript(), "codex", "wrong-session"))

    def test_source_rewrite_invalidates_ids(self):
        path = self.transcript()
        before = list(sources.stream_units(path, "codex", "session-1"))
        self.transcript(text="A different real user request.")
        after = list(sources.stream_units(path, "codex", "session-1"))
        self.assertNotEqual(before[0]["id"], after[0]["id"])

    def test_multi_day_uses_event_local_date(self):
        path = self.transcript()
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"type": "event_msg", "timestamp": "2026-09-07T10:00:00Z", "payload": {"type": "user_message", "message": "Another day of work."}}) + "\n")
        self.assertEqual(len({u["day"] for u in sources.stream_units(path, "codex", "session-1")}), 2)


class CaptureTests(Fixture):

    def test_unrelated_note_write_is_not_coverage(self):
        self.daily()
        units = uncovered(self.vault, self.transcript(), "codex", "session-1")
        self.assertEqual(len(units), 2)

    def test_outside_and_fake_anchors_rejected(self):
        units = list(sources.stream_units(self.transcript(), "codex", "session-1"))
        proposal = self.proposal(units, "already_covered")
        proposal["anchors"] = [{"path": str(self.base / "outside.md"), "text": "## Session " + "x" * 200}]
        with self.assertRaises(core.VaultError):
            capture.validate_proposal(self.vault, proposal, units)

    def test_trivial_has_verified_evidence_and_no_writes(self):
        units = list(sources.stream_units(self.transcript(), "codex", "session-1"))
        proposal = self.proposal(units, "trivial")
        receipt = capture.apply_proposal(self.vault, proposal, "opus 5", units, "codex", "session-1", "trivial-test")
        self.assertEqual(receipt["disposition"], "trivial")
        self.assertEqual(len(list(self.vault.root.rglob("2026-*.md"))), 0)
        proposal["evidence"][0]["quote"] = "invented evidence"
        with self.assertRaises(core.VaultError):
            capture.validate_proposal(self.vault, proposal, units)

    def test_deleted_daily_anchor_invalidates_receipt(self):
        path = self.transcript()
        units = list(sources.stream_units(path, "codex", "session-1"))
        capture.apply_proposal(self.vault, self.proposal(units), "opus 5", units, "codex", "session-1", "capture-test")
        self.vault.path(core.daily_path(units[0]["day"])).unlink()
        self.assertEqual(len(uncovered(self.vault, path, "codex", "session-1")), 2)


class HygieneTests(Fixture):
    def test_schema_block_lists_allowlisted_projects(self):
        import vault_hygiene
        with patch.dict(vault_hygiene.SCHEMA, {"project_allowlist": ["alpha-one", "meta"]}):
            self.assertIn("- Project: `alpha-one`, `meta`.\n", vault_hygiene.schema_block())
        with patch.dict(vault_hygiene.SCHEMA, {"project_allowlist": None}):
            self.assertIn("- Project: any kebab-case slug;", vault_hygiene.schema_block())

    def test_priority_aging_merges_into_existing_review_category(self):
        import vault_hygiene
        text = ("## Active Now\n\n**Personal**\n- Old item `touched: 2026-08-18`\n\n## Review\n\nReview here.\n\n"
                "**Personal**\n- Older item `touched: 2026-08-01`\n- Fresh misfile `touched: 2026-09-05`\n\n## Parked / Watch\n")
        revised = age_priorities(text, dt.date(2026, 9, 6))[0]
        self.assertEqual(revised.count("**Personal**"), 2)
        self.assertLess(revised.index("Older item"), revised.index("Old item"))
        self.assertEqual(len(vault_hygiene.recent_review(revised, dt.date(2026, 9, 6))), 1)

    def test_priority_aging_idempotent(self):
        text = "## Active Now\n\n**Personal**\n- Old item `touched: 2026-08-18`\n- Current item `touched: 2026-09-06`\n\n## Review\n\nReview here.\n\n## Parked / Watch\n- Parked item `touched: 2020-01-01`\n"
        revised, count, active = age_priorities(text, dt.date(2026, 9, 6))
        self.assertEqual(count, 1)
        self.assertEqual(active, 1)
        self.assertIn("Old item", revised.split("## Review")[1])
        self.assertEqual(age_priorities(revised, dt.date(2026, 9, 6))[0], revised)

    def test_hygiene_no_model_and_no_archive_changes(self):
        folder = self.vault.root / "02 - Example Project"
        folder.mkdir()
        (folder / "02 - Example Project.md").write_text(HEADER.replace("type: log", "type: index") + "\n# Index\n", encoding="utf-8")
        (folder / "A note.md").write_text(HEADER + "\n# A note\n", encoding="utf-8")
        frozen = self.vault.root / "09 - Archive/Old Memory/frozen.md"
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(b"old frozen bytes")
        report = hygiene(self.vault, fix=True, check_parity=False)
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(frozen.read_bytes(), b"old frozen bytes")
        again = hygiene(self.vault, fix=True, check_parity=False)
        self.assertEqual(again["repairs"], [])

    def test_index_folders_come_from_the_schema(self):
        folder = self.vault.root / "11 - Business"
        folder.mkdir()
        (folder / "Client.md").write_text(HEADER + "\n# Client\n", encoding="utf-8")
        self.assertNotIn("11 - Business", json.dumps(hygiene(self.vault, check_parity=False)["issues"]))
        with patch.dict(core.SCHEMA, {"index_folders": ["02", "11"]}):
            problems = [i["problem"] for i in hygiene(self.vault, check_parity=False)["issues"]]
        self.assertIn("Missing required folder index", problems)

    def test_long_priority_lines_are_reported_informationally(self):
        (self.vault.root / "Active Priorities.md").write_text(
            HEADER + "\n## Active Now\n- " + "x" * 320 + " `touched: 2099-01-01`\n- short `touched: 2099-01-01`\n\n## Review\n- None\n", encoding="utf-8")
        report = hygiene(self.vault, check_parity=False)
        self.assertEqual(len(report["long_priorities"]), 1)
        self.assertNotIn("long", json.dumps(report["issues"]).lower())

    def test_hygiene_reachable_subfolder_index_covers_its_notes(self):
        index = HEADER.replace("type: log", "type: index")
        folder = self.vault.root / "07 - Corpora"
        linked, orphan = folder / "Linked Corpus", folder / "Orphan Corpus"
        nested = linked / "Topic"
        for d in (nested, orphan):
            d.mkdir(parents=True)
        (folder / "07 - Corpora.md").write_text(index + "\n# Index\n- [[Linked Corpus]] — corpus. `(automation)`\n", encoding="utf-8")
        (linked / "Linked Corpus.md").write_text(index + "\n# Linked\n- [[Topic]]\n", encoding="utf-8")
        (nested / "Topic.md").write_text(index + "\n# Topic\n- [[Video One]]\n", encoding="utf-8")
        (nested / "Video One.md").write_text(HEADER + "\n# Video One\n", encoding="utf-8")
        (orphan / "Orphan Corpus.md").write_text(index + "\n# Orphan\n- [[Video Two]]\n", encoding="utf-8")
        (orphan / "Video Two.md").write_text(HEADER + "\n# Video Two\n", encoding="utf-8")
        report = hygiene(self.vault, fix=False, check_parity=False)
        unindexed = {i["problem"] for i in report["issues"] if i["problem"].startswith("Unindexed note: ")}
        self.assertEqual(unindexed, {"Unindexed note: Orphan Corpus", "Unindexed note: Video Two"})


class ProfileDriftTests(Fixture):
    def note(self, rel, text):
        path = self.vault.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def index(self, who="Works on [[Alpha]].", living="", updated="2026-10-01"):
        self.note("VAULT-INDEX.md", HEADER.replace("2026-08-01", updated) + f"\n## Who I Am\n\n{who}\n\n## Living Profile\n\n{living}\n")

    def day(self, bullets_by_session, day="2026-10-20"):
        body = ""
        for number, (time, bullets) in enumerate(bullets_by_session, 1):
            body += f"## Session {number} — {time}: Topic {number} — `astra`\n\n### Profile Updates\n" + "".join(f"- {b}\n" for b in bullets) + "\n"
        self.note(f"01 - Daily Notes/10 - October 2026/{day}.md", HEADER + f"\n# Tuesday, October 20, 2026\n\n## Index\n\n{body}")

    def priorities(self, now_links="[[Alpha]]", next_links=""):
        self.note("Active Priorities.md", HEADER + f"\n## Active Now\n\n- Work on {now_links}\n\n## Next\n\n- Later {next_links}\n\n## Waiting\n\n- Skip [[Waiting Note]]\n")

    def test_profile_drift_marker_filters_pending_updates(self):
        self.index(living="Profile reviewed through: 2026-10-20T14:00")
        self.day([("1:00 PM", ["Before the marker."]), ("3:42 PM", ["None; preserved", "None", "", "After the marker."]), ("4:00 PM", ["None"])])
        report = vault_hygiene.profile_drift(self.vault)
        self.assertEqual(report["marker"], "2026-10-20T14:00")
        self.assertEqual(report["baseline"], "2026-10-20T14:00:00")
        self.assertEqual([e["text"] for e in report["pending_profile_updates"]], ["After the marker."])
        entry = report["pending_profile_updates"][0]
        self.assertEqual((entry["date"], entry["path"]), ("2026-10-20", "01 - Daily Notes/10 - October 2026/2026-10-20.md"))
        self.assertTrue(entry["session"].startswith("Session 2 — 3:42 PM"))
        self.assertEqual(entry["line"], 24)
        self.assertEqual(report["outcome"], "needs_review")
        self.index(living="Profile reviewed through: October 20, 2026 at 10:40 PM")
        report = vault_hygiene.profile_drift(self.vault)
        self.assertEqual((report["pending_profile_updates"], report["outcome"]), ([], "passed"))

    def test_profile_drift_without_marker_uses_frontmatter_updated(self):
        self.index(updated="2026-10-20")
        self.day([("3:42 PM", ["Same day as updated."])])
        report = vault_hygiene.profile_drift(self.vault)
        self.assertIsNone(report["marker"])
        self.assertEqual(report["baseline"], "2026-10-20T23:59:59")
        self.assertEqual(report["pending_profile_updates"], [])
        self.index(updated="2026-10-19")
        self.assertEqual(len(vault_hygiene.profile_drift(self.vault)["pending_profile_updates"]), 1)

    def test_profile_drift_missing_from_profile_uses_names_and_aliases(self):
        self.index(who="Builds [[Alpha]] and the Beta Tool.")
        self.priorities(now_links="[[Alpha]]", next_links="[[Beta|b]] [[Gamma]]")
        self.note("Alpha.md", HEADER)
        self.note("Beta.md", HEADER.replace("status: active", 'aliases: ["Beta Tool"]\nstatus: active'))
        self.note("Gamma.md", HEADER)
        self.note("Waiting Note.md", HEADER)
        report = vault_hygiene.profile_drift(self.vault)
        self.assertEqual(report["missing_from_profile"], [{"name": "Gamma", "section": "Next"}])
        self.note("Gamma.md", HEADER.replace("project: personal", "project: meta"))
        self.assertEqual(vault_hygiene.profile_drift(self.vault)["missing_from_profile"], [])

    def test_hygiene_reports_profile_drift_informationally(self):
        self.index(living="Profile reviewed through: 2026-10-01T00:00")
        self.day([("3:42 PM", ["New fact."])])
        report = hygiene(self.vault, check_parity=False)
        self.assertEqual(report["profile_drift"]["outcome"], "needs_review")
        self.assertEqual(report["model_calls"], 0)
        self.assertNotIn("profile", json.dumps(report["issues"]).lower())
        with patch.object(vault_hygiene, "profile_drift", side_effect=RuntimeError("boom")):
            forced = hygiene(self.vault, check_parity=False)
        self.assertEqual(forced["profile_drift"], {"outcome": "error", "error": "boom"})
        self.assertEqual(forced["issues"], report["issues"])
        self.assertEqual(forced["outcome"], report["outcome"])

    def test_vaultctl_profile_drift_exit_codes(self):
        import vaultctl
        self.index(living="Profile reviewed through: 2026-10-20T23:00")
        self.day([("3:42 PM", ["Old fact."])])
        args = [sys.executable, str(Path(vaultctl.__file__)), "--vault", str(self.vault.root), "--state", str(self.vault.state),
                "--backups", str(self.vault.backups), "profile-drift"]
        passed = subprocess.run(args, capture_output=True, text=True, timeout=60)
        self.assertEqual((passed.returncode, json.loads(passed.stdout)["outcome"]), (0, "passed"))
        self.index(living="Profile reviewed through: 2026-10-20T12:00")
        needs = subprocess.run(args, capture_output=True, text=True, timeout=60)
        self.assertEqual((needs.returncode, json.loads(needs.stdout)["outcome"]), (2, "needs_review"))



class HookTests(Fixture):
    def gate_fixture(self, vault_write=False, failed=False, padding=0):
        path = self.transcript("claude", model="claude-opus-5")
        rows = path.read_bytes()
        if padding:
            path.write_bytes((json.dumps({"type": "progress", "content": "x" * padding}) + "\n").encode() + rows)
        target = r"C:\Projects\Brain\topic.md" if vault_write else r"C:\Projects\vault-fixture\project.py"
        extra = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "write-1", "name": "Edit", "input": {"file_path": target}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "write-1", "is_error": failed, "content": "failed" if failed else "edited"}]}}
        ]
        with path.open("a", encoding="utf-8") as out:
            out.write("".join(json.dumps(row) + "\n" for row in extra))
        return {"session_id": "session-1", "transcript_path": str(path)}

    def test_large_transcript_gate_still_fires(self):
        payload = self.gate_fixture(padding=20 * 1024 * 1024)
        code, text = hooks.stop_gate(payload, self.vault, self.directory)
        self.assertEqual(code, 2)
        self.assertTrue(text.startswith("Vault checkpoint requested for session "))
        self.assertIn("checkpoint-context", text)
        self.assertIn("checkpoint --summary", text)
        self.assertIn('"Daily checkpoints and coverage"', text)
        self.assertNotIn("Read and reconcile", text)

    def test_long_answer_counts_only_beside_real_tool_use(self):
        rows = [{"type": "user", "origin": {"kind": "human"}, "uuid": "t", "message": {"content": "Explain this"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "A long answer. " * 200}]}}]
        self.assertFalse(hooks.signals(rows)["substantive"])
        for n in range(5):
            rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"r{n}", "name": "Bash", "input": {"command": "cat notes.md"}}]}})
            rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"r{n}", "content": "text"}]}})
        evidence = hooks.signals(rows)
        self.assertEqual(evidence["tool_calls"], 5)
        self.assertTrue(evidence["substantive"])

    def test_request_names_the_flags_and_profile_guidance(self):
        code, text = hooks.stop_gate(self.gate_fixture(), self.vault, self.directory)
        self.assertEqual(code, 2)
        self.assertIn("--source claude --session session-1 --transcript", text)
        self.assertIn("--topic '...' --done '...'", text)
        self.assertIn("--profile only for a fact the user stated about themselves this turn", text)
        self.assertEqual(hooks.stop_gate(self.gate_fixture(failed=True), self.vault, self.directory)[0], 0)

    def test_a_new_turn_is_asked_inside_the_window_but_the_same_turn_is_not(self):
        payload = self.gate_fixture()
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory, current_ms=1_000_000)[0], 2)
        rows = [{"type": "user", "origin": {"kind": "human"}, "uuid": "turn-2", "timestamp": "2026-09-05T21:50:00Z", "message": {"content": "Next task"}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "write-2", "name": "Edit", "input": {"file_path": r"C:\Projects\vault-fixture\other.py"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "write-2", "content": "edited"}]}}]
        with Path(payload["transcript_path"]).open("a", encoding="utf-8") as out:
            out.write("".join(json.dumps(row) + "\n" for row in rows))
        # Two minutes later: new work, so it is asked for even though the last request is recent.
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory, current_ms=1_120_000)[0], 2)
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory, current_ms=1_130_000)[0], 0)

    def test_missing_transcript_falls_back_to_the_turn_log_and_asks_for_an_attested_checkpoint(self):
        import vault_gate
        payload = {"session_id": "session-9", "transcript_path": str(self.base / "gone.jsonl"), "cwd": str(self.base)}
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory), (0, ""))
        vault_gate.post_tool(self.vault, "claude", dict(payload, tool_name="Edit", tool_input={"file_path": str(self.base / "project.py")}),
                             ["tool_input.file_path"])
        code, text = hooks.stop_gate(payload, self.vault, self.directory)
        self.assertEqual(code, 2)
        self.assertIn("--source claude --session session-9 --model <runtime model id>", text)
        self.assertNotIn("--transcript", text)

    def test_write_guard_refuses_direct_writes_to_vault_notes_only(self):
        import vault_gate
        paths = ["tool_input.file_path"]
        note = self.vault.root / "02 - Example/Topic.md"
        refusal = vault_gate.pre_tool(self.vault, {"tool_input": {"file_path": str(note)}}, paths)
        self.assertIn("Direct write to a vault note refused: 02 - Example/Topic.md", refusal)
        self.assertIn("commit --model", refusal)
        for allowed in (self.vault.root / ".obsidian/app.json", self.vault.root / ".trash/Old.md", self.vault.root / "02 - Example/image.png",
                        self.base / "project/README.md"):
            self.assertEqual(vault_gate.pre_tool(self.vault, {"tool_input": {"file_path": str(allowed)}}, paths), "", allowed)
        allow = {"hooks": {"direct_writes": "allow"}}
        self.assertEqual(vault_gate.pre_tool(self.vault, {"tool_input": {"file_path": str(note)}}, paths, allow), "")
        adapter = {"hooks": {"paths": paths, "gate_output": "exit2-stdout-async"}, "transcript_adapter": "claude-jsonl"}
        code, out, err = vault_gate.hook("claude", "PreToolUse", {"tool_input": {"file_path": str(note)}}, adapter, self.vault)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("Direct write to a vault note refused"))

    def test_session_start_gives_the_checkpoint_flags_and_marks_the_hooks_seen(self):
        import vault_gate
        payload = {"session_id": "session-1", "transcript_path": r"C:\t\session-1.jsonl", "cwd": str(self.base)}
        with patch("vault_recall.session_brief", return_value="brief"):
            text = vault_gate.session_start(self.vault, "claude", payload, "claude-jsonl")
        self.assertEqual(text, 'brief\nThis session\'s checkpoint flags: --source claude --session session-1 --transcript "C:\\t\\session-1.jsonl"')
        self.assertIn("claude", json.loads((self.vault.state / "hooks-seen.json").read_text(encoding="utf-8")))
        self.assertEqual(vault_gate.session_line("kiro", {"session_id": "k", "model": "m-1"}), "This session's checkpoint flags: --source kiro --session k --model m-1")

    def test_topic_write_is_not_checkpoint_completion(self):
        payload = self.gate_fixture(vault_write=True)
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 2)

    def test_failed_write_alone_is_not_successful_work(self):
        payload = self.gate_fixture(failed=True)
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 0)

    def test_request_is_not_completed_receipt_and_no_loop(self):
        payload = self.gate_fixture()
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 2)
        self.assertEqual(sources.verified_receipts(self.vault, "claude", "session-1"), [])
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 0)

    def test_pause_and_automation_guards(self):
        payload = self.gate_fixture()
        core.atomic_json(self.directory / "automation-state.json", {"paused": True, "scope": "all"})
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 0)
        core.atomic_json(self.directory / "automation-state.json", {"paused": True, "scope": "afk"})
        with patch.dict(os.environ, {"VAULT_AUTOMATION": "1"}):
            self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 0)
        self.assertEqual(hooks.stop_gate(dict(payload, stop_hook_active=True), self.vault, self.directory)[0], 0)
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 2)

    def test_session_guards_do_not_overwrite_each_other(self):
        payload = self.gate_fixture()
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 2)
        self.assertEqual(hooks.stop_gate(dict(payload, session_id="session-2"), self.vault, self.directory)[0], 2)
        self.assertEqual(len(list((self.vault.state / "gate").glob("*.json"))), 2)


class CheapCheckpointTests(Fixture):
    LAUNCH_MS = int(dt.datetime(2026, 9, 5, 21, 42, tzinfo=dt.timezone.utc).timestamp() * 1000)

    def claude_rows(self, extra, path=None):
        path = path or self.transcript("claude", model="claude-opus-5")
        with path.open("a", encoding="utf-8") as out:
            out.write("".join(json.dumps(row) + "\n" for row in extra))
        return {"session_id": "session-1", "transcript_path": str(path)}

    def shell(self, call_id, command, ok=True):
        return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "is_error": not ok, "content": "ok"}]}}]

    def test_new_day_open_line_keeps_backslashes(self):
        op = core.daily_operation(self.vault, "2026-09-07", "3:42 PM", "Path work", SECTIONS, "astra", "<!-- m -->", r"Resume in C:\Users\me\work")
        self.assertIn(r"**Open for tomorrow:** Resume in C:\Users\me\work", op["content"])

    def test_new_daily_has_no_index_and_empty_optional_sections_are_left_out(self):
        _, rel = self.daily()
        text = (self.vault.root / rel).read_text(encoding="utf-8")
        self.assertNotIn("## Index", text)
        self.assertEqual(re.findall(r"^### (.+)$", text, re.M), ["What Got Done", "What's Still In Progress", "Decisions Made", "Notes Touched"])
        sections = dict(SECTIONS, **{"Profile Updates": ["The user said they prefer tea."]})
        op = core.daily_operation(self.vault, "2026-09-05", "4:00 PM", "More work", sections, "astra", "<!-- m2 -->")
        self.assertEqual(op["edits"], [])
        self.assertIn("### Profile Updates\n- The user said they prefer tea.", op["append"].replace("\r\n", "\n"))
        self.vault.commit([op], "astra", "test")
        # A required section cannot be dropped, and sections keep their order.
        for bad in ("## Session 9 — 5:00 PM: T — `astra`\n\n### What Got Done\n- x\n",
                    "## Session 9 — 5:00 PM: T — `astra`\n\n### Notes Touched\n- x\n\n### What Got Done\n- x\n"):
            with self.assertRaises(core.VaultError):
                core.ensure_new_daily_sections(bad)

    def test_a_daily_note_with_a_legacy_index_still_takes_appends_and_keeps_its_index(self):
        rel = core.daily_path("2026-09-04")
        legacy = (HEADER + "\n# Friday, September 4, 2026\n\n**Open for tomorrow:** None\n\n## Index\n\n- **Old** — bullet. `(astra)`\n\n"
                  "## Session 1 — 1:00 PM: Old — `astra`\n\n" + "".join(f"### {name}\n- None\n\n" for name in core.SCHEMA["daily_sections"]))
        path = self.vault.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(legacy, encoding="utf-8")
        op = core.daily_operation(self.vault, "2026-09-04", "4:00 PM", "More work", SECTIONS, "astra", "<!-- m3 -->")
        self.vault.commit([op], "astra", "test")
        text = path.read_text(encoding="utf-8")
        self.assertIn("## Index\n\n- **Old** — bullet. `(astra)`", text)
        info = self.vault.inspect(rel)
        with self.assertRaises(core.VaultError):
            self.vault.commit([{"path": rel, "expected_sha256": info["sha256"], "edits": [{"old": "- **Old** — bullet. `(astra)`\n", "new": ""}]}], "astra", "drop index")

    def test_checkpoint_fills_day_time_and_skips_short_evidence(self):
        import vaultctl
        path = self.transcript("claude", text="ok", model="claude-opus-5")
        units = list(sources.stream_units(path, "claude", "session-1"))
        payload = {"days": [{"topic": "Work", "sections": SECTIONS}]}
        vaultctl.fill_days(payload, units)
        self.assertEqual((payload["days"][0]["day"], payload["days"][0]["time"]), (units[-1]["day"], units[-1]["time"]))
        self.assertNotEqual(vaultctl.default_evidence(units)[0]["quote"].strip(), "ok")
        self.assertEqual(vaultctl.day_times(units)[-1]["last"], units[-1]["time"])

    def test_inspect_hash_only(self):
        import vaultctl
        _, rel = self.daily()
        rows = vaultctl.main(["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups), "inspect", "--hash", rel])
        self.assertEqual(sorted(rows[0]), ["bytes", "path", "sha256"])

    def test_decision_edits_in_checkpoints_are_status_only(self):
        row = "| 2026-09-01 | Use X. | Because. | `note` | active |"
        capture.check_decision_edit({"old": row, "new": row.replace("| active |", "| superseded 2026-09-02 by the row below |")})
        for bad in ({"old": row, "new": row.replace("Use X.", "Use Y.")},
                    {"old": row.replace("| active |", "| locked |"), "new": row.replace("| active |", "| superseded |")}):
            with self.assertRaises(core.VaultError):
                capture.check_decision_edit(bad)

    def test_consolidate_days_precedence_and_note_filter(self):
        import vault_recall
        (self.vault.root / "Alpha project.md").write_text(HEADER + "\n# Alpha project\n", encoding="utf-8")
        with patch.object(vault_recall, "_today", return_value=dt.date(2026, 9, 5)):
            self.daily(topic="Alpha project work")
            self.vault.commit([core.daily_operation(self.vault, "2026-09-05", "4:00 PM", "Other work", SECTIONS, "astra", "<!-- m2 -->")], "astra", "test")
            self.assertEqual(vault_recall.consolidate_context(self.vault, days=1)["from"], "2026-09-05")
            core.atomic_json(self.vault.state / "consolidation.json", {"through": "2026-09-05"})
            self.assertEqual(vault_recall.consolidate_context(self.vault, days=2)["from"], "2026-09-04")
            report = vault_recall.consolidate_context(self.vault, note="Alpha project")
            self.assertEqual(report["from"], "2026-08-01")
            self.assertEqual(len(report["listed_sessions"]), 1)

    def test_durable_command_alone_is_substantive_but_scratch_copy_is_not(self):
        self.assertEqual(hooks.stop_gate(self.claude_rows(self.shell("c1", "git push origin main")), self.vault, self.directory)[0], 2)
        scratch = self.claude_rows(self.shell("c2", r"cp a.json C:\Users\me\AppData\Local\Temp\scratchpad\b.json"), self.base / "other.jsonl")
        self.assertEqual(hooks.stop_gate(dict(scratch, session_id="session-2"), self.vault, self.directory)[0], 0)

    def test_pending_background_agents_defer_until_notified(self):
        launch = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "agent-1", "name": "Agent", "input": {}}]}},
                  {"type": "user", "timestamp": "2026-09-05T21:42:00Z", "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": "a1"},
                   "message": {"content": [{"type": "tool_result", "tool_use_id": "agent-1", "content": "launched"}]}},
                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 1600}]}}]
        payload = self.claude_rows(launch)
        later = self.LAUNCH_MS + 60000
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory, current_ms=later)[0], 0)
        self.claude_rows([{"type": "user", "origin": {"kind": "task-notification"},
                           "message": {"content": "<task-notification><tool-use-id>agent-1</tool-use-id><status>completed</status></task-notification>"}}],
                         Path(payload["transcript_path"]))
        self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory, current_ms=later)[0], 2)

    def test_after_checkpoint_only_new_durable_work_requests_again(self):
        payload = self.claude_rows(self.shell("c1", "git commit -m x"))
        live = self.vault.state / "live"
        live.mkdir(parents=True, exist_ok=True)
        core.atomic_json(live / (sources.source_key("claude", "session-1") + ".json"),
                         {"turn_key": "turn-1", "receipt_id": "r1", "through": Path(payload["transcript_path"]).stat().st_size})
        with patch.object(hooks, "verified_receipts", return_value=[{"id": "r1"}]):
            self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 0)
            self.claude_rows(self.shell("c2", "git push origin main"), Path(payload["transcript_path"]))
            self.assertEqual(hooks.stop_gate(payload, self.vault, self.directory)[0], 2)

    def test_trivial_refused_after_durable_work(self):
        import types, vaultctl
        payload = self.claude_rows(self.shell("c1", "git push origin main"))
        with self.assertRaises(core.VaultError):
            vaultctl.refuse_trivial(self.vault, types.SimpleNamespace(source="claude", session="session-1", transcript=payload["transcript_path"]))

    def test_stamp_prints_the_report_byline(self):
        import vaultctl
        line = vaultctl.main(["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups),
                              "stamp", "--model", "claude-fable-5-2"])
        self.assertRegex(line, r"^_Written [A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2}:\d{2} [AP]M \(UTC[+-]\d{2}:\d{2}\) by fable 5\.2_$")
        with self.assertRaises(core.VaultError):
            vaultctl.byline("claude")


class RecallMeasurementTests(Fixture):
    def test_handoff_report_and_heading_cases(self):
        import vault_recall
        text = ("---\nstatus: active\nproject: personal\ntype: plan\nupdated_by: astra\nupdated: 2026-09-10\n---\n\n# Project\n\n"
                "## Handoff - resume here\n_Last updated: September 1, 2026 at 9:00 AM by astra_\n\n" + "x" * 3100 + "\n\n## Notes\n")
        report = {"stale": [], "oversized": [], "nonstandard_heading": []}
        vault_recall.handoff_report("Project.md", text, report)
        self.assertEqual([len(report[k]) for k in ("stale", "oversized", "nonstandard_heading")], [1, 1, 1])
        cases = vault_recall.load_eval("| Q | [[Project#Notes]] | project |\n| Q2 | [[Project]] | project |")
        self.assertEqual([c["heading"] for c in cases], ["Notes", None])
        self.assertTrue(vault_recall.has_heading(text, "Notes"))
        self.assertFalse(vault_recall.has_heading(text, "Missing"))


class RuntimeContractTests(unittest.TestCase):
    def test_runtime_hash_covers_only_vault_hooks(self):
        sys.path.insert(0, str(CONTRIB))
        import vault_runtime
        gate = {"type": "command", "command": "python C:\\Users\\me\\.claude\\hooks\\vault\\agent-hook.py claude Stop"}
        base = {"Stop": [{"hooks": [gate]}], "PostToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "node other.js"}]}]}
        changed = json.loads(json.dumps(base))
        changed["PostToolUse"][0]["hooks"][0]["command"] = "node another.js"
        self.assertEqual(vault_runtime.vault_hook_entries(base), vault_runtime.vault_hook_entries(changed))
        self.assertNotEqual(vault_runtime.vault_hook_entries(base), vault_runtime.vault_hook_entries({"PostToolUse": base["PostToolUse"]}))

    def test_daylight_saving_rendering_of_a_trigger_is_not_drift(self):
        sys.path.insert(0, str(CONTRIB))
        import vault_runtime
        task = lambda start: {"name": "VaultNightlyAudit", "logon_type": "Interactive", "triggers": [{"type": "MSFT_TaskDailyTrigger", "start": start}]}
        summer, winter = task("2026-07-27T03:30:00-06:00"), task("2026-07-27T02:30:00-07:00")
        self.assertEqual(vault_runtime.comparable(summer), vault_runtime.comparable(winter))
        self.assertNotEqual(vault_runtime.comparable(summer), vault_runtime.comparable(task("2026-07-27T04:30:00-06:00")))
        self.assertNotEqual(vault_runtime.comparable(summer), vault_runtime.comparable(dict(summer, logon_type="S4U")))
        self.assertEqual(summer["triggers"][0]["start"], "2026-07-27T03:30:00-06:00")  # the input is not modified
        self.assertIsNone(vault_runtime.comparable(None))

    @unittest.skipUnless(os.name == "nt", "PowerShell job runner")
    def test_job_log_rotates_past_128_kb(self):
        import re
        script = (CONTRIB / "invoke-vault-job.ps1").read_text(encoding="utf-8")
        function = re.search(r"function Write-JobLog \{.*?\n\}", script, re.S).group(0)
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "audit.log"
            log.write_bytes(b"x" * (129 * 1024))
            command = "$LogPath = '" + str(log) + "'\n" + function + "\nWrite-JobLog 'after rotation'"
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True, timeout=60)
            self.assertEqual((Path(tmp) / "audit.log.1").stat().st_size, 129 * 1024)
            self.assertIn("after rotation", log.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
