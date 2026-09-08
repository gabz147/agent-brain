#!/usr/bin/env node
'use strict';
// Async Stop hook. Python owns the shared decision logic; an internal error
// must never wake or block the interactive session.
try {
  if (process.env.VAULT_AUTOMATION === '1') process.exit(0);
  const fs = require('fs');
  const path = require('path');
  const { spawnSync } = require('child_process');
  const directory = process.env.BRAIN_AUTOMATION_DIR || process.env.VAULT_AUTOMATION_DIR ||
    path.join(require('os').homedir(), '.claude', 'vault-automation');
  const python = process.env.BRAIN_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const result = spawnSync(python, [path.join(directory, 'vault_hooks.py')],
    { input: fs.readFileSync(0), encoding: 'utf8', windowsHide: true, timeout: 10000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  // Python also exits 2 for a missing script. Only the controller's explicit
  // checkpoint message is a wake request; launcher failures must fail open.
  if (result.status === 2 && (result.stdout || '').startsWith('Vault checkpoint requested for session ')) {
    process.stdout.write(result.stdout || '');
    process.exit(2);
  }
  if (result.error || result.status !== 0) {
    fs.mkdirSync(directory, {recursive: true});
    fs.appendFileSync(path.join(directory, 'hook-errors.jsonl'),
      JSON.stringify({at:new Date().toISOString(),hook:'Stop launcher',
        error:String(result.error || result.stderr || ('exit ' + result.status)).slice(0, 800)})+'\n');
  }
} catch (_) { }
process.exit(0);
