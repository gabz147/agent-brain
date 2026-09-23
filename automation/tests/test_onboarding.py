"""Public setup: each client, preservation, guided choices and archive trust boundaries."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import bootstrap
import install


class OnboardingTests(unittest.TestCase):
    def test_upgrade_migrates_only_known_timestamp_rule_with_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="brain legacy ") as tmp:
            home = Path(tmp).resolve() / "Home"
            vault = home / "Brain"
            with contextlib.redirect_stdout(io.StringIO()):
                install.install(home, vault, apply=True, client="codex")
            contract = vault / "10 - Resources/Vault Workflow Contract.md"
            current = contract.read_text(encoding="utf-8")
            legacy = re.sub(r"^- Updated:.*$", "- Updated: an actual calendar date in `YYYY-MM-DD`, taken from the system clock at the write.", current, flags=re.M)
            legacy += "\nUser-specific instructions must survive.\n"
            contract.write_text(legacy, encoding="utf-8")
            before = contract.read_bytes()
            note = vault / "VAULT-INDEX.md"
            note_before = note.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                install.install(home, vault, client="codex")
                self.assertEqual(contract.read_bytes(), before)
                install.install(home, vault, apply=True, replace=True, client="codex")
                install.verify(home, vault)
                after = contract.read_bytes()
                install.install(home, vault, apply=True, replace=True, client="codex")
            self.assertEqual(contract.read_bytes(), after)
            self.assertEqual(note.read_bytes(), note_before)
            self.assertIn(b"User-specific instructions must survive.", after)
            self.assertIn(b"updated_by: automation", after)
            snapshots = list((home / "Brain Backups/versions").glob("*/*.before"))
            self.assertIn(before, [p.read_bytes() for p in snapshots])
            # The immediately preceding release used an ISO timestamp rule.
            iso_rule = "- Updated: actual local write time in `YYYY-MM-DDTHH:mm:ss+/-HH:mm`; legacy `YYYY-MM-DD` dates remain valid. The writer uses the system clock and timezone."
            contract.write_text(re.sub(r"^- Updated:.*$", iso_rule,
                                      contract.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                install.install(home, vault, apply=True, replace=True, client="codex")
                install.verify(home, vault)
            self.assertIn("User-specific instructions must survive.", contract.read_text(encoding="utf-8"))
            self.assertIsNone(install.timestamp_migration(vault))

    def test_native_codex_is_found_before_path_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            local = home / "AppData/Local"
            default = local / "Programs/OpenAI/Codex/bin" if os.name == "nt" else home / ".local/bin"
            for directory in (default, home / "Chosen bin"):
                target = directory / ("codex.exe" if os.name == "nt" else "codex")
                target.parent.mkdir(parents=True)
                target.write_bytes(b"fixture")
                env = {"LOCALAPPDATA": str(local), "CODEX_INSTALL_DIR": "" if directory == default else str(directory)}
                with patch.object(install.shutil, "which", return_value=None), patch.object(Path, "home", return_value=home), patch.dict(os.environ, env):
                    self.assertEqual(install.executable("codex"), [str(target)])

    def test_each_client_then_add_other_preserves_notes_and_settings(self):
        for client in ("claude", "codex", "both"):
            with self.subTest(client=client), tempfile.TemporaryDirectory(prefix="brain choose ") as tmp:
                home = Path(tmp).resolve() / "New User"
                vault = home / "Custom Brain"
                # An unrelated boot file does not opt an unselected client into Brain.
                other = "codex" if client == "claude" else "claude"
                other_boot = home / ("." + other) / ("AGENTS.md" if other == "codex" else "CLAUDE.md")
                if client != "both":
                    other_boot.parent.mkdir(parents=True)
                    other_boot.write_text("My unrelated startup instructions.\n")
                config = home / ".codex/config.toml"
                config.parent.mkdir(parents=True, exist_ok=True)
                original = '# retain via backup\nmodel = "my-model"\napproval_policy = "on-request"\n[shell_environment_policy]\ninherit = "core"\n[shell_environment_policy.set]\nCUSTOM = "retained"\n'
                config.write_text(original, encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    install.install(home, vault, apply=True, client=client)
                    install.verify(home, vault)
                for name in install.selected(client):
                    skills = home / ("." + name) / "skills"
                    self.assertEqual({p.name for p in skills.iterdir()}, set(install.SKILLS))
                if client != "both":
                    self.assertEqual(other_boot.read_text(), "My unrelated startup instructions.\n")
                    self.assertFalse((home / ("." + other) / "skills").exists())
                if client == "codex":
                    self.assertFalse((home / ".claude/settings.json").exists())
                    self.assertFalse((home / ".claude/hooks").exists())
                if client == "claude":
                    self.assertEqual(config.read_text(), original)
                else:
                    data = tomllib.loads(config.read_text(encoding="utf-8"))
                    self.assertEqual(data["approval_policy"], "on-request")
                    self.assertEqual(data["model"], "my-model")
                    self.assertEqual(data["shell_environment_policy"]["set"]["CUSTOM"], "retained")
                    self.assertEqual(data["shell_environment_policy"]["set"]["BRAIN_VAULT_ROOT"], str(vault))
                self.assertEqual(install.configured_vault(home, client), vault)
                self.assertEqual(install.installation(home, vault, client=client), {})
                note = vault / "VAULT-INDEX.md"
                note.write_text(note.read_text(encoding="utf-8") + "\nA private note to retain.\n", encoding="utf-8")
                before = note.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()):
                    install.install(home, vault, apply=True, replace=True, client="both")
                    install.verify(home, vault)
                self.assertEqual(before, note.read_bytes())
                self.assertEqual(install.installation(home, vault), {})
                if client != "both":
                    self.assertIn("My unrelated startup instructions.", other_boot.read_text(encoding="utf-8"))
                self.assertTrue((home / ".claude/vault-automation/FIRST-CHECKPOINT.md").is_file())

    def test_wizard_decline_and_apply(self):
        with tempfile.TemporaryDirectory(prefix="brain wizard ") as tmp:
            home = Path(tmp).resolve() / "New User"
            args = ["install.py", "--wizard", "--home", str(home)]
            with patch.object(sys, "argv", args), patch.object(sys.stdin, "isatty", return_value=True), patch.object(install, "doctor", return_value=[]), patch("builtins.input", side_effect=["2", "", "n"]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(install.main(), 0)
            self.assertFalse(home.exists())
            with patch.object(sys, "argv", args), patch.object(sys.stdin, "isatty", return_value=True), patch.object(install, "doctor", return_value=[]), patch("builtins.input", side_effect=["2", "", "y"]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(install.main(), 0)
            self.assertTrue((home / "Documents/Brain/VAULT-INDEX.md").is_file())
            self.assertFalse((home / ".claude/settings.json").exists())

    def test_unsafe_paths_conflicts_and_custom_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "Home"
            home.mkdir()
            for bad in (home / ".codex/Brain", REPO / "vault", home):
                result = subprocess.run([sys.executable, str(REPO / "install.py"), "--home", str(home), "--vault", str(bad), "--apply"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
            with self.assertRaises(ValueError):
                install.selected("unknown")
            for client, value in (("claude", home / "One"), ("codex", home / "Two")):
                directory = home / ("." + client)
                directory.mkdir(exist_ok=True)
                if client == "claude":
                    (directory / "settings.json").write_text(json.dumps({"env": {"BRAIN_VAULT_ROOT": str(value)}}))
                else:
                    (directory / "config.toml").write_bytes(install.toml_bytes({"shell_environment_policy": {"set": {"BRAIN_VAULT_ROOT": str(value)}}}))
            with self.assertRaisesRegex(ValueError, "different vaults"):
                install.configured_vault(home, "both")

    def test_archive_rejects_unsafe_members_before_extracting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, mode in (("../escape.py", 0), ("/absolute", 0), ("repo/../escape", 0), ("repo\\escape", 0), ("repo/link", stat.S_IFLNK | 0o777)):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.filename = name  # Preserve malicious backslashes even on Windows.
                    entry.external_attr = mode << 16
                    archive.writestr(entry, "outside")
                with self.assertRaises(ValueError):
                    bootstrap.unpack(stream.getvalue(), root)
                self.assertEqual(list(root.iterdir()), [])

    def test_bootstrap_runs_real_installer_from_downloaded_archive(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("install.py", "FIRST-CHECKPOINT.md"):
                archive.write(REPO / name, "brain/" + name)
            for directory in ("automation", "boot", "skills", "settings", "vault"):
                for path in (REPO / directory).rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        archive.write(path, "brain/" + path.relative_to(REPO).as_posix())
        with tempfile.TemporaryDirectory(prefix="brain archive ") as tmp:
            home = Path(tmp).resolve() / "New User"
            args = ["bootstrap.py", "--home", str(home), "--client", "codex", "--apply"]
            run = subprocess.run
            with patch.object(sys, "argv", args), patch.object(bootstrap, "download", side_effect=[json.dumps({"sha": "a" * 40}).encode(), stream.getvalue()]), patch.object(bootstrap.subprocess, "run", side_effect=lambda *a, **kw: run(*a, **kw, capture_output=True, text=True)):
                self.assertEqual(bootstrap.main(), 0)
            self.assertTrue((home / "Documents/Brain/VAULT-INDEX.md").is_file())
            self.assertFalse((home / ".claude/settings.json").exists())

    def test_installed_claude_hooks_run_directly_with_special_paths(self):
        if not shutil.which("node"):
            self.skipTest("Hook check requires Node")
        with tempfile.TemporaryDirectory(prefix="brain hook ") as tmp:
            home = Path(tmp).resolve() / "Someone's $notes"
            vault = home / "Brain"
            with contextlib.redirect_stdout(io.StringIO()):
                install.install(home, vault, apply=True, client="claude")
            settings = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
            env = dict(os.environ, **settings["env"], PYTHONIOENCODING="utf-8")
            for event in ("Stop", "SessionEnd", "PostToolUse"):
                hook = settings["hooks"][event][0]["hooks"][0]
                result = subprocess.run([hook["command"], *hook["args"]], input="{}", capture_output=True, text=True, env=env, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((home / ".claude/vault-automation/hook-errors.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
