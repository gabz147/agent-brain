"""The transcript-free gate and the Codex hooks it drives, replayed from synthetic payloads."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_vault import Fixture
import vault_adapters
import vault_core as core
import vault_gate as gate
from vaultctl import main

REPO = Path(__file__).resolve().parents[2]
NOTE = "---\nstatus: active\nproject: meta\ntype: reference\nupdated_by: gpt-6\nupdated: 2026-09-05\n---\n# Gate note\n"
HAS_GIT = shutil.which("git") is not None


def patch_payload(cwd, session, *paths):
    body = "".join(f"*** Add File: {p}\n+text\n" for p in paths)
    return {"session_id": session, "cwd": str(cwd), "hook_event_name": "PostToolUse", "model": "gpt-6", "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n" + body + "*** End Patch\n"}}


class GateTests(Fixture):
    def setUp(self):
        super().setUp()
        self.work = self.base / "work"
        self.work.mkdir()
        self.codex = vault_adapters.load()["codex"]

    def run_hook(self, event, payload, config=None):
        return gate.hook("codex", event, payload, self.codex, self.vault, config)

    def stop(self, session="s-1", at=10_000_000, **extra):
        payload = dict({"session_id": session, "cwd": str(self.work), "model": "gpt-6", "transcript_path": None,
                        "hook_event_name": "Stop", "stop_hook_active": False}, **extra)
        return gate.emit("json-decision-block", gate.stop(self.vault, "codex", payload, current_ms=at, directory=self.directory))

    def test_patch_paths_and_extractors(self):
        command = "*** Begin Patch\n*** Update File: a.md\n@@\n*** Delete File: b.py\n*** Add File: c d.md\n*** Move to: e.md\n*** End Patch"
        self.assertEqual(gate.patch_paths(command), ["a.md", "b.py", "c d.md", "e.md"])
        n, m = str(self.base / "n.md"), str(self.base / "m.md")
        payload = {"cwd": str(self.work), "tool_input": {"file_path": n, "edits": [{"file_path": m}, {"nope": 1}]}}
        self.assertEqual(gate.written_paths(payload, ["tool_input.file_path", "tool_input.edits[].file_path", "tool_input.missing"]), [n, m])
        self.assertEqual(gate.written_paths(patch_payload(self.work, "s", "rel.md"), ["apply_patch:tool_input.command"]), [str(self.work / "rel.md")])
        self.assertTrue(gate.scratch(str(self.base / "x" / "scratchpad" / "a.md"), self.work))
        self.assertFalse(gate.scratch(str(self.work / "a.md"), self.work))

    def test_no_delta_means_no_request_and_flags_short_circuit(self):
        self.assertEqual(self.stop(), (0, "", ""))
        self.assertEqual(self.stop(stop_hook_active=True), (0, "", ""))
        self.assertEqual(gate.stop(self.vault, "codex", {"cwd": str(self.work)}), "")
        (self.directory / "automation-state.json").write_text(json.dumps({"paused": True, "scope": "all"}), encoding="utf-8")
        self.run_hook("PostToolUse", patch_payload(self.work, "s-1", "code.py"))
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_write_requests_once_per_delta_and_window_then_a_receipt_covers_it(self):
        self.assertEqual(self.run_hook("PostToolUse", patch_payload(self.work, "s-1", "code.py")), (0, "", ""))
        code, out, err = self.stop()
        self.assertEqual(code, 0)
        request = json.loads(out)
        self.assertEqual(request["decision"], "block")
        self.assertTrue(request["reason"].startswith(gate.PREFIX + "s-1."))
        self.assertIn("--source codex --session s-1 --model gpt-6", request["reason"])
        # Same delta, or inside the ten-minute window: silent.
        self.assertEqual(self.stop(at=10_000_000 + 60_000), (0, "", ""))
        self.assertEqual(self.stop(at=10_000_000 + 700_000), (0, "", ""))
        self.run_hook("PostToolUse", patch_payload(self.work, "s-1", "more.py"))
        self.assertEqual(self.stop(at=10_000_000 + 120_000), (0, "", ""))
        self.assertTrue(self.stop(at=10_000_000 + 700_000)[1])
        # The agent checkpoints; the recorded work no longer asks.
        base = ["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups), "checkpoint"]
        main(base + ["--source", "codex", "--session", "s-1", "--model", "gpt-6", "--topic", "Gate", "--done", "Wrote code"])
        self.assertEqual(self.stop(at=10_000_000 + 2_000_000), (0, "", ""))
        # Another session is unaffected by this one's receipt.
        self.run_hook("PostToolUse", patch_payload(self.work, "s-2", "other.py"))
        self.assertTrue(self.stop(session="s-2", at=10_000_000 + 2_000_000)[1])

    def test_long_answer_counts_only_beside_tool_use(self):
        text = "x" * 2000
        self.assertEqual(self.stop(last_assistant_message=text), (0, "", ""))
        config = {"hooks": {"shell_log": True}}
        for _ in range(5):
            self.run_hook("PostToolUse", {"session_id": "s-1", "cwd": str(self.work), "tool_name": "Bash",
                                          "tool_input": {"command": "ls -la"}}, config)
        self.assertEqual(self.stop(last_assistant_message="short"), (0, "", ""))
        self.assertTrue(self.stop(at=10_000_000 + 700_000, last_assistant_message=text)[1])
        # Shell calls are not logged unless shell logging is on.
        self.run_hook("PostToolUse", {"session_id": "s-3", "cwd": str(self.work), "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}})
        self.assertFalse(gate.turnlog_path(self.vault, gate._key("codex", {"session_id": "s-3"})[0]).exists())

    @unittest.skipUnless(HAS_GIT, "needs git")
    def test_git_delta_since_session_start(self):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        (self.work / "a.txt").write_text("a", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.work), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.work), "commit", "-qm", "one"], check=True, env=env)
        with mock.patch("vault_recall.session_brief", return_value="brief"):
            self.assertEqual(self.run_hook("SessionStart", {"session_id": "s-1", "cwd": str(self.work), "source": "startup"}), (0, "brief", ""))
        self.assertEqual(self.stop(), (0, "", ""))
        (self.work / "b.txt").write_text("b", encoding="utf-8")  # one more dirty file, made by a shell nobody logged
        self.assertTrue(self.stop(at=10_000_000 + 700_000)[1])

    def test_home_and_root_have_no_fingerprint(self):
        self.assertEqual(gate.git_fingerprint(Path.home()), "unavailable")
        self.assertEqual(gate.git_fingerprint(Path(self.base.anchor)), "unavailable")

    def test_controller_commits_count_but_checkpoints_do_not(self):
        with mock.patch("vault_recall.session_brief", return_value=""):
            self.run_hook("SessionStart", {"session_id": "s-1", "cwd": str(self.work)})
        base = ["--vault", str(self.vault.root), "--state", str(self.vault.state), "--backups", str(self.vault.backups), "checkpoint"]
        main(base + ["--source", "other", "--model", "m", "--topic", "Other agent", "--done", "Its own checkpoint"])
        self.assertEqual(self.stop(), (0, "", ""))
        self.vault.commit([{"path": "00 - Inbox/Gate note.md", "expected_sha256": None, "content": NOTE}], "gpt-6", "Add a note")
        self.assertTrue(self.stop(at=10_000_000 + 700_000)[1])

    def test_post_tool_validates_vault_notes_it_wrote(self):
        note = self.vault.root / "00 - Inbox/Bad.md"
        note.parent.mkdir()
        note.write_text("# no metadata\n", encoding="utf-8")
        code, out, err = self.run_hook("PostToolUse", patch_payload(self.vault.root, "s-1", "00 - Inbox/Bad.md"))
        self.assertEqual(code, 2)
        self.assertIn("Vault validation failed", err)
        note.write_text(NOTE, encoding="utf-8")
        self.assertEqual(self.run_hook("PostToolUse", patch_payload(self.vault.root, "s-1", "00 - Inbox/Bad.md")), (0, "", ""))
        # A payload that names no path falls back to notes modified in the last few seconds.
        note.write_text("# broken again\n", encoding="utf-8")
        code, _, err = self.run_hook("PostToolUse", {"session_id": "s-1", "cwd": str(self.work), "tool_name": "mcp__fs__write", "tool_input": {}})
        self.assertEqual(code, 2)
        self.assertIn("Bad.md", err)

    def test_dialects(self):
        self.assertEqual(gate.emit("exit2-stdout-async", "x"), (2, "x", ""))
        self.assertEqual(gate.emit("json-followup", "x"), (0, '{"followup_message": "x"}', ""))
        self.assertEqual(gate.emit("exit1-stderr", "x"), (1, "", "x"))
        self.assertEqual(gate.emit("none", "x"), (0, "", ""))
        self.assertEqual(gate.emit("json-decision-block", ""), (0, "", ""))


class InstalledCodexHookTests(unittest.TestCase):
    """The hooks.json the installer writes, run the way Codex runs it: $SHELL -lc on POSIX, cmd.exe /C on Windows."""

    def test_installed_codex_hooks_round_trip(self):
        spec = importlib.util.spec_from_file_location("brain_install_gate", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(prefix="brain codex hooks ") as tmp:
            home = Path(tmp).resolve() / "Some User"
            vault = home / "Brain"
            hooks_file = home / ".codex/hooks.json"
            hooks_file.parent.mkdir(parents=True)
            unrelated = {"type": "command", "command": "echo unrelated"}
            hooks_file.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [unrelated]}]}}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(home, vault, apply=True, client="codex")
            data = json.loads(hooks_file.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["Stop"][0]["hooks"], [unrelated])
            self.assertEqual(set(data["hooks"]), {"SessionStart", "PostToolUse", "Stop"})
            self.assertEqual(installer.installation(home, vault, client="codex"), {})
            env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k not in ("VAULT_AUTOMATION_DIR", "VAULT_AUTOMATION")}
            env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")

            def run(event, payload):
                group = data["hooks"][event][-1]
                line = group["hooks"][0]["command"]
                command = f'cmd.exe /C "{line}"' if os.name == "nt" else ["/bin/sh", "-lc", line]
                return subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                                      env=env, cwd=str(home), timeout=60)

            started = run("SessionStart", {"session_id": "c-1", "cwd": str(home), "source": "startup", "model": "gpt-6"})
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertIn("Brain", started.stdout)
            bad = vault / "00 - Inbox/Codex note.md"
            bad.write_text("# missing metadata\n", encoding="utf-8")
            posted = run("PostToolUse", patch_payload(vault, "c-1", "00 - Inbox/Codex note.md"))
            self.assertEqual(posted.returncode, 2, posted.stdout + posted.stderr)
            self.assertIn("Vault validation failed", posted.stderr)
            stopped = run("Stop", {"session_id": "c-1", "cwd": str(home), "model": "gpt-6", "transcript_path": None, "stop_hook_active": False})
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            reason = json.loads(stopped.stdout)["reason"]
            self.assertTrue(reason.startswith(gate.PREFIX + "c-1."))
            again = run("Stop", {"session_id": "c-1", "cwd": str(home), "stop_hook_active": True})
            self.assertEqual((again.returncode, again.stdout), (0, ""))
            # Garbage in fails open and leaves a diagnostic.
            broken = run("Stop", "not json")
            self.assertEqual((broken.returncode, broken.stdout), (0, ""))
            self.assertIn("codex Stop", (home / ".agent-brain/automation/hook-errors.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
