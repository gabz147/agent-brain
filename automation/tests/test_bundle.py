"""brain.pyz builds reproducibly from tracked files only, runs setup, and the brain launchers reach the controller."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]
IN_CHECKOUT = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True).stdout.strip() == "true"


def clean_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k not in ("VAULT_AUTOMATION_DIR", "VAULT_AUTOMATION")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    return env


@unittest.skipUnless(IN_CHECKOUT, "builds from git-tracked files; the bundle under test is already built")
class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("brain_build", REPO / "tools/build_pyz.py")
        cls.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build)
        cls.tmp = tempfile.TemporaryDirectory(prefix="brain bundle ")
        cls.base = Path(cls.tmp.name).resolve()
        cls.bundle = cls.base / "brain.pyz"
        # An ignored runtime file beside the sources must never ship.
        cls.ignored = REPO / "automation/state-v2/bundle-probe.json"
        cls.created = not cls.ignored.exists()
        cls.ignored.parent.mkdir(exist_ok=True)
        cls.ignored.write_text("{}", encoding="utf-8")
        cls.digest = cls.build.build("v9.9.9-test", cls.bundle)

    @classmethod
    def tearDownClass(cls):
        if cls.created:
            cls.ignored.unlink()
            try:
                cls.ignored.parent.rmdir()
            except OSError:
                pass
        cls.tmp.cleanup()

    def run_bundle(self, *args, home=None, timeout=120):
        return subprocess.run([sys.executable, str(self.bundle), *args], capture_output=True, text=True, encoding="utf-8",
                              env=clean_env(home or self.base / "nobody"), timeout=timeout)

    def test_build_is_reproducible_and_holds_only_tracked_files(self):
        again = self.base / "again.pyz"
        self.assertEqual(self.build.build("v9.9.9-test", again), self.digest)
        self.assertEqual(again.read_bytes(), self.bundle.read_bytes())
        self.assertTrue(self.bundle.read_bytes().startswith(b"#!/usr/bin/env python3\n"))
        names = zipfile.ZipFile(self.bundle).namelist()
        tracked = set(filter(None, subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()))
        self.assertIn("__main__.py", names)
        self.assertIn("automation/adapters/codex.json", names)
        self.assertNotIn("automation/state-v2/bundle-probe.json", names)
        self.assertEqual(set(names) - {"__main__.py"} - tracked, set())
        self.assertFalse([n for n in names if n.endswith(".png") or "__pycache__" in n])
        self.assertEqual(self.run_bundle("version").stdout.strip(), "v9.9.9-test")

    def test_setup_from_the_bundle_then_brain_reaches_the_controller(self):
        home = self.base / "Some User"
        setup = self.run_bundle("setup", "--home", str(home), "--client", "qwen", "--apply", home=home)
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertIn("OK installed hygiene", setup.stdout)
        brief = self.run_bundle("session-brief", home=home)
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn("Brain", brief.stdout)
        launcher = home / ".agent-brain/bin" / ("brain.cmd" if os.name == "nt" else "brain")
        command = ["cmd.exe", "/C", str(launcher), "session-brief"] if os.name == "nt" else [str(launcher), "session-brief"]
        via_launcher = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=clean_env(home), timeout=60)
        self.assertEqual(via_launcher.returncode, 0, via_launcher.stderr)
        self.assertEqual(via_launcher.stdout, brief.stdout)
        if os.name != "nt":
            self.assertTrue(os.access(launcher, os.X_OK))
        missing = self.run_bundle("session-brief", home=self.base / "empty home")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("brain.pyz setup --wizard", missing.stderr)


class LauncherTemplateTests(unittest.TestCase):
    def test_launchers_keep_odd_paths_literal_or_refuse_them(self):
        spec = importlib.util.spec_from_file_location("brain_install_launch", REPO / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        odd = Path("/home/x/Someone's $notes}/.agent-brain/automation")
        posix = installer.launcher_bytes("brain", odd).decode()
        self.assertIn("brain_default='" + str(odd).replace("'", "'\\''") + "'\n", posix)
        if os.name != "nt":  # the single-quoted default survives $, } and ' as literal text
            probe = subprocess.run(["/bin/sh", "-c", posix.split("\n")[3] + '\nprintf %s "$brain_default"'], capture_output=True, text=True)
            self.assertEqual(probe.stdout, str(odd))
        self.assertIn(b"\r\n", installer.launcher_bytes("brain.cmd", Path("C:/Users/you/.agent-brain/automation")))
        with self.assertRaises(ValueError):
            installer.launcher_bytes("brain.cmd", Path("C:/Users/you/100%/.agent-brain/automation"))


if __name__ == "__main__":
    unittest.main()
