import { homedir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { LIMITS, Receipts, loadBundle, validateInput, hasOwnedBlock, briefingInstruction } from './core.mjs';
import { ResponseAdapter, rewriteSSE } from './transport.mjs';

const exec = promisify(execFile);
export const diagnostics = {
  id: 'goodmorning.cards', events: {},
  methods: { status: { input: { type: 'object', properties: { sessionID: { type: 'string' } }, required: ['sessionID'], additionalProperties: false }, output: { type: 'object', additionalProperties: true } } },
};
export default {
  id: 'goodmorning.briefing-delivery',
  async setup(ctx) {
    const runtime = resolve(ctx.options?.runtime ?? process.env.SECRETARY_DIR ?? join(homedir(), '.local/share/GoodMorning/secretary'));
    const receipts = new Receipts(ctx.storage);
    const adapters = new Map();
    for (const kind of ['context', 'compaction', 'generate', 'title']) await ctx.session.hook(kind, async event => {
      const before = event.messages.reduce((sum, message) => sum + (message.content ?? []).reduce((length, part) => length + (part.type === 'text' ? part.text.length : 0), 0), 0);
      await receipts.filter(event.messages);
      const instruction = kind === 'context' ? briefingInstruction(event.messages) : null;
      if (instruction) event.system.push({ type: 'text', text: instruction });
      const after = event.messages.reduce((sum, message) => sum + (message.content ?? []).reduce((length, part) => length + (part.type === 'text' ? part.text.length : 0), 0), 0);
      if (await ctx.storage.get(`enabled/${event.sessionID}`)) await ctx.storage.set(`audit/${event.sessionID}`, { kind, removedCharacters: before - after, checkedAt: Date.now() });
    });
    // Defence after protocol lowering, including native continuation state.
    // Store only counts/booleans, never provider bodies, headers or prompts.
    const guard = async (event, body, transport) => {
      if (hasOwnedBlock(body)) throw new Error('Owned briefing image reached provider serialization; request stopped.');
      await ctx.storage.set(`wire/${event.sessionID}`, { kind: event.kind, transport, ownedImageBytes: 0, checkedAt: Date.now() });
    };
    await ctx.session.hook('http.request', async event => {
      if (await ctx.storage.get(`enabled/${event.sessionID}`)) await guard(event, await event.request.clone().text(), 'http');
    });
    await ctx.session.hook('experimental.ws.send', async event => {
      if (await ctx.storage.get(`enabled/${event.sessionID}`)) await guard(event, event.frame, 'websocket');
    });
    await ctx.rpc.register(diagnostics, { status: async ({ sessionID }) => {
      const history = await ctx.session.context({ sessionID });
      let storedOwnedCards = 0, removedCharacters = 0;
      for (const message of history) {
        if (message.type !== 'assistant') continue;
        for (const part of message.content ?? []) {
          if (part.type !== 'text' || !hasOwnedBlock(part.text)) continue;
          storedOwnedCards += (part.text.match(/data:image\/webp;base64,/g) ?? []).length;
          removedCharacters += part.text.length - (await receipts.strip(part.text)).length;
        }
      }
      return { enabled: !!await ctx.storage.get(`enabled/${sessionID}`), storedOwnedCards, removedCharacters, request: await ctx.storage.get(`audit/${sessionID}`) ?? null, wire: await ctx.storage.get(`wire/${sessionID}`) ?? null };
    } });
    await ctx.tool.transform(editor => editor.add({
      name: 'briefing_cards',
      description: 'Render and attach an ALREADY SAVED /gm or /gn briefing. Input only date and kind. Returns a short marker: place it once in FINAL answer outside code fences. Never read Base64; no model image generation. Retains text/citations, omits task-duration estimates. Private/local only.',
      input: { type: 'object', properties: { date: { type: 'string', description: 'Profile-local YYYY-MM-DD date from workflow preparation.' }, kind: { type: 'string', enum: ['gm', 'gn'] } }, required: ['date', 'kind'], additionalProperties: false },
      options: { codemode: false },
      execute: async (input, context) => {
        validateInput(input);
        try {
          await exec('python', [fileURLToPath(new URL('./render_cards.py', import.meta.url)), '--runtime', runtime, '--date', input.date, '--kind', input.kind], { signal: context.signal, timeout: 60_000, maxBuffer: 16_000 });
          const bundle = await loadBundle(runtime, input);
          const receipt = await receipts.prepare(context.sessionID, bundle);
          return { content: JSON.stringify(receipt) };
        } catch (error) {
          if (context.signal?.aborted) throw error;
          // Avoid leaking traceback paths or content; no marker on partial failure.
          return { content: JSON.stringify({ error: error.code === 'ENOENT' ? 'Python or saved briefing missing.' : 'Cards could not be safely prepared. Keep the saved text; inspect local renderer diagnostics.', retry: false }) };
        }
      },
    }));
    await ctx.session.hook('http.response', async event => {
      if (event.kind !== 'primary' || !event.response.ok || !event.response.body) return;
      if (!await ctx.storage.get(`enabled/${event.sessionID}`)) return;
      const type = event.response.headers.get('content-type') ?? '';
      if (!type.includes('text/event-stream')) return;
      const adapter = new ResponseAdapter(id => receipts.expand(id, event.sessionID));
      const headers = new Headers(event.response.headers);
      headers.delete('content-length'); headers.delete('content-encoding');
      event.response = new Response(rewriteSSE(event.response.body, adapter), { status: event.response.status, statusText: event.response.statusText, headers });
    });
    await ctx.session.hook('experimental.ws.handshake', async event => {
      adapters.delete(event.sessionID);
      if (event.kind === 'primary' && await ctx.storage.get(`enabled/${event.sessionID}`)) adapters.set(event.sessionID, new ResponseAdapter(id => receipts.expand(id, event.sessionID)));
    });
    await ctx.session.hook('experimental.ws.receive', async event => {
      if (event.kind !== 'primary') return;
      const adapter = adapters.get(event.sessionID);
      if (!adapter) return;
      if (event.frame.length > LIMITS.frameCharacters) throw new Error('Provider WebSocket frame exceeds delivery limit.');
      const frame = JSON.parse(event.frame);
      event.frame = JSON.stringify(await adapter.rewrite(frame));
      if (['response.completed', 'response.failed', 'response.incomplete', 'error'].includes(frame.type)) adapters.delete(event.sessionID);
    });
    return () => adapters.clear();
  },
};
