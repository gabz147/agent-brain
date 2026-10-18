"""Real installer subprocess, fresh home, preservation, and portable source packets."""
import contextlib
import io
import json
try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "automation"))
import vault_adapters  # noqa: E402


class InstallTests(unittest.TestCase):
    def test_startup_context_budget(self):
        # Byte budgets are deterministic across clients/tokenizers and need no dependency.
        index = (REPO / "vault/VAULT-INDEX.md").read_bytes()
        self.assertLessEqual(len(vault_adapters.block_body().encode()), 2400, "shared block body")
        for name, adapter in vault_adapters.load().items():
            boot = vault_adapters.render_file(adapter).encode("utf-8")
            self.assertLessEqual(len(boot), 3600, name)
            self.assertLessEqual(len(boot) + len(index), 6000, name + " plus starter map")
            text = boot.decode("utf-8")
            self.assertIn("Greetings and self-contained questions: no vault reads", text)
            self.assertIn("replaces older blanket startup/compaction reads", text)
        for path in ("vault/VAULT-INDEX.md", "vault/Active Priorities.md", "skills/obsidian-vault/SKILL.md"):
            text = (REPO / path).read_text(encoding="utf-8")
            self.assertNotIn("fully at startup", text, path)
            self.assertNotIn("in full at startup", text, path)
            self.assertNotIn("Checked at the start of every conversation", text, path)

    def test_neutral_home_config_is_written_and_read_without_env(self):
        spec = importlib.util.spec_from_file_location("brain_install", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(prefix="brain-config-") as tmp:
            home = Path(tmp).resolve() / "home"
            vault = home / "Notes" / "My Brain"
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(home, vault, apply=True, client="codex")
            config = json.loads((home / ".agent-brain/config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["vault_root"], str(vault))
            self.assertEqual(config["clients"], ["codex"])
            self.assertEqual(config["automation_dir"], str(home / ".agent-brain/automation"))
            # Every tier reads config.json, so client settings receive no Brain variables.
            self.assertFalse((home / ".codex/config.toml").exists())
            # A v1 home has no config.json: the other client's injected settings still decide the vault, so adding
            # a client without --vault joins the existing vault instead of creating ~/Documents/Brain.
            (home / ".agent-brain/config.json").unlink()
            if tomllib is not None:  # the join reads Codex's TOML settings, which 3.10 cannot parse
                (home / ".codex/config.toml").write_bytes(installer.toml_bytes({"shell_environment_policy": {"set": {"BRAIN_VAULT_ROOT": str(vault)}}}))
                self.assertEqual(installer.configured_vault(home, "claude"), vault)
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(home, vault, apply=True, client="claude")
            config = json.loads((home / ".agent-brain/config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["clients"], ["claude", "codex"])
            self.assertEqual(config["vault_root"], str(vault))
            # With no BRAIN_* variables at all, the controller and the hook adapter resolve through the config.
            env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k not in ("VAULT_AUTOMATION_DIR", "VAULT_AUTOMATION")}
            env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
            probe = subprocess.run([sys.executable, "-c", "import vault_core; print(vault_core.DEFAULT_VAULT)"],
                                   cwd=str(home / ".agent-brain/automation"), capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(probe.stdout.strip(), str(vault), probe.stderr)
            note = vault / "00 - Inbox/Config probe.md"
            note.write_text("# no metadata\n", encoding="utf-8")
            hook = subprocess.run([sys.executable, str(home / ".claude/hooks/vault/validate-vault-frontmatter.py")],
                                  input=json.dumps({"tool_input": {"file_path": str(note)}}), capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(hook.returncode, 2, hook.stdout + hook.stderr)
            self.assertIn("Missing opening frontmatter", hook.stderr)

    def test_existing_controller_stays_put_and_injected_paths_stay_current(self):
        spec = importlib.util.spec_from_file_location("brain_install_home", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(prefix="brain-legacy-") as tmp:
            home = Path(tmp).resolve() / "home"
            legacy = home / ".claude/vault-automation"
            legacy.mkdir(parents=True)
            (legacy / "vaultctl.py").write_text("# v1 controller\n", encoding="utf-8")
            (legacy / "state-v2").mkdir()
            settings = home / ".claude/settings.json"
            settings.write_text(json.dumps({"env": {"BRAIN_VAULT_ROOT": str(home / "Old"), "OTHER": "kept"}}), encoding="utf-8")
            self.assertEqual(installer.automation_dir(home), legacy)
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(home, home / "Brain", apply=True, replace=True, client="claude")
            self.assertTrue((legacy / "vault_gate.py").is_file())
            self.assertTrue((legacy / "state-v2").is_dir())
            self.assertFalse((home / ".agent-brain/automation").exists())
            self.assertEqual(json.loads((home / ".agent-brain/config.json").read_text(encoding="utf-8"))["automation_dir"], str(legacy))
            env = json.loads(settings.read_text(encoding="utf-8"))["env"]
            # An injected value is kept in step with the config; nothing new is added.
            self.assertEqual(env, {"BRAIN_VAULT_ROOT": str(home / "Brain"), "OTHER": "kept"})
            launcher = home / ".agent-brain/bin" / ("brain.cmd" if os.name == "nt" else "brain")
            self.assertIn(str(legacy), launcher.read_text(encoding="utf-8"))

    def test_stale_other_client_is_refused_before_any_write(self):
        spec = importlib.util.spec_from_file_location("brain_install", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory(prefix="brain-stale-") as tmp:
            home = Path(tmp).resolve() / "home"
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(home, home / "Brain", apply=True, client="both")
            self.assertEqual(installer.stale_clients(home, "claude"), [])
            older = home / ".agents/skills/handoff/SKILL.md"
            older.write_text(older.read_text(encoding="utf-8") + "\nolder release\n", encoding="utf-8")
            self.assertEqual(installer.stale_clients(home, "claude"), ["codex"])
            self.assertEqual(installer.stale_clients(home, "both"), [])
            result = subprocess.run([sys.executable, str(REPO / "install.py"), "--home", str(home), "--client", "claude", "--apply", "--replace-workflow"],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn("rerun with --client both", result.stderr)
            self.assertNotIn("WRITE", result.stdout)
            (home / ".agent-brain/config.json").write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "config.json is not valid JSON"):
                installer.read_config(home)

    def test_upgrade_prunes_only_the_retired_session_end_hook(self):
        spec = importlib.util.spec_from_file_location("brain_install", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        retired = {"type": "command", "command": "node", "args": ["/home/x/.claude/hooks/vault/session-end-enqueue.js"]}
        other = {"type": "command", "command": "node", "args": ["/home/x/.claude/hooks/other-session-end.js"]}
        old_stop = {"type": "command", "command": "node", "args": ["/home/x/.claude/hooks/vault/stop-vault-gate.js"]}
        stop = {"type": "command", "command": "python", "args": ["/home/x/.claude/hooks/vault/stop-vault-gate.py"]}
        hooks = {"SessionEnd": [{"hooks": [retired]}, {"hooks": [other, dict(retired)]}], "Stop": [{"hooks": [old_stop]}, {"hooks": [stop]}]}
        installer.prune_retired_hooks(hooks)
        self.assertEqual(hooks, {"SessionEnd": [{"hooks": [other]}], "Stop": [{"hooks": [stop]}]})
        only_retired = {"SessionEnd": [{"hooks": [retired]}]}
        installer.prune_retired_hooks(only_retired)
        self.assertEqual(only_retired, {})

    def test_no_packaged_automation_starts_a_model(self):
        # The background capture drain was removed: nothing shipped may launch a model CLI on its own.
        self.assertFalse((REPO / "automation/vault_queue.py").exists())
        self.assertFalse((REPO / "automation/drain-queue.ps1").exists())
        self.assertFalse((REPO / "hooks/vault/session-end-enqueue.js").exists())
        pattern = re.compile(r"""which\(\s*["'](claude|codex)["']|["']claude["']\s*,\s*["']-p["']|codex\s+exec""")
        for path in list((REPO / "automation").glob("*.py")) + list((REPO / "automation").glob("*.ps1")) + list((REPO / "hooks").rglob("*.*")):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8", errors="replace")), str(path))

    @unittest.skipUnless(importlib.util.find_spec("pymupdf"), "Optional PDF extraction needs PyMuPDF")
    def test_pdf_packet_preserves_pages_and_flags_empty_pages(self):
        import pymupdf as fitz
        with tempfile.TemporaryDirectory(prefix="brain pdf ") as tmp:
            base = Path(tmp)
            source = base / "source.pdf"
            with fitz.open() as document:
                document.new_page().insert_text((50, 50), "Source evidence: 17 spans")
                document.new_page()
                document.save(source)
            original = source.read_bytes()
            helper = REPO / "skills/source-to-vault/scripts/source_packet.py"
            result = subprocess.run([sys.executable, str(helper), str(source), "--output", str(base / "packets")],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            packet = Path(result.stdout.strip())
            extracted = (packet / "extracted.md").read_text(encoding="utf-8")
            self.assertIn("## Page 1", extracted)
            self.assertIn("17 spans", extracted)
            self.assertIn("Page 2: no extracted text", extracted)
            self.assertEqual((packet / "original.pdf").read_bytes(), original)
            self.assertEqual(source.read_bytes(), original)

    def test_install_repeat_upgrade_and_source_packet(self):
        with tempfile.TemporaryDirectory(prefix="brain laptop ") as tmp:
            home = Path(tmp).resolve() / "Different User"
            vault = home / "Custom Vault"
            args = [sys.executable, str(REPO / "install.py"), "--home", str(home), "--vault", str(vault)]

            def run(command, success=True, env=None):
                result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result

            run(args)
            self.assertFalse(home.exists(), "Preview must not write")
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"model": "existing-model", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "unrelated-hook"}]}]}}))
            run(args + ["--apply"])
            auto = home / ".agent-brain/automation"
            self.assertTrue((auto / "vault_links.mjs").is_file())
            self.assertTrue((vault / "Home.md").is_file())
            self.assertTrue((vault / "10 - Resources/Vault Actions.md").is_file())
            self.assertIn("bases", json.loads((vault / ".obsidian/core-plugins.json").read_text()))
            env = dict(os.environ, BRAIN_VAULT_ROOT=str(vault), BRAIN_AUTOMATION_DIR=str(auto),
                       BRAIN_STATE_DIR=str(home / "private-state"), BRAIN_BACKUPS_DIR=str(home / "private-backups"))
            report = run([sys.executable, str(auto / "vaultctl.py"), "validate"], env=env)
            self.assertEqual(json.loads(report.stdout)["outcome"], "valid")
            # Path.home() must resolve the fixture for installed mirror checks too.
            env.update(USERPROFILE=str(home), HOME=str(home))
            report = run([sys.executable, str(auto / "vaultctl.py"), "hygiene"], env=env)
            self.assertEqual(json.loads(report.stdout)["issues"], [])
            data = json.loads(settings.read_text())
            self.assertEqual(data["model"], "existing-model")
            self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "unrelated-hook")
            self.assertEqual(len(data["hooks"]["Stop"]), 2)
            # Verification appends private diagnostics; installed files and notes stay idempotent.
            before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "state-v2" not in p.parts}
            run(args + ["--apply"])
            self.assertEqual(before, {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "state-v2" not in p.parts})
            for skill in ("obsidian-vault", "handoff", "source-to-vault"):
                self.assertEqual((home / f".claude/skills/{skill}/SKILL.md").read_bytes(),
                                 (home / f".agents/skills/{skill}/SKILL.md").read_bytes())

            note = vault / "VAULT-INDEX.md"
            note.write_text(note.read_text(encoding="utf-8") + "\nUser's retained note.\n", encoding="utf-8")
            original = note.read_bytes()
            boot = home / ".codex/AGENTS.md"
            legacy = "Old rule. Fully read yesterday's daily note at startup.\n" * 150
            boot.write_text(boot.read_text(encoding="utf-8").replace("Evidence only:", legacy) + "\nCustom client rule.\n", encoding="utf-8")
            previous_boot = boot.read_bytes()
            queue = auto / "queue.jsonl"
            queue.write_text('pending source\n')
            schema = auto / "vault-schema.json"
            schema.write_text(schema.read_text() + "\n")
            previous_schema = schema.read_bytes()
            run(args + ["--apply"], success=False)
            run(args + ["--apply", "--replace-workflow"])
            self.assertEqual(note.read_bytes(), original)
            self.assertIn("Custom client rule.", boot.read_text(encoding="utf-8"))
            self.assertIn("Evidence only:", boot.read_text(encoding="utf-8"))
            self.assertNotIn(legacy, boot.read_text(encoding="utf-8"))
            self.assertLessEqual(len(boot.read_bytes()), 3700)
            self.assertEqual(schema.read_bytes(), previous_schema)
            self.assertEqual(queue.read_text(), 'pending source\n')
            self.assertIn(previous_boot, [p.read_bytes() for p in (home / "Documents/Brain Install Backups").rglob("*.bak")])

            source = home / "source.txt"
            source.write_text("A verified source fixture.", encoding="utf-8")
            helper = home / ".agents/skills/source-to-vault/scripts/source_packet.py"
            packet_args = [sys.executable, str(helper), str(source), "--output"]
            run(packet_args + [str(vault / "packets")], success=False, env=env)
            output = home / "project/packets"
            first = run(packet_args + [str(output)], env=env)
            second = run(packet_args + [str(output)], env=env)
            self.assertEqual(first.stdout, second.stdout)
            packet = Path(first.stdout.strip())
            self.assertEqual((packet / "original.txt").read_bytes(), source.read_bytes())
            (packet / "extracted.md").write_text("tampered")
            run(packet_args + [str(output)], success=False, env=env)

            source = home / "fixture.docx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Source evidence</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>17 spans</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
            result = run([sys.executable, str(helper), str(source), "--output", str(output)], env=env)
            extracted = (Path(result.stdout.strip()) / "extracted.md").read_text(encoding="utf-8")
            self.assertIn("## Paragraph 1", extracted)
            self.assertIn("## Table 2", extracted)
            self.assertIn("17 spans", extracted)


class SourcePacketSafetyTests(unittest.TestCase):
    def test_existing_packet_identity_and_names_are_checked(self):
        spec = importlib.util.spec_from_file_location("source_packet", REPO / "skills/source-to-vault/scripts/source_packet.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            source = base / "source.txt"
            source.write_text("A verified source fixture.", encoding="utf-8")
            packet = module.packet(source, base / "packets")
            self.assertEqual(module.packet(source, base / "packets"), packet)
            manifest_path = packet / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for change in ({"source_sha256": "0" * 64}, {"files": {**manifest["files"], "../escape.txt": "0" * 64}}):
                manifest_path.write_text(json.dumps({**manifest, **change}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    module.packet(source, base / "packets")


if __name__ == "__main__":
    unittest.main()
