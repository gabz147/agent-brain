import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault_core as core
import vault_capture as capture
import vault_queue as queue
import vault_sources as sources
import vault_hooks as hooks
from vault_hygiene import age_priorities, hygiene

HEADER = "---\nstatus: active\nproject: personal\ntype: log\nupdated_by: codex\nupdated: 2026-08-01\n---\n"
TEMPLATE = HEADER + "\n# {{date:dddd, MMMM D, YYYY}}\n\n**Open for tomorrow:** None\n\n## Index\n\n## Session 1 — {{time:h:mm A}}: Manual entry — `human`\n"
SECTIONS = {key: ["None"] for key in core.SCHEMA["daily_sections"]}
SECTIONS["What Got Done"] = ["Verified the tested change."]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
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
        self.assertEqual(core.model_label("gpt-6-astra"), "astra")
        self.assertEqual(core.model_label("claude-opus-5"), "opus 5")
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
        self.assertIn("updated: " + core.now().date().isoformat(), after)
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
            self.vault.commit([{"path": path, "expected_sha256": info["sha256"], "edits": [{"old": "### Profile Updates", "new": "### Changed"}]}], "astra", "edit")

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
            with self.assertRaises(OSError):
                self.vault.commit(operations, "astra", "partial", "test-transaction")
        self.assertTrue((self.vault.root / "one.md").exists())
        result = self.vault.commit(operations, "astra", "partial", "test-transaction")
        self.assertEqual(result["status"], "committed")
        with self.assertRaises(core.VaultError):
            self.vault.commit(operations, "opus 5", "different", "test-transaction")

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
    def test_capture_repeat_does_not_call_model_or_duplicate(self):
        path = self.transcript()
        entry = {"source": "codex", "session_id": "session-1", "transcript_path": str(path)}
        units = list(sources.stream_units(path, "codex", "session-1"))
        with patch.object(capture, "build_prompt", return_value="full stdin evidence"):
            result = capture.capture(self.vault, entry, model_runner=lambda *args: (self.proposal(units), "opus 5"))
            again = capture.capture(self.vault, entry, model_runner=lambda *args: self.fail("must not run again"))
        self.assertTrue(result["complete"])
        self.assertTrue(again["complete"])
        note = self.vault.inspect(core.daily_path(units[0]["day"]))["text"]
        self.assertEqual(note.count("## Session"), 1)
        self.assertIn("updated_by: opus 5", note)

    def test_unrelated_note_write_is_not_coverage(self):
        self.daily()
        units, _ = sources.uncovered(self.vault, self.transcript(), "codex", "session-1")
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
        self.assertEqual(len(sources.uncovered(self.vault, path, "codex", "session-1")[0]), 2)

    def test_stdin_transport_and_usage(self):
        proposal = {"disposition": "trivial"}
        script = "import sys,json; data=sys.stdin.read(); assert data == 'complete prompt'; print(json.dumps({'type':'assistant','message':{'model':'claude-opus-5'}})); print(json.dumps({'type':'result','is_error':False,'structured_output':" + repr(proposal) + ",'usage':{'input_tokens':123,'output_tokens':9},'modelUsage':{},'total_cost_usd':0.012}))"
        result, signer = capture.run_model(self.vault, "complete prompt", "stub-test", [sys.executable, "-c", script])
        self.assertEqual(signer, "opus 5")
        outcome = json.loads((self.vault.state / "outcomes.jsonl").read_text().splitlines()[-1])
        self.assertEqual(outcome["usage"]["input_tokens"], 123)
        self.assertEqual(outcome["cost_usd"], 0.012)

    def test_exit_zero_without_proof_fails_and_logs(self):
        with self.assertRaises(core.VaultError):
            capture.run_model(self.vault, "prompt", "no-proof", [sys.executable, "-c", "print('done')"])
        self.assertEqual(json.loads((self.vault.state / "outcomes.jsonl").read_text().splitlines()[-1])["outcome"], "failed")

    def test_timeout_logs(self):
        with self.assertRaises(core.VaultError):
            capture.run_model(self.vault, "prompt", "timeout", [sys.executable, "-c", "import time;time.sleep(2)"], timeout=0.1)
        self.assertEqual(json.loads((self.vault.state / "outcomes.jsonl").read_text().splitlines()[-1])["outcome"], "timeout")

    def test_quota_backoff_prevents_next_child(self):
        script = "import json;print(json.dumps({'type':'result','is_error':True,'result':'Rate limit, retry-after: 600'}))"
        with self.assertRaises(capture.Deferred):
            capture.run_model(self.vault, "prompt", "rate-limit", [sys.executable, "-c", script])
        with patch.object(capture.subprocess, "run", side_effect=AssertionError("child must not launch")):
            with self.assertRaises(capture.Deferred):
                capture.run_model(self.vault, "prompt", "backoff", ["unused"])


class QueueTests(Fixture):
    def batch(self, raw=None):
        path = self.directory / "queue.batch.jsonl"
        entry = {"source": "codex", "session_id": "session-1", "transcript_path": "somewhere.jsonl"}
        path.write_bytes(raw or (json.dumps(entry) + "\n").encode())
        return path

    def test_batch_read_failure_preserves_batch(self):
        batch = self.batch()
        real = Path.read_bytes
        def broken(path):
            if path == batch:
                raise OSError("read denied")
            return real(path)
        with patch.object(Path, "read_bytes", broken):
            with self.assertRaises(OSError):
                queue.drain(self.vault, self.directory, discover=False)
        self.assertTrue(batch.exists())

    def test_malformed_failed_journal_failure_preserves_batch(self):
        batch = self.batch(b"not json\n")
        with patch.object(queue, "append_jsonl", side_effect=OSError("journal failed")):
            with self.assertRaises(OSError):
                queue.drain(self.vault, self.directory, discover=False)
        self.assertEqual(batch.read_bytes(), b"not json\n")

    def test_processed_journal_failure_preserves_work(self):
        batch = self.batch()
        with patch.object(queue, "append_jsonl", side_effect=OSError("journal failed")):
            with self.assertRaises(OSError):
                queue.drain(self.vault, self.directory, capture_fn=lambda *args: {"disposition": "captured", "complete": True}, discover=False)
        self.assertTrue(batch.exists())

    def test_batch_replace_failure_preserves_work(self):
        batch = self.batch()
        before = batch.read_bytes()
        with patch.object(queue, "atomic_bytes", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                queue.drain(self.vault, self.directory, capture_fn=lambda *args: {"disposition": "captured", "complete": False}, discover=False)
        self.assertEqual(batch.read_bytes(), before)

    def test_success_has_durable_journal_before_remove(self):
        batch = self.batch()
        result = queue.drain(self.vault, self.directory, capture_fn=lambda *args: {"disposition": "captured", "complete": True}, discover=False)
        self.assertFalse(batch.exists())
        self.assertEqual(result["completed"], 1)
        self.assertTrue((self.directory / "processed-v2.jsonl").exists())

    def test_spool_and_partial_retention(self):
        queue.enqueue(self.directory, {"session_id": "session-1", "transcript_path": "source", "source": "codex"})
        result = queue.drain(self.vault, self.directory, capture_fn=lambda *args: {"disposition": "captured", "complete": False}, discover=False)
        self.assertEqual(result["partial"], 1)
        self.assertTrue((self.directory / "queue.batch.jsonl").exists())

    def test_quota_retains_remaining_records(self):
        batch = self.batch()
        before = batch.read_bytes()
        def deferred(*args):
            raise capture.Deferred("quota")
        result = queue.drain(self.vault, self.directory, capture_fn=deferred, discover=False)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(batch.read_bytes(), before)


class HygieneTests(Fixture):
    def test_priority_aging_idempotent(self):
        text = "## Active Now\n\n**Personal**\n- Old item `touched: 2026-08-18`\n- Current item `touched: 2026-09-06`\n\n## Review\n\nReview here.\n\n## Parked / Watch\n- Parked item `touched: 2020-01-01`\n"
        revised, count, active = age_priorities(text, dt.date(2026, 9, 6))
        self.assertEqual(count, 1)
        self.assertEqual(active, 1)
        self.assertIn("Old item", revised.split("## Review")[1])
        self.assertEqual(age_priorities(revised, dt.date(2026, 9, 6))[0], revised)

    def test_hygiene_no_model_and_no_archive_changes(self):
        folder = self.vault.root / "02 - System Utilities & Machine Setup"
        folder.mkdir()
        (folder / "02 - System Utilities & Machine Setup.md").write_text(HEADER.replace("type: log", "type: index") + "\n# Index\n", encoding="utf-8")
        (folder / "A note.md").write_text(HEADER + "\n# A note\n", encoding="utf-8")
        frozen = self.vault.root / "09 - Archive/Old Memory/frozen.md"
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(b"old frozen bytes")
        report = hygiene(self.vault, fix=True, check_parity=False)
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(frozen.read_bytes(), b"old frozen bytes")
        again = hygiene(self.vault, fix=True, check_parity=False)
        self.assertEqual(again["repairs"], [])


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
        self.assertIn("checkpoint-context", text)

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
        self.assertEqual(len(list((self.vault.state / "requested").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
