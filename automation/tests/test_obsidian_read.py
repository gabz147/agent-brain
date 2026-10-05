"""Offline tests only: all note writes use a temporary fixture, never Brain."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import unittest.mock
import sys

MODULE_ROOT = Path(__file__).resolve().parent
if not (MODULE_ROOT / 'obsidian_read.py').is_file():
    MODULE_ROOT = MODULE_ROOT.parent
sys.path.insert(0, str(MODULE_ROOT))
import obsidian_read as subject


class FakeCLI:
    def __init__(self, vault):
        self.calls = []
        self.responses = {
            "vault": str(vault) + "\n",
            "version": "1.14.4 (installer 1.14.4)\n",
            "history": "No history found for this file.\n",
            "backlinks": "No backlinks found.\n",
            "unresolved": "No unresolved links found.\n",
            "orphans": "Folder/My note.md\n",
            "properties": "[]\n",
        }

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        value = self.responses[argv[2]]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value()
        if isinstance(value, subprocess.CompletedProcess):
            return value
        return subprocess.CompletedProcess(argv, 0, value.encode("utf-8"), b"")


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.vault = Path(self.temporary.name) / "vault"
        self.vault.mkdir()
        self.note = self.vault / "Folder" / "My note.md"
        self.note.parent.mkdir()
        self.note.write_bytes(b"hello\n")
        self.fake = FakeCLI(self.vault.resolve())
        # Pinned selector/executable: the tests never read this machine's Obsidian config or install.
        self.reader = subject.Reader(self.vault, vault_id="test-vault", executable="obsidian-test",
                                     runner=self.fake, config_dirs=[])

    def test_verifies_vault_first_and_uses_list_without_shell(self):
        result = self.reader.execute("backlinks", "Folder/My note.md")
        self.assertEqual([], result["backlinks"])
        self.assertEqual("vault", self.fake.calls[0][0][2])
        self.assertEqual("path=Folder/My note.md", self.fake.calls[1][0][3])
        for argv, kwargs in self.fake.calls:
            self.assertIsInstance(argv, list)
            self.assertEqual("vault=test-vault", argv[1])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(20, kwargs["timeout"])

    def test_wrong_vault_stops_before_requested_read(self):
        self.fake.responses["vault"] = str(self.vault.parent) + "\n"
        with self.assertRaisesRegex(subject.ObservationError, "identity mismatch"):
            self.reader.execute("backlinks", "Folder/My note.md")
        self.assertEqual(1, len(self.fake.calls))

    def test_disabled_cli_exit_zero_is_failure(self):
        self.fake.responses["vault"] = ("Command line interface is not enabled. "
                                           "Please turn it on in Settings > General > Advanced.\n")
        with self.assertRaisesRegex(subject.ObservationError, "not enabled"):
            self.reader.execute("diagnostics")

    def test_native_error_exit_zero_is_failure(self):
        self.fake.responses["backlinks"] = "Error: File not found.\n"
        with self.assertRaisesRegex(subject.ObservationError, "File not found"):
            self.reader.execute("backlinks", "Folder/My note.md")

    def test_stderr_and_nonzero_are_failures(self):
        for response in (
            subprocess.CompletedProcess([], 0, b"[]\n", b"native warning"),
            subprocess.CompletedProcess([], 2, b"failed", b""),
        ):
            with self.subTest(response=response):
                self.fake.responses["backlinks"] = response
                with self.assertRaises(subject.ObservationError):
                    self.reader.execute("backlinks", "Folder/My note.md")

    def test_timeout_and_executable_failure(self):
        for error in (subprocess.TimeoutExpired("Obsidian.com", 20), FileNotFoundError("missing")):
            with self.subTest(error=error):
                self.fake.responses["vault"] = error
                with self.assertRaises(subject.ObservationError):
                    self.reader.execute("diagnostics")

    def test_mutations_and_unsafe_options_rejected_before_spawn(self):
        for command, options in (("eval", ("code=1",)),
                                 ("history:restore", ("path=Folder/My note.md",)),
                                 ("properties", ("active",)), ("backlinks", ())):
            with self.subTest(command=command, options=options):
                with self.assertRaises(subject.ObservationError):
                    self.reader._run(command, *options)
        self.assertEqual([], self.fake.calls)

    def test_unsafe_or_missing_paths_rejected(self):
        paths = ("", "../outside.md", "/outside.md", r"C:\outside.md", r"\\server\x.md",
                 "Folder/../Folder/My note.md", ".obsidian/secret.md", "Folder//My note.md",
                 "Folder/My note.md\non", "Folder/My\tnote.md", 'Folder/My"note.md',
                 "Folder/My note.md:stream", "Folder/not found.md", "Folder/note.json")
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(subject.ObservationError):
                    self.reader.note(path)

    def test_symlink_outside_vault_rejected(self):
        outside = self.vault.parent / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        link = self.vault / "linked.md"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Host does not permit test symlinks: {exc}")
        with self.assertRaisesRegex(subject.ObservationError, "outside"):
            self.reader.note("linked.md")

    def test_unexpected_json_and_invalid_utf8_are_failures(self):
        for output in (b"unexpected\n", b'"Error: bad"\n', b"\xff"):
            with self.subTest(output=output):
                self.fake.responses["backlinks"] = subprocess.CompletedProcess([], 0, output, b"")
                with self.assertRaises(subject.ObservationError):
                    self.reader.execute("backlinks", "Folder/My note.md")

    def test_link_inventory_uses_only_allowed_read_commands(self):
        result = self.reader.execute("link-audit")
        self.assertEqual([], result["unresolved"])
        self.assertEqual(["Folder/My note.md"], result["orphans"])
        self.assertEqual(["vault", "unresolved", "orphans"], [x[0][2] for x in self.fake.calls])

    def test_note_properties_are_object_and_global_properties_array(self):
        self.assertEqual([], self.reader.execute("properties")["properties"])
        self.fake.responses["properties"] = '{"type":"resource"}\n'
        self.assertEqual({"type": "resource"},
                         self.reader.execute("properties", "Folder/My note.md")["properties"])
        self.fake.responses["properties"] = "No frontmatter found.\n"
        self.assertEqual({}, self.reader.execute("properties", "Folder/My note.md")["properties"])

    def test_symlink_into_configuration_rejected(self):
        config = self.vault / ".obsidian"
        config.mkdir()
        target = config / "config.md"
        target.write_text("configuration", encoding="utf-8")
        link = self.vault / "linked.md"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Host does not permit test symlinks: {exc}")
        with self.assertRaisesRegex(subject.ObservationError, "configuration"):
            self.reader.note("linked.md")

    def test_preflight_ready_and_empty_local_history(self):
        result = self.reader.execute("preflight", "Folder/My note.md")
        self.assertTrue(result["ok"])
        self.assertTrue(result["checks_complete"])
        self.assertTrue(result["local"]["stable"])
        self.assertIn("No history", result["local_history"]["output"])
        self.assertNotIn("hello", json.dumps(result))

    def test_history_no_snapshots_is_successful_and_errors_are_explicit(self):
        result = self.reader.execute("history", "Folder/My note.md")
        self.assertTrue(result["ok"])
        self.assertIn("No history", result["local_history"]["output"])
        self.fake.responses["history"] = "Error: File recovery is not enabled.\n"
        result = self.reader.execute("history", "Folder/My note.md")
        self.assertFalse(result["ok"])
        self.assertIn("not enabled", result["local_history"]["error"])

    def test_preflight_detects_file_changed_during_observations(self):
        def changed():
            self.note.write_bytes(b"local edit arrived\n")
            return "No history found for this file.\n"
        self.fake.responses["history"] = changed
        result = self.reader.execute("preflight", "Folder/My note.md")
        self.assertFalse(result["ok"])
        self.assertFalse(result["local"]["stable"])

    def test_preflight_retains_history_error_and_timeout(self):
        for response in (subprocess.TimeoutExpired("Obsidian.com", 20),
                         "Error: File recovery is not enabled.\n"):
            with self.subTest(response=response):
                self.fake.responses["history"] = response
                result = self.reader.execute("preflight", "Folder/My note.md")
                self.assertFalse(result["ok"])
                self.assertFalse(result["checks_complete"])
                self.assertFalse(result["local_history"]["available"])
                self.assertTrue(result["local"]["stable"])

    def test_sync_and_all_native_sync_commands_rejected_before_spawn(self):
        commands = ("sync", "sync:status", "sync:history", "sync:read", "sync:deleted",
                    "sync:open", "sync:restore", "sync:future", "after-write")
        for command in commands:
            with self.subTest(command=command):
                with self.assertRaises(subject.ObservationError):
                    self.reader._run(command)
                with self.assertRaises(subject.ObservationError):
                    self.reader.execute(command, "Folder/My note.md")
        self.assertEqual([], self.fake.calls)

    def test_every_public_command_uses_only_local_calls_and_outputs(self):
        commands = ("diagnostics", "link-audit", "backlinks", "properties", "history", "preflight")
        local_commands = {"vault", "version", "unresolved", "orphans", "backlinks", "properties", "history"}
        for command in commands:
            with self.subTest(command=command):
                self.fake.calls.clear()
                note = "Folder/My note.md" if command in {"backlinks", "history", "preflight"} else None
                result = self.reader.execute(command, note)
                self.assertTrue(result["ok"])
                self.assertTrue(all(call[0][2] in local_commands for call in self.fake.calls))
                self.assertNotIn("sync", json.dumps(result).lower())
                self.assertNotIn("remote", json.dumps(result).lower())
                self.assertNotIn("phone", json.dumps(result).lower())

    def test_cli_exposes_no_arbitrary_native_commands(self):
        for argv in (["eval", "code=1"], ["sync"], ["sync:status"], ["sync:history"],
                     ["sync:read"], ["sync:deleted"], ["sync:open"], ["sync:restore"],
                     ["sync:future"], ["after-write", "Folder/My note.md"], ["backlinks"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    subject.main(argv)
                self.assertEqual(2, error.exception.code)


    # ---------- review hardening (2026-10-05) ----------
    def test_vault_not_found_exit_zero_is_failure(self):
        self.fake.responses["orphans"] = "Vault not found.\n"
        with self.assertRaisesRegex(subject.ObservationError, "Vault not found"):
            self.reader._run("orphans")

    def test_bare_or_repeated_path_options_rejected_before_spawn(self):
        for command, options in (("backlinks", ("path",)), ("history", ("path",)), ("properties", ("path",)),
                                 ("history", ("path=Folder/My note.md", "path=Folder/My note.md")),
                                 ("orphans", ("path=Folder/My note.md",))):
            with self.subTest(command=command, options=options):
                with self.assertRaises(subject.ObservationError):
                    self.reader._run(command, *options)
        self.assertEqual([], self.fake.calls)

    def test_wrong_case_path_uses_on_disk_case(self):
        probe = self.vault / "FOLDER" / "MY NOTE.MD"
        if not probe.exists():
            self.skipTest("Case-sensitive file system: a wrong-case path cannot resolve here.")
        relative, target = self.reader.note("folder/my NOTE.md")
        self.assertEqual("Folder/My note.md", relative)
        self.reader.execute("history", "folder/my NOTE.md")
        self.assertIn("path=Folder/My note.md", self.fake.calls[-1][0])

    def test_invalid_note_rejected_before_any_native_call(self):
        with self.assertRaises(subject.ObservationError):
            self.reader.execute("history", "../outside.md")
        self.assertEqual([], self.fake.calls)

    def test_vault_id_discovered_from_obsidian_config(self):
        config = Path(self.temporary.name) / "config"
        config.mkdir()
        (config / "obsidian.json").write_text(json.dumps({"vaults": {
            "other1234": {"path": str(Path(self.temporary.name) / "elsewhere")},
            "abcd1234": {"path": str(self.vault), "open": True}}}), encoding="utf-8")
        self.assertEqual("abcd1234", subject.discover_vault_id(self.vault, [config]))
        reader = subject.Reader(self.vault, executable="obsidian-test", runner=self.fake, config_dirs=[config])
        self.assertEqual("abcd1234", reader.selector)

    def test_selector_falls_back_to_env_then_folder_name(self):
        broken = Path(self.temporary.name) / "broken"
        broken.mkdir()
        (broken / "obsidian.json").write_text("{not json", encoding="utf-8")
        with unittest.mock.patch.dict(subject.os.environ, {"BRAIN_OBSIDIAN_VAULT": "Named"}):
            self.assertEqual("Named", subject.Reader(self.vault, executable="x", config_dirs=[broken]).selector)
        with unittest.mock.patch.dict(subject.os.environ, {}, clear=False) as env:
            env.pop("BRAIN_OBSIDIAN_VAULT", None)
            self.assertEqual("vault", subject.Reader(self.vault, executable="x", config_dirs=[broken]).selector)

    def test_missing_cli_is_explicit_and_spawns_nothing(self):
        with unittest.mock.patch.object(subject, "discover_cli", return_value=None):
            reader = subject.Reader(self.vault, vault_id="v", runner=self.fake, config_dirs=[])
        with self.assertRaisesRegex(subject.ObservationError, "Obsidian CLI not found"):
            reader._run("version")
        self.assertEqual([], self.fake.calls)

    def test_environment_configures_vault_cli_and_timeout(self):
        with unittest.mock.patch.dict(subject.os.environ, {"BRAIN_VAULT_ROOT": str(self.vault),
                                                           "BRAIN_OBSIDIAN_CLI": "custom-obsidian",
                                                           "BRAIN_OBSIDIAN_TIMEOUT": "45"}):
            reader = subject.Reader(vault_id="v", config_dirs=[])
        self.assertEqual(self.vault.resolve(), reader.vault)
        self.assertEqual(Path("custom-obsidian"), reader.executable)
        self.assertEqual(45.0, reader.timeout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
