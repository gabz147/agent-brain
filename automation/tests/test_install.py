"""Real installer subprocess, fresh home, preservation, and portable source packets."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
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
            home = Path(tmp) / "Different User"
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
            auto = home / ".claude/vault-automation"
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
            before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
            run(args + ["--apply"])
            self.assertEqual(before, {p: p.read_bytes() for p in home.rglob("*") if p.is_file()})
            for skill in ("obsidian-vault", "handoff", "source-to-vault"):
                self.assertEqual((home / f".claude/skills/{skill}/SKILL.md").read_bytes(),
                                 (home / f".codex/skills/{skill}/SKILL.md").read_bytes())

            note = vault / "VAULT-INDEX.md"
            note.write_text(note.read_text(encoding="utf-8") + "\nUser's retained note.\n", encoding="utf-8")
            original = note.read_bytes()
            boot = home / ".codex/AGENTS.md"
            boot.write_text(boot.read_text(encoding="utf-8").replace("Evidence only.", "Old rule.") + "\nCustom client rule.\n", encoding="utf-8")
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
            self.assertIn("Evidence only.", boot.read_text(encoding="utf-8"))
            self.assertEqual(schema.read_bytes(), previous_schema)
            self.assertEqual(queue.read_text(), 'pending source\n')
            self.assertIn(previous_boot, [p.read_bytes() for p in (home / "Documents/Brain Install Backups").rglob("*.bak")])

            source = home / "source.txt"
            source.write_text("A verified source fixture.", encoding="utf-8")
            helper = home / ".codex/skills/source-to-vault/scripts/source_packet.py"
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


if __name__ == "__main__":
    unittest.main()
