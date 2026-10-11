#!/usr/bin/env node
/** Agent-facing local/relay project access. No credentials in arguments or output. */
import { readFile, realpath, stat, open } from 'node:fs/promises';
import { constants } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { parseArgs } from 'node:util';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const execute = promisify(execFile);
const helperURL = new URL('./project_files.py', import.meta.url);
const MAX_BODY = 512 * 1024;
const MAX_WRITE = 32 * 1024;
const HELP = `Usage: node scripts/projects.mjs <operation> [project] [relative-path] [options]
  list                         Registered aliases; no network
  discover --host LABEL_OR_ID   Paired host's projects; no registry changes
  status PROJECT | --all       Connectivity and compatibility
  ls PROJECT [PATH]            Directory page (default 10 entries)
  read PROJECT PATH           Text excerpt + full SHA-256 (default 4000 characters)
  jobs PROJECT                Own project processes + scheduled-task summary
  write PROJECT PATH --expect HASH_OR_missing --confirm < document.txt
  exec PROJECT --command 'short command' --confirm
  batch < operations.json     Up to 20 read-only operations; reuse host connections
Options: --registry PATH --settings PATH --offset N --limit N --tail --timeout SECONDS
Defaults: ~/.local/share/GoodMorning/secretary/projects.json; ~/.config/openchamber/settings.json; timeout 20s.
Write requires exact registry write_targets. Exec requires registry allow_exec=true.
No mutation is retried. Errors, truncation, and unknown outcomes are explicit.
`;

export class AccessError extends Error {
  constructor(code, next = 'Inspect the project access configuration.') {
    super(code);
    this.code = code;
    this.next = next;
  }
}

const hints = {
  auth_failed: 'Repair pairing in OpenChamber; do not retry with the same credential.',
  unavailable: 'Check the host and relay, then retry this read.',
  timeout: 'Check host connectivity; a read can be retried.',
  outcome_unknown: 'Do not repeat the mutation. Inspect the target file hash or job state first.',
  write_conflict: 'Read the current file and reconcile changes before writing again.',
  write_busy: 'Another writer holds the lock; inspect before retrying.',
  file_too_large: 'Use read --tail for a log, or select a smaller document.',
  not_found: 'Check the registered workspace and relative path.',
  registry_missing: 'Confirm project aliases and create secretary/projects.json from the template.',
  pairing_missing: 'Pair this host in OpenChamber first.',
  runtime_unsupported: 'Use Node.js 22.18+ and Python 3.9+ on Linux.',
  directory_too_large: 'Select a more specific subdirectory; this listing exceeds 100,000 entries.',
  helper_failed: 'Check Python 3.9+ and filesystem access on the selected host.',
  incompatible_host: 'Check OpenChamber API v1 and OpenCode readiness before operating.',
  write_not_allowed: 'Ask the owner to authorize this exact target; do not broaden scope automatically.',
  confirmation_required: 'Get user authorization before passing --confirm.',
  execution_not_allowed: 'Execution needs user authorization and registry allow_exec=true.',
  secret_path: 'Do not request credential or environment files.',
  reserved_path: 'Internal write locks and temporary files are not agent-editable targets.',
  access_denied: 'Check pairing and authorized workspace scope; do not broaden permissions automatically.',
  write_size_invalid: 'Writes cap at 32 KiB. Do not truncate an existing document to fit.',
};
export function fail(code) { throw new AccessError(code, hints[code]); }

function integer(value, fallback, min, max) {
  const number = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(number) || number < min || number > max) fail('invalid_bounds');
  return number;
}

async function jsonFile(file, code) {
  let handle;
  try {
    handle = await open(file, constants.O_RDONLY | constants.O_NONBLOCK);
    if (!(await handle.stat()).isFile()) fail('configuration_invalid');
    const buffer = Buffer.alloc(2 * MAX_BODY + 1);
    let total = 0;
    while (total < buffer.length) {
      const { bytesRead } = await handle.read(buffer, total, buffer.length - total, null);
      if (!bytesRead) break;
      total += bytesRead;
    }
    if (total > 2 * MAX_BODY) fail('configuration_too_large');
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, total)));
  } catch (error) {
    if (error instanceof AccessError) throw error;
    fail(error.code === 'ENOENT' ? code : 'configuration_invalid');
  } finally { await handle?.close(); }
}

export async function boundedBody(response, max = MAX_BODY, signal) {
  const reader = response.body?.getReader();
  if (!reader) return '';
  const chunks = [];
  let bytes = 0;
  const onAbort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', onAbort, { once: true });
  if (signal?.aborted) onAbort();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > max) {
        await reader.cancel();
        fail('response_too_large');
      }
      chunks.push(Buffer.from(value));
    }
    try { return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)); }
    catch { fail('invalid_response'); }
  } finally {
    signal?.removeEventListener('abort', onAbort);
    reader.releaseLock();
  }
}

export class RelayAccess {
  constructor(host, factory, timeout = 20_000) {
    this.host = host;
    this.timeout = timeout;
    // Routing metadata is public; the paired credential belongs ONLY in HTTP
    // headers inside the encrypted tunnel, never a relay URL/query/grant.
    this.client = factory({ relayUrl: host.relay.relayUrl, serverId: host.relay.serverId, hostEncPubJwk: host.relay.hostEncPubJwk, helloTimeoutMs: timeout });
    this.healthPromise = null;
  }
  async request(url, { body, directory, safe = body === undefined } = {}) {
    const deadline = Date.now() + this.timeout;
    const attempts = safe ? 2 : 1;
    for (let attempt = 0; attempt < attempts; attempt++) {
      let timer;
      const controller = new AbortController();
      try {
        const remaining = deadline - Date.now();
        if (remaining <= 0) fail(safe ? 'timeout' : 'outcome_unknown');
        const expired = new Promise((_, reject) => {
          timer = setTimeout(() => {
            reject(new AccessError(safe ? 'timeout' : 'outcome_unknown', hints[safe ? 'timeout' : 'outcome_unknown']));
            controller.abort();
          }, remaining);
        });
        const response = await Promise.race([expired, this.client.fetch(url, {
          method: body === undefined ? 'GET' : 'POST',
          headers: { 'x-openchamber-client-token': this.host.clientToken, ...(body === undefined ? {} : { 'content-type': 'application/json' }), ...(directory ? { 'x-opencode-directory': encodeURIComponent(directory), 'x-opencode-directory-encoding': 'uri' } : {}) },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        })]);
        if (!response.ok) {
          void response.body?.cancel().catch(() => {});
          if (response.status === 401) fail('auth_failed');
          if (response.status === 403) fail('access_denied');
          if (response.status === 404) fail('not_found');
          if (response.status === 429) fail('rate_limited');
          if ([408, 502, 503, 504].includes(response.status)) {
            if (safe && attempt + 1 < attempts) continue;
            fail(safe ? 'unavailable' : 'outcome_unknown');
          }
          fail(safe ? 'remote_rejected' : 'outcome_unknown');
        }
        // Cancel through the active reader when locked, rather than relying on
        // a transport to propagate abort into its response stream.
        const text = await Promise.race([expired, boundedBody(response, MAX_BODY, controller.signal)]);
        try { return JSON.parse(text); } catch { fail(safe ? 'invalid_response' : 'outcome_unknown'); }
      } catch (error) {
        if (error instanceof AccessError) {
          if (!safe && ['response_too_large', 'invalid_response'].includes(error.code)) fail('outcome_unknown');
          throw error;
        }
        const status = this.client.getStatus();
        if (status.terminal) fail(status.lastError?.includes('authentication') ? 'auth_failed' : 'relay_rejected');
        if (!safe) fail('outcome_unknown');
        if (attempt + 1 >= attempts || Date.now() >= deadline) fail(Date.now() >= deadline ? 'timeout' : 'unavailable');
      } finally {
        clearTimeout(timer);
      }
    }
  }
  async health() {
    this.healthPromise ??= this.request('/health').then(data => {
      if (data.status !== 'ok' || data.compatibility?.apiVersion !== 1 || !data.isOpenCodeReady) fail('incompatible_host');
      return data;
    });
    return this.healthPromise;
  }
  async projects() {
    this.projectsPromise ??= this.request('/api/config/settings').then(data => {
      if (!Array.isArray(data.projects)) fail('invalid_response');
      return data.projects.map(p => ({ id: p.id, path: p.path, label: p.label }));
    });
    return this.projectsPromise;
  }
  close() { this.client.close(); }
}

export class ProjectAccess {
  constructor(options = {}) {
    this.options = options;
    this.timeout = integer(options.timeout, 20, 1, 120) * 1000;
    const runtime = process.env.SECRETARY_DIR || path.join(os.homedir(), '.local/share/GoodMorning/secretary');
    this.registryFile = options.registry ?? process.env.GM_PROJECT_REGISTRY ?? path.join(runtime, 'projects.json');
    if (this.registryFile.startsWith('~/')) this.registryFile = path.join(os.homedir(), this.registryFile.slice(2));
    this.settingsFile = options.settings ?? process.env.GM_OPENCHAMBER_SETTINGS ?? path.join(os.homedir(), '.config/openchamber/settings.json');
    this.connections = new Map();
    this.secrets = new Set();
  }
  async registry() {
    if (this.projects) return this.projects;
    const data = await jsonFile(this.registryFile, 'registry_missing');
    if (data.version !== 1 || !Array.isArray(data.projects) || data.projects.length > 100) fail('registry_invalid');
    const names = new Set();
    for (const p of data.projects) {
      if (!p || typeof p.name !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(p.name) || names.has(p.name) || typeof p.path !== 'string' || !path.posix.isAbsolute(p.path) || typeof p.host !== 'string' || !p.host || !Array.isArray(p.write_targets) || p.write_targets.some(t => typeof t !== 'string') || (p.allow_exec !== undefined && typeof p.allow_exec !== 'boolean') || (p.shared_id !== undefined && typeof p.shared_id !== 'string') || (p.project_id !== undefined && typeof p.project_id !== 'string')) fail('registry_invalid');
      names.add(p.name);
    }
    this.projects = data.projects;
    return this.projects;
  }
  async pairedHost(reference) {
    this.settings ??= await jsonFile(this.settingsFile, 'pairing_missing');
    const hosts = this.settings.desktopHosts;
    if (!Array.isArray(hosts)) fail('pairing_missing');
    for (const host of hosts) if (typeof host.clientToken === 'string' && host.clientToken) this.secrets.add(host.clientToken);
    const matching = hosts.filter(h => h.id === reference || h.label === reference);
    if (matching.length !== 1) fail(matching.length ? 'ambiguous_host' : 'pairing_missing');
    const host = matching[0];
    if (!host.relay || !host.clientToken || !host.relay.hostEncPubJwk || !host.relay.serverId) fail('pairing_missing');
    try {
      const url = new URL(host.relay.relayUrl);
      if (url.protocol !== 'wss:' || url.username || url.password || url.search || url.hash) fail('relay_url_invalid');
    } catch { fail('relay_url_invalid'); }
    return host;
  }
  async connection(reference) {
    const host = await this.pairedHost(reference);
    if (!this.connections.has(host.id)) {
      const factory = this.options.factory ?? (await import('./relay_transport.mjs')).createRelayTunnelClient;
      // Concurrent batch workers may have awaited the same dynamic import.
      if (!this.connections.has(host.id)) this.connections.set(host.id, new RelayAccess(host, factory, this.timeout));
    }
    return this.connections.get(host.id);
  }
  async project(name) {
    const project = (await this.registry()).find(p => p.name === name);
    if (!project) fail('unknown_project');
    return project;
  }
  async helper(project, payload) {
    this.helperSource ??= await readFile(helperURL, 'utf8');
    const input = { ...payload, root: project.path, write_targets: project.write_targets };
    const encoded = Buffer.from(JSON.stringify(input)).toString('base64');
    let stdout;
    if (project.host === 'local') {
      try {
        ({ stdout } = await execute('python3', [fileURLToPath(helperURL), encoded], { timeout: this.timeout, maxBuffer: MAX_BODY }));
      } catch (error) {
        if (typeof error.stdout === 'string' && error.stdout) stdout = error.stdout;
        else fail(payload.op === 'write' ? 'outcome_unknown' : 'helper_failed');
      }
    } else {
      const connection = await this.connection(project.host);
      await connection.health();
      const code = Buffer.from(this.helperSource).toString('base64');
      const command = `python3 -c 'import base64;exec(base64.b64decode("${code}"))' '${encoded}'`;
      const data = await connection.request('/api/fs/exec', { body: { cwd: project.path, commands: [command] }, directory: project.path, safe: payload.op !== 'write' });
      stdout = data.results?.[0]?.stdout;
    }
    let result;
    try { result = JSON.parse(stdout); } catch { fail(payload.op === 'write' ? 'outcome_unknown' : 'helper_failed'); }
    if (result.ok !== true) fail(Object.hasOwn(hints, result.error) || ['invalid_path', 'secret_path', 'filesystem_error', 'write_not_allowed', 'expected_hash_required', 'invalid_data', 'permission_denied', 'not_regular_file', 'changed_during_read'].includes(result.error) ? result.error : 'helper_failed');
    delete result.ok;
    return result;
  }
  async run(operation) {
    const { op, project: name } = operation;
    if (op === 'list') return { projects: (await this.registry()).map(p => ({ name: p.name, host: p.host, ...(p.shared_id ? { shared_id: p.shared_id } : {}) })) };
    if (op === 'discover') {
      if (!operation.host) fail('host_required');
      const connection = await this.connection(operation.host);
      await connection.health();
      return { projects: (await connection.projects()).map(p => ({ name: p.label, path: p.path, project_id: p.id })) };
    }
    const project = await this.project(name);
    if (op === 'status') {
      if (project.host === 'local') {
        try { if (!(await stat(await realpath(project.path))).isDirectory()) fail('invalid_root'); }
        catch (error) { if (error instanceof AccessError) throw error; fail('not_found'); }
        return { transport: 'local', ready: true };
      }
      const health = await (await this.connection(project.host)).health();
      // Checking the root distinguishes "host up" from "project mounted".
      await this.helper(project, { op: 'status' });
      return { transport: 'relay', ready: true, remote_version: health.openchamberVersion };
    }
    const limit = integer(operation.limit, op === 'read' ? 4000 : 10, 1, op === 'read' ? 16_000 : 50);
    const offset = integer(operation.offset, 0, 0, Number.MAX_SAFE_INTEGER);
    if (op === 'read' || op === 'ls') return this.helper(project, { op: op === 'ls' ? 'list' : 'read', path: operation.path ?? '.', offset, limit, tail: Boolean(operation.tail) });
    if (op === 'write') {
      if (!operation.confirm) fail('confirmation_required');
      if (typeof operation.content !== 'string' || Buffer.byteLength(operation.content) > MAX_WRITE) fail('write_size_invalid');
      if (!project.write_targets.includes(operation.path)) fail('write_not_allowed');
      return this.helper(project, { op, path: operation.path, content: operation.content, expect: operation.expect });
    }
    if (op === 'jobs') {
      const processes = await this.helper(project, { op, limit });
      if (project.host === 'local') return processes;
      const connection = await this.connection(project.host);
      const candidates = (await connection.projects()).filter(p => p.path === project.path && (!project.project_id || p.id === project.project_id));
      const id = candidates.length === 1 ? candidates[0].id : null;
      if (!id) fail('project_identity_required');
      const data = await connection.request(`/api/projects/${encodeURIComponent(id)}/scheduled-tasks`);
      if (!Array.isArray(data.tasks)) fail('invalid_response');
      const tasks = data.tasks.map(t => {
        const status = t.state?.lastStatus ?? t.lastRunStatus;
        return { id: t.id, name: this.redact(String(t.name ?? '')).slice(0, 120), enabled: t.enabled === true, last_status: ['idle', 'queued', 'running', 'success', 'error', 'skipped', 'cancelled'].includes(status) ? status : 'unknown', ...(Number.isFinite(t.state?.lastRunAt) ? { last_run_at: t.state.lastRunAt } : {}) };
      });
      return { ...processes, tasks: tasks.slice(0, limit), task_total: tasks.length, tasks_truncated: tasks.length > limit };
    }
    if (op === 'exec') {
      if (!operation.confirm || !project.allow_exec) fail('execution_not_allowed');
      if (typeof operation.command !== 'string' || !operation.command.trim() || operation.command.length > 10_000) fail('invalid_command');
      let result;
      if (project.host === 'local') {
        try {
          const value = await execute('/bin/sh', ['-c', operation.command], { cwd: project.path, timeout: this.timeout, maxBuffer: MAX_BODY });
          result = { exit_code: 0, stdout: value.stdout, stderr: value.stderr };
        } catch (error) {
          if (typeof error.code !== 'number') fail('outcome_unknown');
          result = { exit_code: error.code, stdout: error.stdout ?? '', stderr: error.stderr ?? '' };
        }
      } else {
        const connection = await this.connection(project.host);
        await connection.health();
        const data = await connection.request('/api/fs/exec', { body: { cwd: project.path, commands: [operation.command] }, directory: project.path, safe: false });
        const value = data.results?.[0];
        if (typeof value?.exitCode !== 'number') fail('outcome_unknown');
        result = { job_id: data.jobId, exit_code: value.exitCode, stdout: value.stdout ?? '', stderr: value.stderr ?? '' };
      }
      const stdout = this.redact(result.stdout), stderr = this.redact(result.stderr);
      return { ok: result.exit_code === 0, ...(result.exit_code === 0 ? {} : { error: 'command_failed', next: 'Inspect the bounded command output; execution already finished.' }), ...result, stdout: stdout.slice(0, 4000), stderr: stderr.slice(0, 1000), redacted: stdout !== result.stdout || stderr !== result.stderr, truncated: stdout.length > 4000 || stderr.length > 1000 };
    }
    fail('invalid_operation');
  }
  async result(operation) {
    try {
      const data = await this.run(operation);
      if (typeof data.text === 'string') {
        const text = this.redact(data.text);
        if (text !== data.text) { data.text = text; data.redacted = true; }
      }
      return { ok: true, op: operation.op, ...(operation.project ? { project: operation.project } : {}), ...data };
    }
    catch (error) {
      const known = error instanceof AccessError;
      return { ok: false, op: operation.op, ...(operation.project ? { project: operation.project } : {}), error: known ? error.code : 'internal_error', next: known ? error.next : 'Check runtime compatibility and configuration without printing credentials.' };
    }
  }
  redact(text, assignments = true) {
    const mask = value => value.length >= 10 ? '[REDACTED]' : '*'.repeat(value.length);
    for (const secret of this.secrets) text = text.replaceAll(secret, mask(secret));
    // Mask quoted values including spaces/escapes. Never expand an excerpt,
    // including when a placeholder is shorter than the redaction marker.
    return assignments ? text.replace(/(\b[a-z0-9_-]{0,128}(?:password|secret|token|api[_-]?key|authorization)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?|(?:Bearer\s+)?[^\s,"'}]+)/gi, (match, prefix, value) => prefix + mask(value)) : text;
  }
  close() { for (const connection of this.connections.values()) connection.close(); }
}

async function stdin(max) {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > max) fail('input_too_large');
    chunks.push(chunk);
  }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)); }
  catch { fail('invalid_data'); }
}

export async function main() {
  let access;
  try {
    const [major, minor] = process.versions.node.split('.').map(Number);
    if (major < 22 || (major === 22 && minor < 18)) fail('runtime_unsupported');
    const { values, positionals } = parseArgs({ allowPositionals: true, options: Object.fromEntries(['registry', 'settings', 'host', 'offset', 'limit', 'timeout', 'expect', 'command'].map(k => [k, { type: 'string' }]).concat(['confirm', 'tail', 'all', 'help'].map(k => [k, { type: 'boolean' }]))) });
    if (values.help || !positionals.length) { console.log(HELP); return; }
    access = new ProjectAccess(values);
    const [op, project, target, ...extra] = positionals;
    if (extra.length) fail('invalid_arguments');
    let operations;
    if (op === 'batch') {
      operations = JSON.parse(await stdin(64 * 1024));
      if (!Array.isArray(operations) || !operations.length || operations.length > 20 || operations.some(o => !o || !['list', 'status', 'ls', 'read', 'jobs'].includes(o.op))) fail('invalid_batch');
    } else if (op === 'status' && values.all) {
      operations = (await access.registry()).map(p => ({ op, project: p.name }));
    } else {
      operations = [{ op, project, path: target, ...values, ...(op === 'write' ? { content: await stdin(MAX_WRITE) } : {}) }];
    }
    // Four workers bound pressure while sharing one encrypted connection per host.
    const results = new Array(operations.length);
    let cursor = 0;
    await Promise.all(Array.from({ length: Math.min(4, operations.length) }, async () => {
      while (cursor < operations.length) {
        const index = cursor++;
        results[index] = await access.result(operations[index]);
      }
    }));
    const output = op === 'batch' || values.all ? { ok: results.every(r => r.ok), results } : results[0];
    console.log(access.redact(JSON.stringify(output), false));
    if (!output.ok) process.exitCode = 1;
  } catch (error) {
    console.log(JSON.stringify({ ok: false, error: error instanceof AccessError ? error.code : 'invalid_arguments', next: error instanceof AccessError ? error.next : 'Run node scripts/projects.mjs --help.' }));
    process.exitCode = 1;
  } finally { access?.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main();
  // Native WebSocket close-handshake timers must not keep a finished CLI alive.
  await new Promise(resolve => process.stdout.write('', resolve));
  process.exit(process.exitCode ?? 0);
}
