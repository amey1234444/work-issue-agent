import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { searchDocs } from '../src/scripts/search.mjs';
import { buildSetup } from '../src/scripts/setup.mjs';
import { getTrace, nodes, scenarios } from '../src/scripts/architecture-data.mjs';

const root = resolve(import.meta.dirname, '..');
const dist = join(root, 'dist');
const read = path => readFileSync(path, 'utf8');
function walk(dir) { return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? walk(join(dir, entry.name)) : [join(dir, entry.name)]); }

test('every article is built and available to full-text search', () => {
  const entries = JSON.parse(read(join(dist, 'search.json')));
  const sources = readdirSync(join(root, 'src/content/docs')).filter(file => file.endsWith('.md'));
  assert.equal(entries.length, sources.length);
  assert.ok(entries.length >= 14);
  for (const entry of entries) {
    assert.ok(entry.body.length > 200, entry.title);
    const html = read(join(dist, entry.url, 'index.html'));
    assert.ok(html.includes(`<title>${entry.title}`), entry.url);
    assert.equal((html.match(/<h1(?:\s|>)/g) || []).length, 1, entry.url);
  }
});

test('all generated local links and fragment targets resolve', () => {
  for (const file of walk(dist).filter(file => file.endsWith('.html'))) {
    const html = read(file);
    for (const [, href] of html.matchAll(/href="([^"]+)"/g)) {
      if (!href.startsWith('/') && !href.startsWith('#')) continue;
      const url = new URL(href, 'https://test.local');
      const target = href.startsWith('#') ? file : join(dist, url.pathname, url.pathname.endsWith('/') ? 'index.html' : '');
      assert.ok(existsSync(target), `${file}: missing ${href}`);
      if (url.hash && target.endsWith('.html')) assert.ok(read(target).includes(`id="${decodeURIComponent(url.hash.slice(1))}"`), `${file}: missing anchor ${href}`);
    }
  }
});

test('search ranks title matches, requires all words, and handles empty results', () => {
  const entries = JSON.parse(read(join(dist, 'search.json')));
  assert.equal(searchDocs(entries, 'Python API')[0].title, 'Python API');
  assert.equal(searchDocs(entries, 'configuration')[0].title, 'Configuration');
  assert.ok(searchDocs(entries, 'GITHUB_TOKEN').some(entry => entry.title === 'Configuration'));
  assert.equal(searchDocs(entries, 'zzzz-no-such-article').length, 0);
  assert.equal(searchDocs(entries, '   ').length, 6);
});

test('setup builder makes plan and local modes explicit for every provider', () => {
  for (const provider of ['mock', 'openai', 'anthropic', 'openrouter']) {
    const plan = buildSetup(provider, 'plan');
    assert.ok(plan.run.includes('--dry-run --no-pr'));
    assert.ok(plan.run.includes('--prompt'));
    assert.ok(plan.run.includes(`--provider ${provider}`));
    assert.ok(!plan.run.includes('--issue'));
    assert.ok(buildSetup(provider, 'local').run.includes('--no-pr'));
    assert.ok(!buildSetup(provider, 'pr').run.includes('--no-pr'));
    assert.ok(!buildSetup(provider, 'pr').run.includes('--dry-run'));
  }
  assert.ok(buildSetup('openrouter', 'local').install.includes('[openai]'));
  assert.ok(!buildSetup('mock', 'local').install.includes('['));
  assert.throws(() => buildSetup('unknown', 'plan'));
  assert.throws(() => buildSetup('mock', 'unknown'));
});

test('CLI reference covers every flag implemented by the Python parser', () => {
  const cli = read(join(root, '../github_issue_agent/cli.py'));
  const docs = read(join(root, 'src/content/docs/cli.md'));
  for (const [, flag] of cli.matchAll(/add_argument\(\s*["'](--[a-z-]+)["']/g)) assert.ok(docs.includes(flag), `Undocumented flag: ${flag}`);
});

test('the website documents verification and credential boundaries accurately', () => {
  assert.match(read(join(root, 'src/content/docs/verification.md')), /PR creation is not blocked by failed tests/);
  assert.match(read(join(root, 'src/content/docs/configuration.md')), /issue URL is provided or PR creation is enabled/);
  assert.match(read(join(root, 'src/content/docs/safety.md')), /git add -A/);
});

test('architecture scenarios preserve real stopping and retry behavior', () => {
  const nodeIds = new Set(nodes.map(node => node.id));
  for (const name of Object.keys(scenarios)) {
    const trace = getTrace(name);
    assert.ok(trace.every(event => nodeIds.has(event.node)));
    assert.ok(trace.every(event => event.input && event.output && event.source));
  }
  assert.ok(!getTrace('dry').some(event => ['implement', 'verify', 'publish'].includes(event.node)));
  assert.ok(!getTrace('local').some(event => event.node === 'publish'));
  assert.deepEqual(getTrace('retry').slice(4).map(event => event.id), ['failed', 'retry', 'verify', 'publish']);
  assert.deepEqual(getTrace('exhausted').slice(-2).map(event => event.id), ['exhausted', 'publish']);
  assert.ok(getTrace('skipped').some(event => event.id === 'skipped' && event.output.includes('tests_passed=True')));
  assert.throws(() => getTrace('unavailable'));
});

test('manual, architecture, and downloadable setup resources ship in the build', () => {
  const manual = read(join(dist, 'manual.md'));
  assert.ok(manual.startsWith('# User manual'));
  for (const name of ['work-issue.md', 'AGENTS.md', 'config.yaml']) assert.ok(existsSync(join(dist, 'examples', name)));
  assert.ok(read(join(dist, 'architecture/index.html')).includes('No code is executed'));
  assert.ok(read(join(dist, 'docs/index.html')).includes('User manual'));
  assert.ok(manual.includes('## 14. A repeatable operating checklist'));
});
