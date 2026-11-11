"""Recall eval, consolidation digest and fact freshness stay read-only and index-free."""
import datetime as dt
import json
import subprocess
import sys
from unittest.mock import patch

from test_vault import Fixture, HEADER, SECTIONS
import vault_core as core
import vault_recall as recall

EVAL = HEADER.replace("type: log", "type: guide") + """
# Recall Eval

| Question | Expected note | Search terms |
|---|---|---|
| Where is the printer model? | [[Machine Inventory]] | printer, model |
| What did we decide about storage? | [[Decisions]] | storage decision |
| Which note covers the ghost? | [[Ghost Note]] | ghost |

```md
| Fenced example | [[Nowhere]] | ignored |
```
"""


class RecallTests(Fixture):
    def write(self, rel, body, header=HEADER):
        info = self.vault.inspect(rel)
        self.vault.commit([{"path": rel, "expected_sha256": info["sha256"], "content": header + body}], "astra", "fixture")

    def corpus(self):
        self.write("Machine Inventory.md", "\n# Machine Inventory\n\n- Printer model: LX-9 (as of 2026-01-02)\n"
                   "- GPU: RX 9 (as of September 1, 2026)\n- Disk: (as of someday soon)\n"
                   "- Convention: `(as of YYYY-MM-DD)` is documentation, not a fact\n")
        self.write("Decisions.md", "\n# Decisions\n\n| Date | Decision |\n|---|---|\n| 2026-09-01 | Storage decision: Markdown only |\n")
        self.write(recall.EVAL_NOTE, EVAL[len(HEADER.replace("type: log", "type: guide")):],
                   HEADER.replace("type: log", "type: guide"))

    def snapshot(self):
        return {p.relative_to(self.vault.root).as_posix(): p.read_bytes() for p in self.vault.root.rglob("*.md")}

    def test_eval_parses_only_real_rows(self):
        cases = recall.load_eval(EVAL)
        self.assertEqual([c["expected"] for c in cases], ["Machine Inventory", "Decisions", "Ghost Note"])
        self.assertEqual(cases[0]["terms"], ["printer", "model"])

    def test_eval_ranks_hits_reports_misses_and_stays_read_only(self):
        self.corpus()
        before = self.snapshot()
        report = recall.recall_eval(self.vault, top_k=5)
        self.assertEqual(before, self.snapshot())
        self.assertEqual((report["questions"], report["found"]), (3, 2))
        self.assertEqual(report["outcome"], "needs_review")
        miss = report["misses"][0]
        self.assertEqual(miss["expected"], "Ghost Note")
        self.assertTrue(miss["missing_note"])
        self.assertIsNone(miss["rank"])

    def test_record_creates_then_appends_valid_audit_note(self):
        self.corpus()
        recall.recall_eval(self.vault, record=True)
        report = recall.recall_eval(self.vault, record=True)
        text = self.vault.path(recall.MISS_LOG).read_text(encoding="utf-8")
        self.assertEqual(core.validate(text, self.vault.path(recall.MISS_LOG)), [])
        self.assertEqual(core.frontmatter(text)[0]["updated_by"], "automation")
        self.assertEqual(text.count("2/3 found in top 5"), 2)
        self.assertIn("[[Ghost Note]]", text)
        self.assertTrue(report["recorded"]["transaction_id"])

    def test_missing_eval_note_is_an_error(self):
        with self.assertRaises(core.VaultError):
            recall.recall_eval(self.vault)

    def test_consolidation_digest_groups_sessions_and_marks(self):
        self.write("Topic.md", "\n# Topic\n")
        sections = dict(SECTIONS, **{"What Got Done": ["Tried the shell route; it failed, do instead use the API."],
                                     "What's Still In Progress": ["Wire the retry path."],
                                     "Decisions Made": ["Keep Markdown canonical."],
                                     "Notes Touched": ["[[Topic]]", "[[Missing Topic]]"]})
        op = core.daily_operation(self.vault, "2026-09-05", "4:42 PM", "Consolidate me", sections, "astra", "<!-- c -->")
        self.vault.commit([op], "astra", "fixture")
        before = self.snapshot()
        with patch.object(recall, "_today", return_value=dt.date(2026, 9, 6)):
            digest = recall.consolidate_context(self.vault, days=7)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(digest["days_with_notes"], ["2026-09-05"])
            self.assertEqual(digest["touched_notes"][0]["note"], "Topic")
            self.assertEqual(digest["unresolved_links"], ["Missing Topic"])
            self.assertEqual(digest["open_items"][0]["item"], "Wire the retry path.")
            self.assertEqual(digest["decisions"][0]["item"], "Keep Markdown canonical.")
            self.assertEqual(len(digest["dead_end_candidates"]), 1)
            recall.mark_consolidated(self.vault, "2026-09-05")
            later = recall.consolidate_context(self.vault)
            self.assertEqual(later["from"], "2026-09-06")
            self.assertEqual(later["sessions"], 0)
            with self.assertRaises(core.VaultError):
                recall.mark_consolidated(self.vault, "2026-09-30")

    def test_fact_freshness_flags_stale_unparsed_and_unmarked(self):
        self.corpus()
        with patch.object(recall, "_today", return_value=dt.date(2026, 9, 28)):
            report = recall.fact_freshness(self.vault, max_age_days=90)
        self.assertEqual([s["as_of"] for s in report["stale"]], ["2026-01-02"])
        self.assertEqual(report["fresh_markers"], 1)
        self.assertEqual(len(report["unparsed"]), 1)
        self.assertEqual(report["volatile_without_markers"], [])
        self.write("Machine Inventory.md", "\n# Machine Inventory\n\n- Nothing dated\n")
        report = recall.fact_freshness(self.vault)
        self.assertEqual(report["volatile_without_markers"][0]["path"], "Machine Inventory.md")

    def drift_vault(self, marker):
        def note(rel, text):
            path = self.vault.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        note("VAULT-INDEX.md", HEADER + f"\n## Who I Am\n\nWorks on [[Xray]].\n\n## Living Profile\n\nProfile reviewed through: {marker}\n")
        note("Active Priorities.md", HEADER + "\n## Active Now\n\n- Work on [[Xray]]\n\n## Next\n\n- Later [[Yankee]]\n")
        note("Xray.md", HEADER)
        note("Yankee.md", HEADER)
        note("01 - Daily Notes/10 - October 2026/2026-10-20.md", HEADER + "\n# Tuesday, October 20, 2026\n\n## Index\n\n"
             "## Session 1 — 3:42 PM: Topic — `astra`\n\n### Profile Updates\n- I prefer tea.\n\n")

    def test_session_brief_profile_line_with_drift_and_without(self):
        self.drift_vault("2026-10-20T12:00")
        brief = recall.session_brief(self.vault)
        profile = [l for l in brief.splitlines() if l.startswith("Profile:")]
        self.assertEqual(profile, ["Profile: 1 pending profile update(s) since 2026-10-20; 1 active project(s) not in Who I Am (Yankee). "
                                   "Editing VAULT-INDEX needs owner approval."])
        self.assertLessEqual(len(profile[0]), recall.BRIEF_LINE)
        self.drift_vault("2026-10-20T23:00")
        (self.vault.root / "Active Priorities.md").write_text(HEADER + "\n## Active Now\n\n- Work on [[Xray]]\n", encoding="utf-8")
        self.assertNotIn("Profile:", recall.session_brief(self.vault))

    def test_session_brief_profile_line_omits_zero_clause_and_caps_names(self):
        self.drift_vault("2026-10-20T23:00")
        names = ["Yankee", "Zulu", "Quebec", "Romeo", "Sierra"]
        for name in names:
            (self.vault.root / f"{name}.md").write_text(HEADER, encoding="utf-8")
        (self.vault.root / "Active Priorities.md").write_text(
            HEADER + "\n## Active Now\n\n- Work on [[Xray]]\n\n## Next\n\n" + "".join(f"- [[{n}]]\n" for n in names), encoding="utf-8")
        profile = [l for l in recall.session_brief(self.vault).splitlines() if l.startswith("Profile:")][0]
        self.assertTrue(profile.startswith("Profile: 5 active project(s) not in Who I Am (Yankee, Zulu, Quebec, Romeo, ...)"), profile)
        self.assertNotIn("pending", profile)
        self.assertIn("Editing VAULT-INDEX needs owner approval.", profile)

    def test_session_brief_survives_profile_drift_failure(self):
        self.drift_vault("2026-10-20T23:00")
        (self.vault.root / "Active Priorities.md").write_text(HEADER + "\n## Active Now\n\n- Work on [[Xray]]\n", encoding="utf-8")
        baseline = recall.session_brief(self.vault)
        self.drift_vault("2026-10-20T12:00")
        with patch("vault_hygiene.profile_drift", side_effect=core.VaultError("boom")):
            self.assertEqual(recall.session_brief(self.vault), baseline)

    def test_find_returns_the_ranking_the_eval_measures(self):
        self.corpus()
        info = self.vault.inspect(recall.EVAL_NOTE)
        for case in recall.load_eval(info["text"]):
            found = recall.find_notes(self.vault, case["terms"], top=50)
            corpus = [(path.stem, rel, core.read_text(path)) for path, rel in recall._live_notes(self.vault) if rel != recall.EVAL_NOTE]
            expected = [rel for _, rel, _ in recall.rank_notes(corpus, case["terms"])]
            self.assertEqual([row["path"] for row in found["results"] if row["path"] != recall.EVAL_NOTE], expected[:len(found["results"])])
        first = recall.find_notes(self.vault, [recall.load_eval(info["text"])[0]["terms"][0]], top=1)
        self.assertEqual((first["outcome"], len(first["results"])), ("found", 1))
        self.assertTrue(all(set(hit) == {"line", "text"} for hit in first["results"][0]["hits"]))
        self.assertEqual(recall.find_notes(self.vault, ["no-such-term-anywhere"])["outcome"], "none")
        with self.assertRaises(core.VaultError):
            recall.find_notes(self.vault, ["  "])

    def test_find_scope_excludes_daily_and_archive_unless_asked(self):
        def note(rel, body):
            path = self.vault.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(HEADER + body, encoding="utf-8")
        note("02 - Project/Zebra plan.md", "\n# Zebra plan\n")
        note("09 - Archive/Zebra old.md", "\n# Zebra old\n")
        note("01 - Daily Notes/09 - September 2026/2026-09-05.md", "\n# Saturday, September 5, 2026\n\nzebra session\n")
        paths = lambda **kw: [row["path"] for row in recall.find_notes(self.vault, ["zebra"], **kw)["results"]]
        self.assertEqual(paths(), ["02 - Project/Zebra plan.md"])
        self.assertEqual(paths(daily=True), ["01 - Daily Notes/09 - September 2026/2026-09-05.md"])
        self.assertEqual(sorted(paths(archive=True)), ["02 - Project/Zebra plan.md", "09 - Archive/Zebra old.md"])

    def test_cli_exit_codes(self):
        self.corpus()
        args = [sys.executable, str(core.HERE / "vaultctl.py"), "--vault", str(self.vault.root),
                "--state", str(self.vault.state), "--backups", str(self.vault.backups)]
        child = subprocess.run(args + ["recall-eval"], capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(child.returncode, 2, child.stderr)
        self.assertEqual(json.loads(child.stdout)["found"], 2)
        child = subprocess.run(args + ["consolidate-context", "--days", "3"], capture_output=True, text=True,
                               encoding="utf-8", timeout=20)
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
