"""Release guards: keep the template lean, consistent with its Contract and free of private paths."""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "vault/10 - Resources/Vault Workflow Contract.md"
# Sizes after the October 2026 context audit, plus 5%. Raise a cap only with a measured reason.
CAPS = {"skills/obsidian-vault/SKILL.md": 4205, "skills/handoff/SKILL.md": 1793,
        "skills/source-to-vault/SKILL.md": 4260, "vault/10 - Resources/Vault Workflow Contract.md": 20428}
STOP_TEMPLATE_CAP = 1246
BANNED = ("keep queueing", "drain when you resume", "durable spool", "scheduled capture")
PLACEHOLDER_PATHS = {"/home/x", "C:/Users/you", "C:/Users/me"}  # compared with separators normalized to '/'


def stop_template():
    source = (REPO / "automation/vault_hooks.py").read_text(encoding="utf-8")
    start = source.index('instruction = f"""') + len('instruction = f"""')
    return source[start:source.index('"""', start)]


class ReleaseGuards(unittest.TestCase):
    def test_size_caps(self):
        for rel, cap in CAPS.items():
            self.assertLessEqual(len((REPO / rel).read_bytes()), cap, rel)
        self.assertLessEqual(len(stop_template()), STOP_TEMPLATE_CAP)

    def test_stop_text_prefix_and_named_contract_sections_exist(self):
        template = stop_template()
        self.assertTrue(template.startswith("Vault checkpoint requested for session {session_id}."))
        headings = set(re.findall(r"^## (.+)$", CONTRACT.read_text(encoding="utf-8"), re.M))
        named = set(re.findall(r'"(Daily checkpoints and coverage|Shared writer|Related notes and ledgers)"', template))
        for rel in ("boot/CLAUDE.md", "boot/AGENTS.md", "skills/obsidian-vault/SKILL.md", "skills/handoff/SKILL.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            named |= {name for name in ("Daily checkpoints and coverage", "Shared writer", "Related notes and ledgers",
                                        "Handoffs and manual use", "Read-only Obsidian CLI", "Context loading") if name in text}
        self.assertTrue(named)
        self.assertFalse(named - headings, "Contract sections named by the Stop text, boots or skills are missing")

    def test_shipped_docs_have_no_retired_capture_promises(self):
        docs = [REPO / p for p in ("README.md", "INSTALL.md", "LAPTOP-SETUP.md", "plugins/agent-pulse/README.md")]
        docs += list((REPO / "docs").glob("*.md")) + list((REPO / "vault").rglob("*.md"))
        for path in docs:
            text = path.read_text(encoding="utf-8").lower()
            for phrase in BANNED:
                self.assertNotIn(phrase, text, f"{path.relative_to(REPO)}: {phrase}")

    def test_vault_actions_fallback_matches_the_note(self):
        note = (REPO / "vault/10 - Resources/Vault Actions.md").read_text(encoding="utf-8")
        body = re.sub(r"^---\n.*?\n---\n\n?", "", note, flags=re.S)
        self.assertEqual((REPO / "skills/obsidian-vault/references/vault-actions.md").read_text(encoding="utf-8"), body)

    def test_no_private_paths_or_license_placeholder(self):
        self.assertNotIn("<YOUR NAME>", (REPO / "LICENSE").read_text(encoding="utf-8"))
        files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
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
