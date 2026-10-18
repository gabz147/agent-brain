// Read-only navigation audit using Obsidian's own Markdown parser and resolver.
import { pathToFileURL } from 'node:url';
import { homedir } from 'node:os';

export function auditVault(app, expectedRoot) {
  const canonical = value => {
    const path = value.replace(/\\+/g, '/').replace(/\/+$/, '');
    return /^[a-z]:/i.test(path) || path.startsWith('//') ? path.toLowerCase() : path;
  };
  if (canonical(app.vault.adapter.getBasePath()) !== canonical(expectedRoot)) throw Error('Wrong vault; refusing audit');
  const cache = app.metadataCache;
  if (!cache.initialized || !cache.didFinish || cache.inProgressTaskCount) throw Error('Obsidian is still indexing; retry after indexing finishes');
  const visible = path => !path.split('/').some(part => part.startsWith('.'));
  const live = path => visible(path) && !path.startsWith('09 - Archive/');
  const files = app.vault.getFiles().filter(file => visible(file.path));
  const notes = files.filter(file => live(file.path) && file.extension === 'md');
  const incoming = new Set();
  const findings = [];
  let links = 0;
  const add = (kind, file, link, extra = {}) => findings.push({kind, path: file.path,
    line: link.position ? link.position.start.line + 1 : null, target: link.link || '', ...extra});
  for (const file of notes) {
    const data = cache.getFileCache(file);
    if (!data) throw Error(`Missing metadata: ${file.path}; retry after indexing finishes`);
    for (const link of [...(data.links || []), ...(data.embeds || []), ...(data.frontmatterLinks || [])]) {
      const raw = link.link;
      if (/^[a-z][a-z\d+.-]*:|^\/\//i.test(raw)) continue; // No network or outside-vault filesystem probes.
      links++;
      const hash = raw.indexOf('#');
      const target = hash < 0 ? raw : raw.slice(0, hash);
      const fragment = hash < 0 ? '' : raw.slice(hash + 1);
      const dest = target ? cache.getFirstLinkpathDest(target, file.path) : file;
      if (!dest) {
        add('missing-file', file, link);
        continue;
      }
      if (dest.path !== file.path) incoming.add(dest.path);
      if (target && !target.includes('/')) {
        const matches = files.filter(candidate => candidate.name.toLowerCase() === target.toLowerCase()
          || (candidate.extension === 'md' && candidate.basename.toLowerCase() === target.toLowerCase()));
        if (matches.length > 1) add('ambiguous-name', file, link, {resolved: dest.path, candidates: matches.map(f => f.path)});
      }
      if (!fragment || dest.extension !== 'md') continue;
      if (!live(dest.path)) { add('archive-fragment-unchecked', file, link); continue; }
      const destinationCache = cache.getFileCache(dest);
      if (!destinationCache) throw Error(`Missing metadata: ${dest.path}`);
      let decoded;
      try { decoded = decodeURIComponent(fragment); }
      catch { add('invalid-fragment-encoding', file, link); continue; }
      if (decoded.startsWith('^')) {
        if (!Object.hasOwn(destinationCache.blocks || {}, decoded.slice(1))) add('missing-block', file, link);
      } else {
        // Nested heading paths need native rendering review; do not guess a resolution.
        if (decoded.includes('#')) { add('nested-heading-unchecked', file, link); continue; }
        const normalize = value => value.trim().replace(/\s+/g, ' ').toLowerCase();
        const headings = destinationCache.headings || [];
        if (!headings.some(heading => normalize(heading.heading) === normalize(decoded))) {
          add('heading-needs-review', file, link, {resolved: dest.path});
        }
      }
    }
  }
  for (const file of notes) if (!incoming.has(file.path)) add('orphan-candidate', file, {});
  const counts = {};
  for (const finding of findings) counts[finding.kind] = (counts[finding.kind] || 0) + 1;
  return {vault: expectedRoot, notes: notes.length, links, counts, findings,
    scope: 'Live visible Markdown sources; Archive may resolve file targets but is not inspected. External URLs/files are not checked.',
    interpretation: 'Orphans may be intentional. Ambiguous names show the native chosen target. Heading matches are conservative; formatting may require native review. No fixes are applied.'};
}

export async function evaluate(expression, port = 9333) {
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`, {signal: AbortSignal.timeout(5000)})).json();
  const targets = pages.filter(page => page.type === 'page' && page.url === 'app://obsidian.md/index.html');
  if (targets.length !== 1) throw Error('Expected one Obsidian vault window; close extra vault windows or select a dedicated debug port');
  const endpoint = new URL(targets[0].webSocketDebuggerUrl);
  if (endpoint.protocol !== 'ws:' || endpoint.hostname !== '127.0.0.1' || endpoint.port !== String(port)) throw Error('Unexpected debugger endpoint');
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(endpoint);
    const timer = setTimeout(() => finish(Error('Obsidian evaluation timed out')), 15000);
    function finish(error, value) {
      clearTimeout(timer);
      socket.close();
      error ? reject(error) : resolve(value);
    }
    socket.onopen = () => socket.send(JSON.stringify({id: 1, method: 'Runtime.evaluate',
      params: {expression, awaitPromise: true, returnByValue: true}}));
    socket.onerror = () => finish(Error('Cannot connect to Obsidian debugger'));
    socket.onmessage = event => {
      const response = JSON.parse(event.data);
      if (response.id !== 1) return;
      if (response.error || response.result.exceptionDetails) finish(Error(response.error?.message
        || response.result.exceptionDetails.exception?.description || 'Obsidian evaluation failed'));
      else finish(null, response.result.result.value);
    };
  });
}

async function main() {
  const args = process.argv.slice(2);
  const allowed = new Set(['--vault', '--port', '--limit', '--json']);
  const options = {};
  for (let i = 0; i < args.length; i++) {
    if (!allowed.has(args[i])) throw Error(`Unknown argument: ${args[i]}`);
    if (args[i] === '--json') options.json = true;
    else {
      const key = args[i].slice(2);
      if (!args[i + 1] || args[i + 1].startsWith('--')) throw Error(`Missing value: ${args[i]}`);
      options[key] = args[++i];
    }
  }
  const port = Number(options.port || 9333), limit = Number(options.limit || 20);
  if (!Number.isInteger(port) || port < 1 || port > 65535 || !Number.isInteger(limit) || limit < 1 || limit > 10000) throw Error('Invalid port or limit');
  const vault = options.vault || process.env.BRAIN_VAULT_ROOT || `${homedir()}/Documents/Brain`;
  const result = await evaluate(`(${auditVault.toString()})(app, ${JSON.stringify(vault)})`, port);
  if (options.json) console.log(JSON.stringify(result, null, 2));
  else {
    console.log(`${result.notes} notes, ${result.links} links. ${JSON.stringify(result.counts)}`);
    for (const finding of result.findings.slice(0, limit)) console.log(`${finding.kind}: ${finding.path}${finding.line ? ':' + finding.line : ''} -> ${finding.target}`);
    if (result.findings.length > limit) console.log(`${result.findings.length - limit} more; use --json for the complete report.`);
    console.log(result.scope + '\n' + result.interpretation);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => {
  console.error(`${error.message}\nRequires Node 22+ and Obsidian running with --remote-debugging-port=9333. No notes were changed.`);
  process.exitCode = 1;
});
