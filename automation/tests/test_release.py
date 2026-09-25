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

    def test_capture_cannot_discard_a_source_day(self):
        path = self.transcript()
        units = list(sources.stream_units(path, 'codex', 'session-1'))
        units.append(dict(units[-1], id='different-day', day='2026-09-06'))
        with self.assertRaisesRegex(core.VaultError, 'every source-local day'):
            capture.validate_proposal(self.vault, self.proposal(units), units)
