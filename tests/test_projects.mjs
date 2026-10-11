import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { RelayAccess, ProjectAccess, boundedBody } from '../integrations/projects/index.mjs';
import { fixture } from './relay_fixture.mjs';
import { execFile } from 'node:child_process';
import { tempRoot } from './support.mjs';
import { promisify } from 'node:util';
const execute = promisify(execFile);

const health = { status: 'ok', compatibility: { apiVersion: 1 }, isOpenCodeReady: true, openchamberVersion: 'fixture' };
const context = async (t, handle, options) => {
  const f = await fixture(handle, options);
  const access = new RelayAccess(f.host, f.factory, 2000);
  t.after(() => access.close());
  return { ...f, access };
};

test('encrypted JSON request and fragmented response, batching enabled', async t => {
  const value = 'x'.repeat(150_000);
  const f = await context(t, request => {
    assert.equal(request.headers['x-openchamber-client-token'], 'fake-paired-token');
    assert.equal(decodeURIComponent(request.headers['x-opencode-directory']), '/fake/项目');
    assert.equal(request.headers['x-opencode-directory-encoding'], 'uri');
    assert.deepEqual(JSON.parse(request.body), { message: 'hello' });
    return { body: { value } };
  });
  assert.deepEqual(await f.access.request('/api/fake', { body: { message: 'hello' }, directory: '/fake/项目' }), { value });
  assert.equal(new URL(f.urls[0]).searchParams.has('grant'), false);
  assert.equal(f.urls[0].includes(f.host.clientToken), false);
});

test('older peer without batching is refused before any request', async t => {
  const f = await context(t, () => ({ body: { ok: true } }), { batch: false });
  await assert.rejects(f.access.request('/health'));
  assert.equal(f.requests.length, 0);
});

test('older peer without flow control is refused before any request', async t => {
  const f = await context(t, () => ({ body: { ok: true } }), { flowControl: false });
  await assert.rejects(f.access.request('/health'));
  assert.equal(f.requests.length, 0);
});

test('read reconnects once after dispatched request loses response', async t => {
  const f = await context(t, (request, server) => {
    if (server.requests.length === 1) { server.wire.close(1012); return null; }
    return { body: { recovered: true } };
  });
  assert.deepEqual(await f.access.request('/health'), { recovered: true });
  assert.equal(f.requests.length, 2);
  assert.equal(f.wires.length, 2);
});

test('lost mutation response is outcome unknown and is never replayed', async t => {
  const f = await context(t, (request, server) => { server.wire.close(1012); return null; });
  await assert.rejects(f.access.request('/api/fs/exec', { body: { command: 'fake mutation' } }), { code: 'outcome_unknown' });
  assert.equal(f.requests.length, 1);
});

test('relay authentication rejection stops without retry loops', async t => {
  const f = await context(t, () => null, { authFailed: true });
  await assert.rejects(f.access.request('/health'), { code: 'auth_failed' });
  assert.equal(f.wires.length, 1);
});

test('HTTP authentication and missing files are definite errors', async t => {
  for (const [status, code] of [[401, 'auth_failed'], [403, 'access_denied'], [404, 'not_found'], [429, 'rate_limited']]) {
    const f = await context(t, () => ({ status, body: {} }));
    await assert.rejects(f.access.request('/api/fake'), { code });
    assert.equal(f.requests.length, 1);
  }
});

test('unavailable reads retry at most once', async t => {
  const f = await context(t, () => ({ status: 503, body: {} }));
  await assert.rejects(f.access.request('/health'), { code: 'unavailable' });
  assert.equal(f.requests.length, 2);
});

test('mutating HTTP 503 is not retried', async t => {
  const f = await context(t, () => ({ status: 503, body: {} }));
  await assert.rejects(f.access.request('/api/fs/exec', { body: {} }), { code: 'outcome_unknown' });
  assert.equal(f.requests.length, 1);
});

test('read timeout stays within the shared request deadline', async t => {
  const f = await context(t, () => null);
  f.access.timeout = 50;
  const started = Date.now();
  await assert.rejects(f.access.request('/health'), { code: 'timeout' });
  assert.ok(Date.now() - started < 500);
});

test('deadline does not depend on a transport honoring abort signals', async t => {
  const client = { fetch: () => new Promise(() => {}), getStatus: () => ({ terminal: false }), close() {} };
  const access = new RelayAccess({ relay: {} }, () => client, 20);
  t.after(() => access.close());
  const result = await Promise.race([
    access.request('/health').then(() => 'unexpected success', error => error.code),
    new Promise(resolve => setTimeout(() => resolve('deadline ignored'), 150)),
  ]);
  assert.equal(result, 'timeout');
});

test('response body stalls are included in the request deadline', async t => {
  let cancelled = false;
  const response = new Response(new ReadableStream({ start() {}, cancel() { cancelled = true; } }));
  const client = { fetch: async () => response, getStatus: () => ({ terminal: false }), close() {} };
  const access = new RelayAccess({ relay: {} }, () => client, 20);
  t.after(() => access.close());
  const result = await Promise.race([
    access.request('/health').then(() => 'unexpected success', error => error.code),
    new Promise(resolve => setTimeout(() => resolve('deadline ignored'), 150)),
  ]);
  assert.equal(result, 'timeout');
  assert.equal(cancelled, true);
});

test('ignored mutation abort is still uncertain and never replayed', async t => {
  let calls = 0;
  const client = { fetch: () => { calls++; return new Promise(() => {}); }, getStatus: () => ({ terminal: false }), close() {} };
  const access = new RelayAccess({ relay: {} }, () => client, 20);
  t.after(() => access.close());
  await assert.rejects(access.request('/api/fake', { body: {} }), { code: 'outcome_unknown' });
  assert.equal(calls, 1);
});

test('mutation timeout reports uncertainty, not definite failure', async t => {
  const f = await context(t, () => null);
  f.access.timeout = 50;
  await assert.rejects(f.access.request('/api/fs/exec', { body: {} }), { code: 'outcome_unknown' });
  assert.equal(f.requests.length, 1);
});

test('response-size cap cancels an oversized stream', async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({ start(c) { c.enqueue(new Uint8Array(20)); }, cancel() { cancelled = true; } }));
  await assert.rejects(boundedBody(response, 10), { code: 'response_too_large' });
  assert.equal(cancelled, true);
  await assert.rejects(boundedBody(new Response(Buffer.from([255]))), { code: 'invalid_response' });
});

test('incompatible health does not permit project operations', async t => {
  const f = await context(t, () => ({ body: { ...health, compatibility: { apiVersion: 99 } } }));
  await assert.rejects(f.access.health(), { code: 'incompatible_host' });
});

test('health requests are single-flight per shared connection', async t => {
  const f = await context(t, () => ({ body: health }));
  await Promise.all([f.access.health(), f.access.health(), f.access.health()]);
  assert.equal(f.requests.length, 1);
});

async function localAccess(t, projects) {
  const root = await mkdtemp(path.join(tempRoot, 'gm-projects-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const registry = path.join(root, 'registry.json');
  await writeFile(path.join(root, 'PLAN.md'), 'fake project\n');
  await writeFile(registry, JSON.stringify({ version: 1, projects: projects ?? [{ name: 'demo', host: 'local', path: root, write_targets: ['PLAN.md'], allow_exec: false }] }));
  return { root, registry, access: new ProjectAccess({ registry }) };
}

test('local alias read uses compact contract without loading pairing', async t => {
  const { access } = await localAccess(t);
  const result = await access.result({ op: 'read', project: 'demo', path: 'PLAN.md', limit: 4 });
  assert.equal(result.ok, true);
  assert.equal(result.text, 'fake');
  assert.equal(access.settings, undefined);
});

test('write needs both confirmation and exact scope', async t => {
  const { access } = await localAccess(t);
  const base = { op: 'write', project: 'demo', path: 'PLAN.md', content: 'new', expect: 'missing' };
  assert.equal((await access.result(base)).error, 'confirmation_required');
  assert.equal((await access.result({ ...base, confirm: true, path: 'other.md' })).error, 'write_not_allowed');
});

test('arbitrary execution disabled by default, even with confirm', async t => {
  const { access } = await localAccess(t);
  assert.equal((await access.result({ op: 'exec', project: 'demo', command: 'true', confirm: true })).error, 'execution_not_allowed');
});

test('duplicate aliases and malformed bounds fail explicitly', async t => {
  const project = { name: 'same', host: 'local', path: '/fake', write_targets: [] };
  const { access } = await localAccess(t, [project, project]);
  assert.equal((await access.result({ op: 'list' })).error, 'registry_invalid');
});

test('parallel remote workers reuse one paired host connection', async t => {
  const { root, registry } = await localAccess(t, []);
  const settings = path.join(root, 'settings.json');
  await writeFile(settings, JSON.stringify({ desktopHosts: [{ id: 'host-id', label: 'host-label', clientToken: 'private-token', relay: { relayUrl: 'wss://example.invalid/ws', serverId: 'server', hostEncPubJwk: {} } }] }));
  let count = 0;
  const access = new ProjectAccess({ registry, settings, factory: () => { count++; return { close() {} }; } });
  t.after(() => access.close());
  await Promise.all([access.connection('host-id'), access.connection('host-label'), access.connection('host-id')]);
  assert.equal(count, 1);
  assert.equal(access.redact('credential private-token'), 'credential [REDACTED]');
});

test('missing registry does not initialize user data', async () => {
  const access = new ProjectAccess({ registry: path.join(tmpdir(), 'gm-nonexistent-registry.json') });
  assert.equal((await access.result({ op: 'list' })).error, 'registry_missing');
});

test('text credential assignments are masked and marked', async t => {
  const { access, root } = await localAccess(t);
  await writeFile(path.join(root, 'PLAN.md'), 'API_KEY=fake-private-value\nordinary text\n');
  const result = await access.result({ op: 'read', project: 'demo', path: 'PLAN.md' });
  assert.equal(result.redacted, true);
  assert.equal(result.text, 'API_KEY=[REDACTED]\nordinary text\n');
  assert.equal(result.sha256.length, 64);
  const short = 'api_key=x';
  assert.ok(access.redact(short).length <= short.length);
  assert.equal(access.redact("password='fake multiword value'"), 'password=[REDACTED]');
  assert.equal(access.redact('x'.repeat(200_000)).length, 200_000);
});

test('CLI returns one compact JSON object and useful failure exit code', async t => {
  const { registry } = await localAccess(t);
  const cli = new URL('../scripts/projects.mjs', import.meta.url).pathname;
  const { stdout, stderr } = await execute(process.execPath, [cli, 'read', 'demo', 'PLAN.md', '--registry', registry, '--limit', '4']);
  assert.equal(stderr, '');
  assert.equal(stdout.trim().split('\n').length, 1);
  assert.equal(JSON.parse(stdout).text, 'fake');
  await assert.rejects(execute(process.execPath, [cli, 'read', 'demo', '.env', '--registry', registry]), error => {
    assert.equal(error.code, 1);
    assert.equal(JSON.parse(error.stdout).error, 'secret_path');
    return true;
  });
});

test('finished CLI flushes JSON and exits despite lingering close timers', async t => {
  const { registry } = await localAccess(t);
  const cli = new URL('../scripts/projects.mjs', import.meta.url).pathname;
  const preload = 'data:text/javascript,' + encodeURIComponent('setInterval(() => {}, 60000);');
  const { stdout } = await execute(process.execPath, ['--import', preload, cli, 'list', '--registry', registry], { timeout: 1500 });
  assert.equal(JSON.parse(stdout).ok, true);
});

test('confirmed short commands return explicit nonzero exit state', async t => {
  const { access, registry, root } = await localAccess(t);
  await writeFile(registry, JSON.stringify({ version: 1, projects: [{ name: 'demo', host: 'local', path: root, write_targets: [], allow_exec: true }] }));
  const result = await access.result({ op: 'exec', project: 'demo', command: 'exit 7', confirm: true });
  assert.equal(result.ok, false);
  assert.equal(result.error, 'command_failed');
  assert.equal(result.exit_code, 7);
});
