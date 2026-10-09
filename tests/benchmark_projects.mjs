/** Reproducible fake-data benchmark; never reads pairing or user project data. */
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { ProjectAccess } from '../scripts/projects.mjs';
import path from 'node:path';
import { tempRoot } from './support.mjs';

const root = await mkdtemp(path.join(tempRoot, 'gm-project-benchmark-'));
const tasks = Array.from({ length: 5 }, (_, i) => ({ id: `task-${i}`, name: `Example monitor ${i}`, enabled: i === 0, prompt: 'Example detailed monitoring instructions. '.repeat(60), model: 'example/model', schedule: { cron: '0 * * * *', timezone: 'UTC' }, state: { lastStatus: 'success', lastRunAt: 1_700_000_000_000 + i, lastSessionId: `session-${i}`, lastError: null } }));
const projects = ['alpha', 'beta', 'gamma', 'delta'].map((name, i) => ({ name, host: `host-${i % 2}`, path: `/example/${name}`, project_id: name, write_targets: [] }));
const hosts = [0, 1].map(i => ({ id: `host-${i}`, label: `host-${i}`, clientToken: `fake-test-token-${i}`, relay: { relayUrl: 'wss://example.invalid/ws', serverId: `server-${i}`, hostEncPubJwk: {} } }));
let connections = 0, requests = 0;
const factory = () => {
  connections++;
  return {
    async fetch(url) {
      requests++;
      const body = url === '/health' ? { status: 'ok', compatibility: { apiVersion: 1 }, isOpenCodeReady: true } : url === '/api/config/settings' ? { projects: projects.map(p => ({ id: p.project_id, path: p.path, label: p.name })) } : url === '/api/fs/exec' ? { results: [{ stdout: JSON.stringify({ ok: true, processes: [], process_total: 0, truncated: false }) }] } : { tasks };
      return new Response(JSON.stringify(body));
    },
    getStatus: () => ({ state: 'connected' }),
    close() {},
  };
};
const access = new ProjectAccess({ registry: `${root}/projects.json`, settings: `${root}/settings.json`, factory });
try {
  await writeFile(`${root}/projects.json`, JSON.stringify({ version: 1, projects }));
  await writeFile(`${root}/settings.json`, JSON.stringify({ desktopHosts: hosts }));
  const results = await Promise.all(projects.map(p => access.result({ op: 'jobs', project: p.name })));
  assert.ok(results.every(r => r.ok));
  assert.equal(connections, 2);
  const summaries = results.map(r => ({ tasks: r.tasks, task_total: r.task_total, tasks_truncated: r.tasks_truncated }));
  const expected = tasks.map(t => ({ id: t.id, name: t.name, enabled: t.enabled, last_status: t.state.lastStatus, last_run_at: t.state.lastRunAt }));
  assert.deepEqual(summaries[0].tasks, expected);
  const rawChars = JSON.stringify(projects.map(() => ({ tasks }))).length;
  const compactChars = JSON.stringify(summaries).length;
  console.log(JSON.stringify({ fake_data: true, projects: projects.length, hosts: hosts.length, connections, requests, raw_chars: rawChars, compact_chars: compactChars, raw_tokens_est: Math.ceil(rawChars / 4), compact_tokens_est: Math.ceil(compactChars / 4), reduction_percent: Math.round((1 - compactChars / rawChars) * 1000) / 10 }));
} finally {
  access.close();
  await rm(root, { recursive: true, force: true });
}
