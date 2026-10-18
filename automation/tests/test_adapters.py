"""The adapter registry: manifests validate, every agent installs where its manifest says, upgrades merge."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(REPO / "automation"))
import vault_adapters as adapters  # noqa: E402
from vault_hygiene import parity  # noqa: E402

spec = importlib.util.spec_from_file_location("brain_install_adapters", REPO / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def quietly(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brain adapters ")
        self.home = Path(self.tmp.name).resolve() / "Some User"
        self.vault = self.home / "Brain"

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_manifest_validates_and_the_schema_refuses_bad_ones(self):
        registry = adapters.load()
        self.assertEqual(list(registry)[:2], ["claude", "codex"])
        self.assertGreaterEqual(set(registry), {"claude", "codex", "copilot", "kiro", "qwen", "factory"})
        schema = json.loads((REPO / "automation/adapters/schema.json").read_text(encoding="utf-8"))
        good = registry["copilot"]
        self.assertEqual(adapters.check(good, schema), [])
        for change, problem in (({"id": "Copilot CLI"}, "id does not match"), ({"surprise": 1}, "not a known field"),
                                ({"skills": []}, "at least 1"), ({"transcript_adapter": "copilot-log"}, "must be one of"),
                                ({"instructions": dict(good["instructions"], strategy="symlink")}, "must be one of"),
                                ({"hooks": "yes"}, "must be object or null")):
            with self.subTest(change=change):
                broken = dict(copy.deepcopy(good), **change)
                self.assertTrue(any(problem in p for p in adapters.check(broken, schema)), adapters.check(broken, schema))
        bad = Path(self.tmp.name) / "registry"
        bad.mkdir()
        (bad / "schema.json").write_bytes((REPO / "automation/adapters/schema.json").read_bytes())
        (bad / "other.json").write_text(json.dumps(good), encoding="utf-8")
        with self.assertRaisesRegex(adapters.AdapterError, "must declare id 'other'"):
            adapters.load(bad)

    def test_fresh_install_for_each_agent_writes_where_its_manifest_says(self):
        for name, adapter in install.ADAPTERS.items():
            with self.subTest(agent=name), tempfile.TemporaryDirectory(prefix="brain one ") as tmp:
                home = Path(tmp).resolve() / "User"
                quietly(install.install, home, home / "Brain", apply=True, client=name)
                target = adapters.instructions_path(adapter, home)
                self.assertEqual(target.read_text(encoding="utf-8"), adapters.render_file(adapter))
                self.assertIn(adapter["instructions"]["tail"], adapters.installed_block(adapter, home))
                dirs = install.skill_dirs([name], home, install.ADAPTERS)
                self.assertEqual(len(dirs), 1)
                for skill in adapters.SKILLS:
                    self.assertEqual((dirs[0] / skill / "SKILL.md").read_bytes(), (REPO / "skills" / skill / "SKILL.md").read_bytes())
                self.assertEqual(install.installed_clients(home), [name])
                self.assertEqual(parity(home), [])
                quietly(install.verify, home, home / "Brain")
                config = json.loads((home / ".agent-brain/config.json").read_text(encoding="utf-8"))
                self.assertEqual(config["clients"], [name])
                self.assertEqual((home / ".claude/settings.json").exists(), name == "claude")

    def test_shared_skill_dirs_get_one_copy_and_parity_scales(self):
        quietly(install.install, self.home, self.vault, apply=True, client="codex,copilot,kiro")
        self.assertTrue((self.home / ".agents/skills/handoff/SKILL.md").is_file())
        self.assertFalse((self.home / ".copilot/skills").exists())
        self.assertTrue((self.home / ".kiro/skills/handoff/SKILL.md").is_file())
        self.assertEqual(install.installed_clients(self.home), ["codex", "copilot", "kiro"])
        self.assertEqual(parity(self.home), [])
        # Leaving one installed agent out of an upgrade is refused when its copy is older.
        steering = adapters.instructions_path(install.ADAPTERS["kiro"], self.home)
        steering.write_text(steering.read_text(encoding="utf-8").replace("Evidence only:", "Evidence:"), encoding="utf-8")
        self.assertEqual(install.stale_clients(self.home, "codex,copilot"), ["kiro"])
        result = subprocess.run([sys.executable, str(REPO / "install.py"), "--home", str(self.home), "--vault", str(self.vault),
                                 "--client", "codex", "--apply", "--replace-workflow"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--client codex,kiro", result.stderr)

    def test_v1_boot_files_upgrade_in_place_without_a_stale_tail(self):
        for name, fixture in (("claude", "v1-CLAUDE.md"), ("codex", "v1-AGENTS.md")):
            adapter = install.ADAPTERS[name]
            target = adapters.instructions_path(adapter, self.home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("My own rule first.\n\n" + (FIXTURES / fixture).read_text(encoding="utf-8") + "\nMy own rule last.\n", encoding="utf-8")
        legacy = self.home / ".codex/skills"
        for skill in adapters.SKILLS:
            (legacy / skill).mkdir(parents=True)
            (legacy / skill / "SKILL.md").write_text("v1 copy\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Existing workflow files differ"):
            install.installation(self.home, self.vault, client="both")
        quietly(install.install, self.home, self.vault, apply=True, replace=True, client="both")
        for name in ("claude", "codex"):
            adapter = install.ADAPTERS[name]
            text = adapters.instructions_path(adapter, self.home).read_text(encoding="utf-8")
            self.assertEqual(text.count(adapters.START), 1)
            self.assertIn("My own rule first.", text)
            self.assertIn("My own rule last.", text)
            self.assertIn(adapter["instructions"]["tail"], text)
            after = text.split(adapters.END, 1)[1]
            for line in adapters.LEGACY_TAILS:
                self.assertNotIn(line, after)
        # The legacy Codex skills dir is refreshed in place so no older copy lingers.
        self.assertEqual((legacy / "handoff/SKILL.md").read_bytes(), (REPO / "skills/handoff/SKILL.md").read_bytes())
        self.assertEqual(parity(self.home), [])
        self.assertEqual(install.installation(self.home, self.vault, client="both"), {})

    def test_client_selection_forms(self):
        self.assertEqual(install.selected("both"), ("claude", "codex"))
        self.assertEqual(install.selected("qwen, factory,qwen"), ("qwen", "factory"))
        with self.assertRaisesRegex(ValueError, "Choose claude, codex"):
            install.selected("claude,nobody")
        probes = {v for a in install.ADAPTERS.values() for v in a["detect"]["env"]}
        clean = {k: v for k, v in adapters.os.environ.items() if k not in probes}
        with patch.object(adapters.shutil, "which", return_value=None), patch.dict(adapters.os.environ, clean, clear=True):
            with self.assertRaisesRegex(ValueError, "No supported agent"):
                install.selected("all", self.home)
            (self.home / ".kiro").mkdir(parents=True)
            self.assertEqual(install.selected("all", self.home), ("kiro",))
        future = copy.deepcopy(install.ADAPTERS["qwen"])
        future["instructions"]["strategy"] = "yaml-read-list"
        with patch.dict(install.ADAPTERS, {"aider": dict(future, id="aider", display="Aider")}):
            with self.assertRaisesRegex(ValueError, "yaml-read-list strategy"):
                install.selected("aider")

    def test_render_prints_one_agent_file_and_writes_nothing(self):
        result = subprocess.run([sys.executable, str(REPO / "install.py"), "--home", str(self.home), "--render", "factory"],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, adapters.render_file(install.ADAPTERS["factory"]))
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
