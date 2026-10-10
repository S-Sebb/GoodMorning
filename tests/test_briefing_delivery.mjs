import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, symlink, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { LIMITS, MarkerStream, Receipts, sha, loadBundle, payloadFor, validateInput, hasOwnedBlock, briefingInstruction } from '../plugins/briefing-delivery/core.mjs';
import { ResponseAdapter, rewriteSSE } from '../plugins/briefing-delivery/transport.mjs';
import delivery from '../plugins/briefing-delivery/index.mjs';

function storage() {
  const data = new Map();
  return { get: async key => structuredClone(data.get(key)), set: async (key, value) => data.set(key, structuredClone(value)), data };
}
const id = 'a'.repeat(32), marker = `[[GM_CARD:${id}]]`;
test('older local-plugin contexts return a compact failure even without an abort signal', async () => {
  let tool;
  await delivery.setup({
    options: { runtime: '/tmp/opencode/briefing-missing-runtime-for-test' }, storage: storage(),
    session: { hook: async () => {} }, rpc: { register: async () => {} },
    tool: { transform: async callback => callback({ add: definition => { tool = definition; } }) },
  });
  const result = await tool.execute({ date: '2026-10-10', kind: 'gm' }, { sessionID: 'ses_test' });
  assert(JSON.parse(result.content).error);
  assert(!result.content.includes('base64'));
});
test('explicit gm/gn requests get default-delivery guidance without overriding text or duplicate rules', () => {
  const messages = text => [{ role: 'user', content: [{ type: 'text', text }] }];
  for (const input of ['/gm Good morning!', '/gn', '  /gm text only']) {
    const instruction = briefingInstruction(messages(input));
    assert(instruction.includes('Save complete text first'));
    assert(instruction.includes('explicitly requests text only'));
    assert(instruction.includes('duplicate/consent rules'));
  }
  assert.equal(briefingInstruction(messages('Investigate the /gm plugin')), null);
  assert.equal(briefingInstruction([...messages('/gm'), ...messages('Different task now')]), null);
});
test('all marker splits, duplicate suppression, unknown and unfinished markers', async () => {
  for (let split = 1; split < marker.length; split++) {
    const stream = new MarkerStream(async () => '<image>');
    assert.equal(await stream.push('π ' + marker.slice(0, split)) + await stream.push(marker.slice(split) + ' after') + await stream.push('', true), 'π <image> after');
  }
  const stream = new MarkerStream(async () => '<image>');
  assert.equal(await stream.push(marker + marker, true), '<image>');
  assert.equal(await stream.push('incomplete [[GM_CA') + await stream.push('', true), 'incomplete [[GM_CA');
  assert.match(await new MarkerStream(async () => null).push(marker, true), /unavailable/);
});

test('durable ownership filtering works without assets, including forked history', async () => {
  const store = storage();
  const receipts = new Receipts(store);
  const bundle = { date: '2026-10-10', kind: 'gm', sourceHash: 'hash', directory: '/does-not-exist', images: [{ file: '01-card.webp', bytes: Buffer.from('fixture'), hash: 'hash' }], total: 7, source: 'source.md' };
  const prepared = await receipts.prepare('ses_test', bundle);
  const ownedID = /[a-f0-9]{32}/.exec(prepared.marker)[0];
  const payload = payloadFor(ownedID, bundle);
  const original = [{ role: 'assistant', content: [{ type: 'text', text: 'Original text.\n' + payload }] }, { role: 'user', content: [{ type: 'text', text: payload }] }];
  const draft = structuredClone(original);
  await new Receipts(store).filter(draft);
  assert.match(draft[0].content[0].text, /Original text/);
  assert(!draft[0].content[0].text.includes('base64'));
  assert.equal(draft[1].content[0].text, payload);
  assert(original[0].content[0].text.includes('base64'));
  await assert.rejects(receipts.expand(ownedID, 'ses_test'));
  assert.equal(await receipts.expand(ownedID, 'ses_other'), null);
  await assert.rejects(receipts.strip(payload.replace('Zml4dHVyZQ==', 'changed')), /integrity|changed/);
  await assert.rejects(new Receipts(storage()).strip(payload), /Restore/);
});

test('hidden ownership definitions retain legacy filtering and versioned receipts', async () => {
  const store = storage();
  const receipts = new Receipts(store);
  const bundle = { date: '2026-10-10', kind: 'gm', sourceHash: 'hash', directory: '/missing', images: [{ file: '01-card.webp', bytes: Buffer.from('fixture'), hash: 'hash' }], total: 7, source: 'source.md' };
  const legacy = payloadFor(id, bundle, 1);
  const oldReceipt = { id, sessionID: 'ses_test', date: bundle.date, kind: bundle.kind, count: 1, payloadHash: sha(legacy) };
  await store.set(`receipts/${id}`, oldReceipt);
  const prepared = await receipts.prepare('ses_test', bundle);
  const newID = /[a-f0-9]{32}/.exec(prepared.marker)[0];
  assert.notEqual(newID, id);
  assert.deepEqual(await store.get(`receipts/${id}`), oldReceipt);
  const hidden = payloadFor(newID, bundle);
  assert(!hidden.includes('<!--'));
  assert(hidden.startsWith(`[gm-card-${newID}-begin]: #\n\n`));
  assert.equal((hidden.match(/data:image\/webp/g) ?? []).length, 1);
  for (const payload of [legacy, hidden]) {
    assert(hasOwnedBlock(payload));
    assert(hasOwnedBlock(JSON.stringify({ input: payload })));
    assert(!hasOwnedBlock(await receipts.strip(payload)));
    await assert.rejects(receipts.strip(payload.replace('base64,', 'base64,tampered')), /changed/);
  }
  const mixed = await receipts.strip('Before.\n' + legacy + '\nBetween.\n' + hidden + '\nAfter.');
  assert(!mixed.includes('base64'));
  assert(mixed.includes('Before.') && mixed.includes('Between.') && mixed.includes('After.'));
});

test('streamed SSE handles byte-split UTF-8, CRLF and multiline data', async () => {
  const frame = { choices: [{ index: 0, delta: { content: '你好 ' + marker }, finish_reason: 'stop' }] };
  const bytes = new TextEncoder().encode('event: message\r\n: comment\r\ndata: ' + JSON.stringify(frame).replace(',"finish_reason"', ',\r\ndata: "finish_reason"') + '\r\n\r\ndata: [DONE]\r\n\r\n');
  let offset = 0;
  const input = new ReadableStream({ pull(controller) { if (offset === bytes.length) return controller.close(); controller.enqueue(bytes.slice(offset, ++offset)); } });
  const output = await new Response(rewriteSSE(input, new ResponseAdapter(async () => '<image>'))).text();
  assert(output.includes('你好 <image>'));
  assert(output.includes(': comment'));
  assert(output.includes('[DONE]'));
});

test('SSE cancellation reaches upstream and oversized frames fail', async () => {
  let cancelled = false;
  const input = new ReadableStream({ cancel() { cancelled = true; } });
  await rewriteSSE(input, new ResponseAdapter(async () => null)).cancel();
  assert(cancelled);
  const oversized = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('x'.repeat(LIMITS.frameCharacters + 1))); c.close(); } });
  await assert.rejects(new Response(rewriteSSE(oversized, new ResponseAdapter(async () => null))).text(), /limit/);
});

test('Responses delta/done/completed agree, including final-only and partial marker', async () => {
  const adapter = new ResponseAdapter(async () => '<image>');
  const raw = 'Saved text. ' + marker;
  let observed = '';
  for (const delta of [raw.slice(0, 22), raw.slice(22)]) observed += (await adapter.rewrite({ type: 'response.output_text.delta', item_id: 'msg', delta })).delta;
  const done = await adapter.rewrite({ type: 'response.output_text.done', item_id: 'msg', text: raw });
  const complete = await adapter.rewrite({ type: 'response.completed', response: { output: [{ type: 'message', id: 'msg', content: [{ type: 'output_text', text: raw }] }] } });
  assert.equal(observed, 'Saved text. <image>');
  assert.equal(done.text, observed);
  assert.equal(complete.response.output[0].content[0].text, observed);
  const finalOnly = await new ResponseAdapter(async () => '<image>').rewrite({ type: 'response.output_item.done', item: { type: 'message', id: 'other', content: [{ type: 'output_text', text: marker }] } });
  assert.equal(finalOnly.item.content[0].text, '<image>');
  const unfinished = new ResponseAdapter(async () => '<image>');
  await unfinished.rewrite({ type: 'response.output_text.delta', item_id: 'msg', delta: '[[GM_CA' });
  assert.equal((await unfinished.rewrite({ type: 'response.output_text.done', item_id: 'msg', text: '[[GM_CA' })).delta, '[[GM_CA');
});

test('Responses commentary never expands an attachment marker', async () => {
  let expanded = false;
  const adapter = new ResponseAdapter(async () => { expanded = true; return '<image>'; });
  await adapter.rewrite({ type: 'response.output_item.added', item: { type: 'message', id: 'comment', phase: 'commentary' } });
  assert.equal((await adapter.rewrite({ type: 'response.output_text.delta', item_id: 'comment', delta: marker })).delta, marker);
  assert.equal(expanded, false);
});

test('renderer and attachment validation: gm/gn, immutable text, symlinks, hashes', async () => {
  const root = await mkdtemp(join('/tmp/opencode/', 'gm-delivery-test-'));
  try {
    await mkdir(join(root, 'daily'));
    for (const kind of ['gm', 'gn']) {
      const source = `Hello.\n\n## Schedule\n\n| Date | Time | Event | Place | Prep |\n|---|---|---|---|---|\n| Monday | 09:00–11:00 | Teaching | Room | Bring slides |\n\n## Priorities\n\n- [ ] Due 2026-10-15 — task. Ten minutes tonight saves a rush.\n\n## News\n\n### AI\n\n- Headline — factual detail. [Source](https://example.org/story)\n`;
      const sourcePath = join(root, 'daily', `2026-10-10.${kind}.md`);
      await writeFile(sourcePath, source);
      const renderer = new URL('../plugins/briefing-delivery/render_cards.py', import.meta.url);
      execFileSync('python', [renderer.pathname, '--runtime', root, '--date', '2026-10-10', '--kind', kind]);
      const bundle = await loadBundle(root, { date: '2026-10-10', kind });
      assert.equal(bundle.images.length, 3);
      assert.equal(await readFile(sourcePath, 'utf8'), source);
      assert((await readFile(join(bundle.directory, 'sources.md'), 'utf8')).includes('https://example.org/story'));
      const file = join(bundle.directory, bundle.images[0].file);
      const saved = await readFile(file);
      await rm(file);
      await symlink(sourcePath, file);
      await assert.rejects(loadBundle(root, { date: '2026-10-10', kind }), /canonical/);
      await rm(file);
      await writeFile(file, saved);
      await writeFile(sourcePath, source + '\nchanged');
      await assert.rejects(loadBundle(root, { date: '2026-10-10', kind }));
    }
    for (const bad of [{ date: '../escape', kind: 'gm' }, { date: '2026-02-30', kind: 'gm' }, { date: '2026-10-10', kind: 'xx' }]) assert.throws(() => validateInput(bad));
  } finally { await rm(root, { recursive: true }); }
});
