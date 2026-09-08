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
import vault_core as core
from vault_hygiene import parity

REPO = Path(__file__).resolve().parents[2]


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="brain-export-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.vault = self.base / "Vault with spaces"
        self.auto = self.base / "Controller with spaces"
        self.auto.mkdir()
        for path in (REPO / "automation").iterdir():
            if path.is_file():
                shutil.copy2(path, self.auto / path.name)
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
        args = [sys.executable, str(REPO / "hooks/vault/validate-vault-frontmatter.py")]
        result = self.child(args, {"tool_input": {"file_path": str(target)}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing opening frontmatter", result.stderr)
        target.write_text("---\nstatus: active\nproject: custom-project\ntype: reference\nupdated_by: astra\nupdated: 2026-09-07\n---\n", encoding="utf-8")
        self.assertEqual(self.child(args, {"tool_input": {"file_path": str(target)}}).returncode, 0)

    def test_missing_controller_fails_open_and_logs(self):
        missing = self.base / "Uninstalled controller"
        env = dict(self.env, BRAIN_AUTOMATION_DIR=str(missing))
        result = self.child([sys.executable, str(REPO / "hooks/vault/validate-vault-frontmatter.py")], {}, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((missing / "hook-errors.jsonl").exists())
        result = self.child(["node", str(REPO / "hooks/vault/stop-vault-gate.js")], {}, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len((missing / "hook-errors.jsonl").read_text().splitlines()), 2)

    def test_session_end_prefers_public_environment_setting(self):
        legacy = self.base / "Unused legacy location"
        env = dict(self.env, VAULT_AUTOMATION_DIR=str(legacy))
        result = self.child(["node", str(REPO / "hooks/vault/session-end-enqueue.js")],
                            {"session_id": "portable", "transcript_path": str(self.base / "source.jsonl")}, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list((self.auto / "spool").glob("*.json"))), 1)
        self.assertFalse(legacy.exists())

    def test_stop_launcher_resolves_custom_paths_and_python(self):
        transcript = self.base / "source.jsonl"
        rows = [
            {"type": "user", "origin": {"kind": "human"}, "uuid": "portable-turn", "message": {"content": "Explain a useful finding"}},
            {"type": "assistant", "message": {"content": "Verified findings. " * 100}},
        ]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        result = self.child(["node", str(REPO / "hooks/vault/stop-vault-gate.js")],
                            {"session_id": "portable", "transcript_path": str(transcript)})
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertIn(str(self.vault / "10 - Resources/Vault Workflow Contract.md"), result.stdout)
        self.assertIn(str(self.auto / "vaultctl.py"), result.stdout)
        self.assertTrue(list((self.state / "requested").glob("*.json")))

    def test_one_client_and_two_client_parity(self):
        home = self.base / "Fresh home"
        for client, boot in ((".claude", "CLAUDE.md"), (".codex", "AGENTS.md")):
            root = home / client
            root.mkdir(parents=True)
            shutil.copy2(REPO / "boot" / boot, root / boot)
            shutil.copytree(REPO / "skills", root / "skills")
            self.assertEqual(parity(home), [])
        changed = home / ".codex/skills/handoff/SKILL.md"
        changed.write_text(changed.read_text(encoding="utf-8") + "\nChanged copy\n", encoding="utf-8")
        self.assertIn("Skill mirror mismatch: handoff", parity(home))
