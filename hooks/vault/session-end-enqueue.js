#!/usr/bin/env node
'use strict';
// SessionEnd is deadline-bound. One durable spool file is authoritative;
// queue.jsonl is a compatible activity/count feed and may contain duplicates.
try {
  if (process.env.VAULT_AUTOMATION === '1') process.exit(0);
  const fs = require('fs');
  const path = require('path');
  const crypto = require('crypto');
  const payload = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
  if (!payload.session_id || typeof payload.transcript_path !== 'string') process.exit(0);
  const directory = process.env.BRAIN_AUTOMATION_DIR || process.env.VAULT_AUTOMATION_DIR ||
    path.join(require('os').homedir(), '.claude', 'vault-automation');
  const spool = path.join(directory, 'spool');
  fs.mkdirSync(spool, {recursive:true});
  const entry = {ts:new Date().toISOString(),source:'claude',session_id:payload.session_id,
    transcript_path:payload.transcript_path,cwd:payload.cwd};
  const bytes = JSON.stringify(entry)+'\n';
  const id = crypto.randomUUID();
  const temp = path.join(spool,id+'.tmp');
  const target = path.join(spool,id+'.json');
  let fd = fs.openSync(temp,'wx');
  try { fs.writeFileSync(fd,bytes,'utf8'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(temp,target);
  try {
    fd = fs.openSync(path.join(directory,'queue.jsonl'),'a');
    try { fs.writeFileSync(fd,bytes,'utf8'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  } catch (_) { /* durable spool remains queued */ }
} catch (error) {
  try {
    const path = require('path');
    const directory = process.env.BRAIN_AUTOMATION_DIR || process.env.VAULT_AUTOMATION_DIR ||
      path.join(require('os').homedir(), '.claude', 'vault-automation');
    require('fs').mkdirSync(directory, {recursive:true});
    require('fs').appendFileSync(path.join(directory, 'hook-errors.jsonl'),
      JSON.stringify({at:new Date().toISOString(),hook:'SessionEnd',error:String(error)})+'\n');
  } catch (_) { }
}
process.exit(0);
