#!/usr/bin/env node
'use strict';

// Stop hook (asyncRewake): decide whether the turn that just ended did work
// worth checkpointing into the vault. Exit 2 => Claude Code wakes the model and
// feeds it this script's stdout as an instruction. Exit 0 => stay silent.
//
// Runs in the background (asyncRewake implies async), so it never adds latency
// to the user's turn. It MUST fail open: any internal error exits 0, because a
// crashing gate that exited 2 would wake the model on every single turn.
//
// Loop guards, in order of reliability:
//   1. VAULT_AUTOMATION=1        - the drainer's own headless runs
//   2. stop_hook_active          - Claude Code's own re-entry flag
//   3. turnKey already recorded  - the checkpoint itself ends a turn whose
//                                  human-origin boundary is unchanged, so the
//                                  second Stop for the same turn is a no-op
//   4. DEBOUNCE_MS since last fire for this session
//
// PORTABILITY: vault root and the automation/state directory are read from the
// BRAIN_VAULT_ROOT and BRAIN_AUTOMATION_DIR environment variables, falling back
// to ~/Documents/Brain and ~/.claude/vault-automation. Set them once in your
// environment so every tool agrees.

const os = require('os');
const path = require('path');

const VAULT_ROOT = process.env.BRAIN_VAULT_ROOT ||
  path.join(os.homedir(), 'Documents', 'Brain');
const STATE_DIR = process.env.BRAIN_AUTOMATION_DIR ||
  path.join(os.homedir(), '.claude', 'vault-automation');
const STATE_FILE = 'stop-state.json';

const DEBOUNCE_MS = 10 * 60 * 1000; // at most one checkpoint per 10 min per session
const STATE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_TRANSCRIPT_BYTES = 12 * 1024 * 1024;

// Substantive-work thresholds
const MIN_TEXT_CHARS = 1500; // a long answer is worth recording even with no writes
const MIN_MUTATING_SHELL = 3;

const WRITE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit']);
const SHELL_TOOLS = new Set(['Bash', 'PowerShell']);

// Shell commands that only read state. Anything not matching counts as mutating.
const READ_ONLY_SHELL = /^\s*(ls|dir|pwd|cd|cat|type|head|tail|wc|grep|rg|find|which|where|echo|printf|stat|file|du|df|jq|tree|env|date|whoami|hostname|git\s+(status|log|diff|show|branch|remote|rev-parse|describe|config\s+--get)|npm\s+(ls|list|view|outdated)|pip\s+(show|list)|Get-(ChildItem|Content|Item|Location|Command|Process|Date|Service)|Test-Path|Select-String|Measure-Object)\b/i;

const fs = require('fs');

// The user's automation toggle (written by the Obsidian Agent Pulse plugin).
// Only scope "all" silences this in-session gate; scope "afk" pauses just the
// scheduled drainer and audit. Missing or unreadable file = not paused.
function isPausedForLiveCapture() {
  try {
    const raw = fs.readFileSync(path.join(STATE_DIR, 'automation-state.json'), 'utf8');
    const st = JSON.parse(raw);
    return !!(st && typeof st === 'object' && st.paused === true && st.scope === 'all');
  } catch (_) {
    return false;
  }
}

function main() {
  if (process.env.VAULT_AUTOMATION === '1') return 0;
  if (isPausedForLiveCapture()) return 0;

  let payload = {};
  try {
    const raw = fs.readFileSync(0, 'utf8');
    payload = raw ? JSON.parse(raw) : {};
  } catch (_) {
    return 0;
  }

  if (payload.stop_hook_active === true) return 0;

  const transcriptPath = payload.transcript_path;
  const sessionId = payload.session_id;
  if (typeof transcriptPath !== 'string' || !transcriptPath) return 0;
  if (typeof sessionId !== 'string' || !sessionId) return 0;

  let stat;
  try {
    stat = fs.statSync(transcriptPath);
  } catch (_) {
    return 0;
  }
  if (!stat.isFile() || stat.size === 0 || stat.size > MAX_TRANSCRIPT_BYTES) return 0;

  let lines;
  try {
    lines = fs.readFileSync(transcriptPath, 'utf8').split('\n');
  } catch (_) {
    return 0;
  }

  // Parse, keeping only main-thread conversation records.
  const records = [];
  for (const line of lines) {
    const s = line.trim();
    if (!s) continue;
    let d;
    try {
      d = JSON.parse(s);
    } catch (_) {
      continue;
    }
    if (!d || typeof d !== 'object') continue;
    if (d.isSidechain === true) continue;
    const t = d.type;
    if (t !== 'user' && t !== 'assistant') continue;
    records.push(d);
  }
  if (!records.length) return 0;

  // Turn boundary: the last genuine human prompt. Slash-command plumbing, image
  // attachments, compaction continuations and hook-injected context all lack
  // origin.kind === 'human', which is what makes this reliable.
  let startIdx = -1;
  for (let i = records.length - 1; i >= 0; i--) {
    const d = records[i];
    if (d.type !== 'user') continue;
    const o = d.origin;
    if (o && typeof o === 'object' && o.kind === 'human') {
      startIdx = i;
      break;
    }
  }
  if (startIdx === -1) return 0;

  const boundary = records[startIdx];
  const turnKey = String(boundary.uuid || boundary.timestamp || startIdx);

  // State: per-session turnKey + last fire time.
  const statePath = path.join(STATE_DIR, STATE_FILE);
  let state = {};
  try {
    state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    if (!state || typeof state !== 'object') state = {};
  } catch (_) {
    state = {};
  }

  const now = Date.now();
  const prev = state[sessionId];
  if (prev && typeof prev === 'object') {
    if (prev.turnKey === turnKey) return 0; // already checkpointed this turn
    if (typeof prev.lastFiredMs === 'number' && now - prev.lastFiredMs < DEBOUNCE_MS) return 0;
  }

  // Scan the turn for evidence of real work.
  const turn = records.slice(startIdx + 1);
  const writes = [];
  const shells = [];
  let vaultWrites = 0;
  let textChars = 0;

  for (const d of turn) {
    const content = (d.message || {}).content;
    if (typeof content === 'string') {
      if (d.type === 'assistant') textChars += content.length;
      continue;
    }
    if (!Array.isArray(content)) continue;

    for (const block of content) {
      if (!block || typeof block !== 'object') continue;

      if (block.type === 'text' && d.type === 'assistant') {
        textChars += String(block.text || '').length;
        continue;
      }
      if (block.type !== 'tool_use') continue;

      const name = block.name;
      const input = block.input || {};

      if (WRITE_TOOLS.has(name)) {
        const fp = input.file_path || input.notebook_path;
        if (typeof fp !== 'string' || !fp) continue;
        if (isVault(fp)) vaultWrites++;
        else if (!isScratch(fp)) writes.push(fp);
      } else if (SHELL_TOOLS.has(name)) {
        const cmd = input.command;
        if (typeof cmd !== 'string' || !cmd) continue;
        if (READ_ONLY_SHELL.test(cmd)) continue;
        if (touchesOnlyScratch(cmd)) continue; // housekeeping on temp files is not work
        shells.push(cmd);
      }
    }
  }

  // The turn already wrote into the vault, so it checkpointed itself. turnKey
  // only blocks a repeat fire for the same turn; without this, any turn that
  // does work and then records it still earns a pointless wake-up.
  if (vaultWrites > 0) return 0;

  const substantive =
    writes.length >= 1 || shells.length >= MIN_MUTATING_SHELL || textChars >= MIN_TEXT_CHARS;
  if (!substantive) return 0;

  // Record the fire BEFORE emitting, so a crash after this point cannot loop.
  state[sessionId] = { turnKey, lastFiredMs: now };
  pruneState(state, now);
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    const tmp = statePath + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(state), 'utf8');
    fs.renameSync(tmp, statePath);
  } catch (_) {
    return 0; // could not persist the guard -> do not fire
  }

  process.stdout.write(buildInstruction(writes, shells, textChars));
  return 2;

  function isScratch(p) {
    const n = p.replace(/\//g, '\\').toLowerCase();
    return n.includes('\\appdata\\local\\temp\\') || n.includes('\\scratchpad\\') || n.includes('/tmp/');
  }

  function isVault(p) {
    const n = p.replace(/\//g, '\\').toLowerCase();
    return n.startsWith(VAULT_ROOT.replace(/\//g, '\\').toLowerCase());
  }

  // True when a command names at least one path and every path it names is
  // scratch or temp - deleting a working file is housekeeping, not work.
  function touchesOnlyScratch(cmd) {
    const paths = cmd.match(/(?:[A-Za-z]:|\.{0,2})[\\/][^\s"'<>|]+/g);
    if (!paths || !paths.length) return false;
    return paths.every(isScratch);
  }
}

function pruneState(state, now) {
  for (const k of Object.keys(state)) {
    const v = state[k];
    if (!v || typeof v !== 'object' || typeof v.lastFiredMs !== 'number') {
      delete state[k];
    } else if (now - v.lastFiredMs > STATE_TTL_MS) {
      delete state[k];
    }
  }
}

function buildInstruction(writes, shells, textChars) {
  const uniq = [...new Set(writes)].slice(0, 12);
  const parts = [];
  parts.push('Vault checkpoint due. The turn that just ended did substantive work and has not been recorded yet.');
  parts.push('');
  parts.push('Signals:');
  if (uniq.length) {
    parts.push('- files written: ' + uniq.join(', ') + (writes.length > uniq.length ? ' (+more)' : ''));
  }
  if (shells.length) parts.push('- mutating shell commands: ' + shells.length);
  if (textChars) parts.push('- assistant prose: ~' + textChars + ' chars');
  parts.push('');
  parts.push('Checkpoint now, per the rules in CLAUDE.md:');
  parts.push('1. Append a new `## Session N` to today\'s daily note (create it from the Daily Note Template if missing) and add its one-line entry to the `## Index` block. Existing session sections are immutable - Edit only, never Write over an existing note.');
  parts.push('2. Update the relevant project/topic note, plus that folder\'s index if anything was created, renamed, or materially changed.');
  parts.push('3. Update `Active Priorities.md` if this opened or closed an item.');
  parts.push('4. Ledgers at the vault root: if this turn made or confirmed a deliberate cross-session decision, append one row to `Decisions.md` (never edit an existing row); if an approach was abandoned for one that works on a recurring operation, append one line to `Dead Ends.md`. Skip both if nothing qualifies.');
  parts.push('5. Rewrite the daily note\'s single mutable `**Open for tomorrow:**` line (under the date heading) with the one thing the next session should pick up first, if something is left open.');
  parts.push('6. Sign everything you write as `claude`: frontmatter `updated_by: claude` + `updated: <today YYYY-MM-DD>` (both keys are required - the validator hook rejects a note without them), a trailing `` `(claude)` `` on any Index line or folder-index entry you add, and `- `claude`` at the end of the session heading (`Session N` is a label - take max+1, never renumber; the local time in the heading is the order). Never re-sign an entry another agent wrote.');
  parts.push('7. Read back each file you wrote to verify it landed.');
  parts.push('');
  parts.push('If the work genuinely does not warrant a vault entry, say so in one line and stop - do not manufacture content. Keep this brief; do not restate the work to the user.');
  return parts.join('\n');
}

let code = 0;
try {
  code = main();
} catch (_) {
  code = 0; // fail open: never wake the model because of a bug in here
}
process.exit(code);
