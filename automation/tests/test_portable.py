"""Exercise the exported package with a fresh home and paths containing spaces."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault_adapters
import vault_core as core
from vault_hygiene import parity

REPO = Path(__file__).resolve().parents[2]


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="brain-export-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.vault = self.base / "Vault with spaces"
        self.auto = self.base / "Controller with spaces"
        self.auto.mkdir()
        for path in (REPO / "automation").iterdir():
            if path.is_file():
                shutil.copy2(path, self.auto / path.name)
        shutil.copytree(REPO / "automation/adapters", self.auto / "adapters")  # every hook goes through an adapter manifest
        shutil.copytree(REPO / "vault", self.vault)
        self.state = self.base / "Private state"
        self.backups = self.base / "Private snapshots"
        self.env = dict(os.environ, BRAIN_VAULT_ROOT=str(self.vault),
                        BRAIN_AUTOMATION_DIR=str(self.auto), BRAIN_STATE_DIR=str(self.state),
                        BRAIN_BACKUPS_DIR=str(self.backups), BRAIN_PYTHON=sys.executable,
                        PYTHONIOENCODING="utf-8")
        self.env.pop("VAULT_AUTOMATION", None)

    def child(self, args, payload=None, env=None):
        return subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, encoding="utf-8", env=env or self.env,
                              cwd=self.base, timeout=15)

    def ctl(self, *args):
        result = self.child([sys.executable, str(self.auto / "vaultctl.py"), *args])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_starter_validates_and_hygiene_uses_private_state(self):
        before = {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob("*.md")}
        self.assertEqual(self.ctl("validate")["outcome"], "valid")
        report = self.ctl("hygiene", "--no-parity")
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["outcome"], "verified")
        self.assertTrue((self.state / "hygiene-latest.json").exists())
        self.assertFalse((self.auto / "state-v2").exists())
        self.assertEqual(before, {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob("*.md")})

    def test_cli_commit_uses_custom_vault_and_snapshot_location(self):
        payload = self.base / "prepared operations.json"
        payload.write_text(json.dumps({"operations": [{"path": "00 - Inbox/Portable.md", "expected_sha256": None,
            "content": "---\nstatus: active\nproject: custom-project\ntype: reference\nupdated_by: astra\nupdated: 2026-09-07\n---\n\n# Portable\n"}]}), encoding="utf-8")
        self.ctl("commit", "--model", "gpt-6-astra", "--reason", "Isolated portability verification", "--input", str(payload))
        self.assertTrue((self.vault / "00 - Inbox/Portable.md").exists())
        self.assertTrue(list(self.backups.glob("*/manifest.json")))
        self.assertEqual(self.ctl("inspect", "00 - Inbox/Portable.md")[0]["path"], "00 - Inbox/Portable.md")

    def test_custom_project_and_optional_allowlist(self):
        text = "---\nstatus: active\nproject: my-other-project\ntype: reference\nupdated_by: astra\nupdated: 2026-09-07\n---\n"
        self.assertEqual(core.validate(text), [])
        self.assertTrue(core.validate(text.replace("my-other-project", "Bad Project")))
        with patch.dict(core.SCHEMA, project_allowlist=["personal"]):
            self.assertIn("Invalid project: my-other-project", core.validate(text))

    def test_post_hook_loads_custom_controller_and_checks_written_note(self):
        target = self.vault / "00 - Inbox/Hook fixture.md"
        target.write_text("# Missing metadata\n", encoding="utf-8")
        args = [sys.executable, str(REPO / "hooks/vault/agent-hook.py"), "claude", "PostToolUse"]
        payload = {"session_id": "portable", "tool_name": "Edit", "tool_input": {"file_path": str(target)}}
        result = self.child(args, payload)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing opening frontmatter", result.stderr)
        target.write_text("---\nstatus: active\nproject: custom-project\ntype: reference\nupdated_by: astra\nupdated: 2026-09-07\n---\n", encoding="utf-8")
        self.assertEqual(self.child(args, payload).returncode, 0)
        # The write guard refuses the same write before it happens, and leaves files outside the vault alone.
        guard = [sys.executable, str(REPO / "hooks/vault/agent-hook.py"), "claude", "PreToolUse"]
        refused = self.child(guard, payload)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Direct write to a vault note refused: 00 - Inbox/Hook fixture.md", refused.stderr)
        outside = dict(payload, tool_input={"file_path": str(self.base / "project.py")})
        self.assertEqual((self.child(guard, outside).returncode, self.child(guard, outside).stderr), (0, ""))

    def test_missing_controller_fails_open_and_logs(self):
        missing = self.base / "Uninstalled controller"
        env = dict(self.env, BRAIN_AUTOMATION_DIR=str(missing))
        for count, event in enumerate(("PostToolUse", "PreToolUse", "Stop", "SessionStart"), 1):
            result = self.child([sys.executable, str(REPO / "hooks/vault/agent-hook.py"), "claude", event], {}, env)
            self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
            self.assertEqual(len((missing / "hook-errors.jsonl").read_text().splitlines()), count)

    def test_stop_launcher_resolves_custom_paths_and_python(self):
        transcript = self.base / "source.jsonl"
        rows = [
            {"type": "user", "origin": {"kind": "human"}, "uuid": "portable-turn", "message": {"content": "Explain a useful finding"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "durable-1", "name": "Bash", "input": {"command": "git commit -m 'portable'"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "durable-1", "content": "committed"}]}},
            {"type": "assistant", "message": {"content": "Verified findings. " * 100}},
        ]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        result = self.child([sys.executable, str(REPO / "hooks/vault/agent-hook.py"), "claude", "Stop"],
                            {"session_id": "portable", "transcript_path": str(transcript)})
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn(str(self.vault / "10 - Resources/Vault Workflow Contract.md"), result.stdout)
        self.assertIn(str(self.auto / "vaultctl.py"), result.stdout)
        self.assertIn('load only the "Daily checkpoints and coverage" section', result.stdout)
        self.assertIn(f'--session portable --transcript "{transcript}"', result.stdout)
        self.assertTrue(list((self.state / "gate").glob("*.json")))

    def test_session_brief_adapter_prints_continuity_and_fails_open(self):
        start = [sys.executable, str(REPO / "hooks/vault/agent-hook.py"), "claude", "SessionStart"]
        result = self.child(start, {"source": "startup"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Brain: no sessions recorded yet.", result.stdout)
        self.assertIn("navigation, not evidence", result.stdout)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 720)
        # With a session in the payload the brief ends with the flags that checkpoint it.
        result = self.child(start, {"source": "startup", "session_id": "abc", "transcript_path": str(self.base / "abc.jsonl")})
        self.assertIn(f'This session\'s checkpoint flags: --source claude --session abc --transcript "{self.base / "abc.jsonl"}"', result.stdout)
        missing = self.base / "Uninstalled controller"
        result = self.child(start, {}, dict(self.env, BRAIN_AUTOMATION_DIR=str(missing)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("claude SessionStart", (missing / "hook-errors.jsonl").read_text(encoding="utf-8"))

    def test_one_two_and_n_agent_parity(self):
        home = self.base / "Fresh home"
        adapters = vault_adapters.load()
        self.assertEqual(parity(home), ["No installed client boot files"])
        # One agent, two, then every adapter: each copy is checked against one rendering.
        for count, name in enumerate(adapters, 1):
            adapter = adapters[name]
            target = vault_adapters.instructions_path(adapter, home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(vault_adapters.render_file(adapter), encoding="utf-8")
            for directory in vault_adapters.skill_dirs([name], home, adapters):
                if not directory.exists():
                    shutil.copytree(REPO / "skills", directory)
            self.assertEqual(parity(home), [], f"{count} agents")
        changed = home / ".agents/skills/handoff/SKILL.md"
        changed.write_text(changed.read_text(encoding="utf-8") + "\nChanged copy\n", encoding="utf-8")
        self.assertEqual(parity(home).count("Skill mirror mismatch: handoff"), 1)
        changed.write_bytes((REPO / "skills/handoff/SKILL.md").read_bytes())
        # Another agent's tail in this agent's block is drift, and so is a missing block.
        kiro = vault_adapters.instructions_path(adapters["kiro"], home)
        kiro.write_text(vault_adapters.render_file(adapters["qwen"]), encoding="utf-8")
        self.assertEqual(parity(home), ["Boot shared-rule block differs from this release: kiro"])
        claude = vault_adapters.instructions_path(adapters["claude"], home)
        claude.write_text("My own rules.\n", encoding="utf-8")
        self.assertIn("Missing shared-rule block: " + str(claude), parity(home))
