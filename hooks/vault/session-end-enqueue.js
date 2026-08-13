#!/usr/bin/env node
'use strict';

// SessionEnd hook: enqueue this session's info for later vault-drainer processing.
// MUST be near-instant and MUST always exit 0 — SessionEnd hooks are killed
// roughly 1.5s after firing, and a non-zero exit here would surface an error
// on every single session end.
//
// This hook only matters if you run the OPTIONAL automation module (the queue
// drainer that turns finished sessions into daily notes). Without automation it
// harmlessly appends to a queue file nothing ever reads.
//
// PORTABILITY: the automation/queue directory is read from BRAIN_AUTOMATION_DIR,
// falling back to ~/.claude/vault-automation.

try {
  // Guard: never queue automation-driven sessions (prevents the drainer's own
  // headless `claude -p` runs from re-queuing themselves infinitely).
  if (process.env.VAULT_AUTOMATION === '1') {
    process.exit(0);
  }

  const fs = require('fs');
  const os = require('os');
  const path = require('path');

  let raw = '';
  try {
    raw = fs.readFileSync(0, 'utf8');
  } catch (_) {
    raw = '';
  }

  let payload = {};
  try {
    payload = raw ? JSON.parse(raw) : {};
  } catch (_) {
    payload = {};
  }

  const queueDir = process.env.BRAIN_AUTOMATION_DIR ||
    path.join(os.homedir(), '.claude', 'vault-automation');
  const queueFile = path.join(queueDir, 'queue.jsonl');

  try {
    fs.mkdirSync(queueDir, { recursive: true });
  } catch (_) {
    // ignore — appendFileSync below will fail loudly enough if this is fatal
  }

  // Did the Stop gate already checkpoint this session in-session? If so the
  // drainer must reconcile gaps rather than re-narrate the day, or the daily
  // note gets written twice.
  let inSessionCaptured = false;
  try {
    const stateRaw = fs.readFileSync(path.join(queueDir, 'stop-state.json'), 'utf8');
    const state = JSON.parse(stateRaw);
    inSessionCaptured = !!(state && typeof state === 'object' && state[payload.session_id]);
  } catch (_) {
    inSessionCaptured = false;
  }

  const entry = {
    ts: new Date().toISOString(),
    session_id: payload.session_id,
    transcript_path: payload.transcript_path,
    cwd: payload.cwd,
    in_session_captured: inSessionCaptured,
  };

  if (typeof payload.transcript_path !== 'string' || !payload.transcript_path) process.exit(0);

  fs.appendFileSync(queueFile, JSON.stringify(entry) + '\n');
} catch (_) {
  // never let this hook fail the session
}

process.exit(0);
