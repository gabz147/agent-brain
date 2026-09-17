import assert from 'node:assert/strict';
import { auditVault } from '../vault_links.mjs';

const file = path => ({path, name: path.split('/').at(-1), basename: path.split('/').at(-1).replace(/\.md$/, ''), extension: 'md'});
const files = ['Home.md', 'A.md', 'one/Duplicate.md', 'two/Duplicate.md', 'Lonely.md', '09 - Archive/Old Memory/Frozen.md'].map(file);
const link = target => ({link: target, position: {start: {line: 3}}});
const metadata = Object.fromEntries(files.map(f => [f.path, {}]));
metadata['Home.md'] = {links: ['A#Real Heading', 'A#Missing', 'A#^block', 'A#^gone', 'Duplicate', 'Gone',
  'A#Parent#Child', 'A#%ZZ', 'https://example.com', 'C:/outside.md', '09 - Archive/Old Memory/Frozen#Heading'].map(link),
  embeds: [link('A')], frontmatterLinks: [link('A')]};
metadata['A.md'] = {headings: [{heading: 'Real Heading'}], blocks: {block: {}}};
metadata['Lonely.md'] = {links: [link('Lonely')]}; // Self-links do not make an orphan reachable.
const app = {vault: {adapter: {getBasePath: () => 'C:\\Fixture'}, getFiles: () => files},
  metadataCache: {initialized: true, didFinish: true, inProgressTaskCount: 0,
    getFileCache: f => metadata[f.path],
    getFirstLinkpathDest: target => files.find(f => f.path === target || f.path === target + '.md' || f.basename === target)}};
const before = JSON.stringify(metadata);
const report = auditVault(app, 'c:/fixture');
assert.equal(report.notes, 5);
assert.equal(report.links, 12);
assert.equal(report.counts['missing-file'], 1);
assert.equal(report.counts['missing-block'], 1);
assert.equal(report.counts['heading-needs-review'], 1);
assert.equal(report.counts['ambiguous-name'], 1);
assert.equal(report.counts['nested-heading-unchecked'], 1);
assert.equal(report.counts['archive-fragment-unchecked'], 1);
assert.equal(report.counts['invalid-fragment-encoding'], 1);
assert(report.findings.some(f => f.kind === 'orphan-candidate' && f.path === 'Lonely.md'));
assert(!report.findings.some(f => f.kind === 'orphan-candidate' && f.path === 'A.md'));
assert.equal(report.findings.find(f => f.kind === 'missing-file').line, 4);
assert.equal(JSON.stringify(metadata), before);
assert.throws(() => auditVault(app, 'C:/Wrong'), /Wrong vault/);
app.vault.adapter.getBasePath = () => '/tmp/Brain';
assert.throws(() => auditVault(app, '/tmp/brain'), /Wrong vault/);
assert.equal(auditVault(app, '/tmp/Brain').notes, 5);
app.vault.adapter.getBasePath = () => 'C:/Fixture';
app.metadataCache.inProgressTaskCount = 1;
assert.throws(() => auditVault(app, 'C:/Fixture'), /indexing/);
app.metadataCache.inProgressTaskCount = 0;
delete metadata['A.md'];
assert.throws(() => auditVault(app, 'C:/Fixture'), /Missing metadata/);
console.log('Vault link audit checks passed');
