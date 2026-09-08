import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from test_vault import Fixture, HEADER
import vault_core as core
import vault_capture as capture
import vault_queue as queue
import vault_sources as sources
from vault_hygiene import daily_structure, schema_block
from vaultctl import checkpoint


class ReleaseTests(Fixture):
    def test_live_checkpoint_retry_ignores_verification_tail(self):
        path = self.transcript()
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        payload = self.proposal(units)
        args = SimpleNamespace(source='codex', session='session-1', transcript=str(path))
        first = checkpoint(self.vault, args, payload)
        daily = self.vault.path(core.daily_path(units[0]['day']))
        before = daily.read_bytes()
        with path.open('a') as out:
            out.write(json.dumps({'type': 'response_item', 'timestamp': '2026-09-05T21:43:00Z', 'payload': {'type': 'function_call_output', 'call_id': 'verify', 'output': 'Checkpoint verified.'}}) + '\n')
        second = checkpoint(self.vault, args, payload)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['units'], second['units'])
        self.assertEqual(daily.read_bytes(), before)

    def test_fork_inherited_metadata_keeps_child_identity(self):
        path = self.transcript()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['payload']['forked_from_id'] = 'parent-session'
        rows.insert(1, {'type': 'session_meta', 'payload': {'id': 'parent-session'}})
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(len(list(sources.stream_units(path, 'codex', 'session-1'))), 2)

    def test_subagent_and_empty_sources_never_claim_capture(self):
        path = self.transcript()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['payload'].update(source={'subagent': {'thread_spawn': {}}}, forked_from_id='parent')
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        entry = {'source': 'codex', 'session_id': 'session-1', 'transcript_path': str(path)}
        result = capture.capture(self.vault, entry, model_runner=lambda *a: self.fail('subagent model call'))
        self.assertEqual(result['disposition'], 'excluded_subagent')
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0), 0)
        rows[0]['payload'].pop('source')
        path.write_text(json.dumps(rows[0]) + '\n')
        result = capture.capture(self.vault, entry, model_runner=lambda *a: self.fail('empty model call'))
        self.assertEqual(result['disposition'], 'empty_source')

    def test_excluded_queue_source_is_journaled_separately(self):
        entry = {'source': 'codex', 'session_id': 'session-1', 'transcript_path': str(self.transcript())}
        queue.enqueue(self.directory, entry)
        result = queue.drain(self.vault, self.directory, discover=False, capture_fn=lambda *a: {'disposition': 'excluded_subagent', 'reason': 'Verified subagent metadata'})
        self.assertEqual(result['excluded'], 1)
        self.assertEqual(result['completed'], 0)
        self.assertTrue((self.directory / 'excluded-v2.jsonl').exists())
        self.assertFalse((self.directory / 'processed-v2.jsonl').exists())

    def test_desktop_user_metadata_boundaries_exclude_boot(self):
        path = self.transcript()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        user = rows[2]
        boot = {'type': 'response_item', 'timestamp': user['timestamp'], 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Boot instructions'}], 'internal_chat_message_metadata_passthrough': {'content_item_kinds': ['agents_md.instructions']}}}
        rows[2] = {'type': 'response_item', 'timestamp': user['timestamp'], 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': user['payload']['message']}], 'internal_chat_message_metadata_passthrough': {'turn_id': 'desktop-turn', 'content_item_kinds': ['user.text']}}}
        rows.insert(2, boot)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        self.assertEqual(len(units), 2)
        self.assertEqual({u['turn_key'] for u in units}, {'desktop-turn'})
        self.assertNotIn('Boot instructions', json.dumps(units))

    def test_cli_duplicate_user_representations_are_one_turn(self):
        path = self.transcript()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        user = rows[2]
        rows.insert(3, {'type': 'response_item', 'timestamp': user['timestamp'], 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': user['payload']['message']}]}})
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(len(list(sources.stream_units(path, 'codex', 'session-1'))), 2)

    def test_manual_date_exception_only_output_template(self):
        text = HEADER.replace('updated_by: codex', 'updated_by: human').replace('2026-08-01', '"{{date:YYYY-MM-DD}}"')
        self.assertEqual(core.validate(text, self.vault.root / '10 - Resources/Templates/Manual Daily Note Template.md'), [])
        for name in ('Manual Daily Note Template.md', 'other/Manual Daily Note Template.md', '10 - Resources/Templates/Ordinary.md'):
            self.assertTrue(core.validate(text, self.vault.root / name))

    def test_open_line_grandfathering_does_not_rewrite_history(self):
        text = HEADER + '\n# Tuesday, September 1, 2026\n\n## Index\n'
        self.assertEqual(daily_structure(text, Path('01 - Daily Notes/2026-09-01.md')), [])
        self.assertIn('Missing Open for tomorrow line', daily_structure(text, Path('01 - Daily Notes/2026-09-06.md')))

    def test_human_schema_block_uses_every_enum(self):
        block = schema_block()
        for key in ('required', 'optional', 'status', 'project', 'type'):
            for value in core.SCHEMA[key]:
                self.assertIn('`' + value + '`', block)

    def test_session_end_real_js_spools_without_capture_claim(self):
        env = dict(os.environ, VAULT_AUTOMATION_DIR=str(self.directory))
        env.pop('VAULT_AUTOMATION', None)
        payload = {'session_id': 'fixture', 'transcript_path': str(self.transcript()), 'in_session_captured': True}
        hook = core.HERE.parent / 'hooks/vault/session-end-enqueue.js'
        child = subprocess.run(['node', str(hook)], input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr)
        files = list((self.directory / 'spool').glob('*.json'))
        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text())
        self.assertNotIn('in_session_captured', entry)
        self.assertEqual(list((self.directory / 'spool').glob('*.tmp')), [])
        self.assertEqual(json.loads((self.directory / 'queue.jsonl').read_text()), entry)

    def test_codex_discovery_advances_only_after_enqueue(self):
        path = self.transcript()
        with patch.object(queue, 'enqueue', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0)
        self.assertFalse((self.vault.state / 'codex-discovery.json').exists())
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0), 1)
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0), 0)
        self.assertEqual(len(list((self.directory / 'spool').glob('*.json'))), 1)

    def test_changed_codex_source_is_rediscovered_and_active_skipped(self):
        path = self.transcript()
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base), 0)
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0), 1)
        with path.open('a') as out:
            out.write('\n')
        self.assertEqual(queue.discover_codex(self.vault, self.directory, self.base, minimum_idle_seconds=0), 1)

    def test_concurrent_capture_conflict_rebuilds_once(self):
        path = self.transcript()
        entry = {'source': 'codex', 'session_id': 'session-1', 'transcript_path': str(path)}
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        real = capture.apply_proposal
        calls = []
        def apply(*args, **kwargs):
            if not calls:
                calls.append('conflict')
                raise core.Conflict('concurrent writer')
            return real(*args, **kwargs)
        with patch.object(capture, 'apply_proposal', side_effect=apply), patch.object(capture, 'build_prompt', side_effect=['baseline', 'fresh']) as prompt:
            with patch.object(capture, 'run_model'):
                runner = lambda *args: (self.proposal(units), 'opus 5')
                result = capture.capture(self.vault, entry, model_runner=runner)
        self.assertTrue(result['complete'])
        self.assertEqual(prompt.call_count, 2)
        receipt = sources.verified_receipts(self.vault, 'codex', 'session-1')[0]
        self.assertTrue(receipt['transaction_id'].endswith('-r1'))

    def test_interrupted_capture_replays_staged_proposal(self):
        path = self.transcript()
        entry = {'source': 'codex', 'session_id': 'session-1', 'transcript_path': str(path)}
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        runner = lambda *args: (self.proposal(units), 'opus 5')
        with patch.object(capture, 'build_prompt', return_value='evidence'), patch.object(capture, 'apply_proposal', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                capture.capture(self.vault, entry, model_runner=runner)
        result = capture.capture(self.vault, entry, model_runner=lambda *args: self.fail('paid model replay'))
        self.assertTrue(result['complete'])

    def test_capture_cannot_discard_a_source_day(self):
        path = self.transcript()
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        units.append(dict(units[-1], id='different-day', day='2026-09-06'))
        with self.assertRaisesRegex(core.VaultError, 'every source-local day'):
            capture.validate_proposal(self.vault, self.proposal(units), units)
