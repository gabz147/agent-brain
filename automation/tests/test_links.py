"""The pure-Python link audit and the Contract section helper are read-only and agree with the starter vault."""
from pathlib import Path

from test_vault import Fixture
import vault_core as core
from vault_links import audit
from vaultctl import main

REPO = Path(__file__).resolve().parents[2]
META = "---\nstatus: active\nproject: meta\ntype: reference\nupdated_by: human\nupdated: 2026-09-05\n---\n"


class LinkTests(Fixture):
    def write(self, rel, body):
        path = self.vault.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(META + body, encoding="utf-8")
        return path

    def test_resolution_fragments_ambiguity_and_orphans(self):
        self.write("02 - Work/02 - Work.md", "# Work\n- [[Topic]]\n- [[Topic#Real heading]] [[Topic#Gone]] [[Topic#^b1]] [[Topic#^nope]]\n")
        self.write("02 - Work/Topic.md", "# Topic\n## Real **heading**\nText ^b1\n```\n[[Inside fence]]\n```\n`[[inline code]]` [[#Topic]]\n")
        self.write("02 - Work/Lonely.md", "# Lonely\n[[Missing note|alias]] ![[image.png]] [[sub/Twin]] [[Twin]]\n")
        self.write("03 - Other/sub/Twin.md", "# Twin\n")
        self.write("03 - Other/Twin.md", "# Twin\n")
        (self.vault.root / "02 - Work/image.png").write_bytes(b"png")
        self.write("09 - Archive/Old.md", "[[Never checked]]\n")
        before = {p: p.read_bytes() for p in self.vault.root.rglob("*") if p.is_file()}
        report = audit(self.vault, full=True)
        self.assertEqual(report["outcome"], "needs_review")
        self.assertEqual([m["link"] for m in report["missing"]], ["[[Missing note]]"])
        self.assertEqual(sorted(f["link"] for f in report["fragments"]), ["[[Topic#Gone]]", "[[Topic#^nope]]"])
        self.assertEqual(len(report["ambiguous"]), 1)
        self.assertEqual(report["ambiguous"][0]["resolves_to"], "03 - Other/Twin.md")
        self.assertEqual(report["orphans"], ["02 - Work/Lonely.md"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.vault.root.rglob("*") if p.is_file()})

    def test_starter_vault_is_clean(self):
        starter = core.Vault(REPO / "vault", self.base / "s", self.base / "b")
        report = audit(starter)
        self.assertEqual(report["counts"]["missing"], 0, report["missing"])
        self.assertEqual(report["counts"]["fragments"], 0, report["fragments"])

    def test_help_write_lists_and_prints_contract_sections(self):
        base = ["--vault", str(REPO / "vault"), "--state", str(self.base / "s"), "--backups", str(self.base / "b"), "help", "write"]
        listing = main(base)
        for name in ("Read and reconcile", "Shared writer", "Daily checkpoints and coverage", "Related notes and ledgers"):
            self.assertIn("- " + name + " (lines ", listing)
        section = main(base + ["daily checkpoints and coverage"])
        self.assertTrue(section.startswith("## Daily checkpoints and coverage\n"))
        self.assertNotIn("## Related notes", section)
        with self.assertRaisesRegex(core.VaultError, "No Contract section"):
            main(base + ["Nope"])
