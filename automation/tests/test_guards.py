"""Release guards: keep the template lean, consistent with its Contract and free of private paths."""
import re
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "vault/10 - Resources/Vault Workflow Contract.md"
# Sizes after the October 2026 context audit, plus 5%. Raise a cap only with a measured reason.
CAPS = {
    # 2026-11-10: the find recipe and one worked checkpoint example replace the ripgrep block and the path paragraph,
    # so the common checkpoint needs no Contract read; measured 4,547 bytes, cap is that plus 5%.
    "skills/obsidian-vault/SKILL.md": 4775,
    "skills/handoff/SKILL.md": 1793,
    "skills/source-to-vault/SKILL.md": 4260,
    # 2026-10-18: v2 trimmed the Contract from 20,178 to about 13,400 bytes, agent-neutral.
    # 2026-11-10: plus the report byline, resume, write guard and snapshot rules, minus the Obsidian CLI section.
    "vault/10 - Resources/Vault Workflow Contract.md": 15100}
STOP_TEMPLATE_CAP = 1300
BANNED = ("keep queueing", "drain when you resume", "durable spool", "scheduled capture")
PLACEHOLDER_PATHS = {"/home/x", "/Users/you", "C:/Users/you", "C:/Users/me"}  # compared with separators normalized to '/'
# Contract section references: quoted in the Stop text, "Contract's X section" or "its X section" in boots and skills.
SECTION_REFERENCES = (re.compile(r'"([A-Z][^"{}]*)"(?= (?:sections?\b|and "))'),
                      re.compile(r"(?:[Cc]ontract's|its) ([A-Z][A-Za-z -]+?) section"))


def stop_template():
    """The one Stop request every agent receives, rendered with placeholder paths so its fixed text can be measured."""
    sys.path.insert(0, str(REPO / "automation"))
    import types
    import vault_gate
    vault = types.SimpleNamespace(root=Path("V"))
    with unittest.mock.patch.object(vault_gate, "HERE", Path("A")), unittest.mock.patch.object(vault_gate, "python_command", return_value="python"):
        return vault_gate.instruction(vault, "claude", "{session_id}", {"transcript_path": "T"}, use_transcript=True)


def vault_gate_request_without_transcript():
    sys.path.insert(0, str(REPO / "automation"))
    import types
    import vault_gate
    return vault_gate.instruction(types.SimpleNamespace(root=Path("V")), "kiro", "s", {"model": "m"})


class ReleaseGuards(unittest.TestCase):
    def test_size_caps(self):
        for rel, cap in CAPS.items():
            self.assertLessEqual(len((REPO / rel).read_bytes()), cap, rel)
        self.assertLessEqual(len(stop_template()), STOP_TEMPLATE_CAP)

    def test_stop_text_prefix_and_named_contract_sections_exist(self):
        template = stop_template()
        self.assertTrue(template.startswith("Vault checkpoint requested for session {session_id}."))
        self.assertIn("--transcript", template)
        self.assertNotIn("--transcript", vault_gate_request_without_transcript())
        headings = set(re.findall(r"^## (.+)$", CONTRACT.read_text(encoding="utf-8"), re.M))
        sources = [REPO / "boot/BRAIN.md", REPO / "SKILL.md", *sorted((REPO / "skills").glob("*/SKILL.md"))]
        texts = [template] + [path.read_text(encoding="utf-8") for path in sources]
        named = {name for text in texts for pattern in SECTION_REFERENCES for name in pattern.findall(text)}
        self.assertGreaterEqual(named, {"Daily checkpoints and coverage", "Shared writer", "Related notes and ledgers", "Read and reconcile"})
        self.assertFalse(named - headings, "Contract sections named by the Stop text, boots or skills are missing")

    def test_shipped_docs_have_no_retired_capture_promises(self):
        docs = [REPO / p for p in ("README.md", "docs/setup.md", *(str(p.relative_to(REPO)) for p in sorted((REPO / "contrib").glob("*/README.md"))))]
        docs += list((REPO / "docs").glob("*.md")) + list((REPO / "vault").rglob("*.md"))
        for path in docs:
            text = path.read_text(encoding="utf-8").lower()
            for phrase in BANNED:
                self.assertNotIn(phrase, text, f"{path.relative_to(REPO)}: {phrase}")

    def test_generated_agent_pages_are_current(self):
        result = subprocess.run([sys.executable, str(REPO / "tools/gen_agent_docs.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "Run python tools/gen_agent_docs.py: " + result.stdout)

    def test_one_copy_of_vault_actions_and_one_hook_adapter(self):
        self.assertFalse((REPO / "skills/obsidian-vault/references").exists(), "Vault Actions lives once, in the vault")
        self.assertEqual(sorted(p.name for p in (REPO / "hooks/vault").glob("*.py")), ["agent-hook.py", "brain_paths.py"])
        self.assertFalse((REPO / "automation/obsidian_read.py").exists(), "the Obsidian CLI helper is optional, in contrib/")

    def test_shipped_schema_matches_the_packaged_defaults(self):
        import json
        sys.path.insert(0, str(REPO / "automation"))
        import vault_core
        shipped = json.loads((REPO / "automation/vault-schema.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped, vault_core.DEFAULT_SCHEMA)
        self.assertEqual(vault_core.load_schema(REPO / "automation/no-such-schema.json"), vault_core.DEFAULT_SCHEMA)

    def test_no_private_paths_or_license_placeholder(self):
        self.assertNotIn("<YOUR NAME>", (REPO / "LICENSE").read_text(encoding="utf-8"))
        listed = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True)
        if listed.returncode or not listed.stdout:
            self.skipTest("needs a git checkout; an extracted brain.pyz bundle was already built from tracked files")
        files = listed.stdout.split("\n")
        # Path segments exclude regex brackets, so this pattern does not match its own source.
        pattern = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s`\"'<>\[\]]+|/home/[^/\s`\"'<>\[\]]+|/Users/[^/\s`\"'<>\[\]]+)")
        for rel in filter(None, files):
            path = REPO / rel
            if path.suffix.lower() == ".png" or not path.is_file():
                continue
            found = {re.sub(r"[\\/]+", "/", hit) for hit in pattern.findall(path.read_text(encoding="utf-8", errors="ignore"))} - PLACEHOLDER_PATHS
            self.assertFalse(found, f"{rel}: {sorted(found)}")


if __name__ == "__main__":
    unittest.main()
