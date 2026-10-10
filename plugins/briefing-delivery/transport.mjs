import { LIMITS, MarkerStream } from './core.mjs';

// One state per output item, not per network chunk. Responses repeats its text
// in done/completed events; use the expanded text there without duplicating it.
export class ResponseAdapter {
  constructor(resolve) { this.resolve = resolve; this.states = new Map(); }
  state(key) {
    if (!this.states.has(key)) this.states.set(key, { stream: new MarkerStream(this.resolve), text: '', raw: '' });
    return this.states.get(key);
  }
  async delta(key, raw, final = false) {
    const state = this.state(key);
    state.raw += raw;
    const text = state.commentary ? raw : await state.stream.push(raw, final);
    state.text += text;
    if (state.text.length > LIMITS.frameCharacters) throw new Error('Briefing response exceeds stream limit.');
    return text;
  }
  async full(key, raw) {
    const state = this.state(key);
    if (!state.raw) await this.delta(key, raw, true);
    else if (raw.startsWith(state.raw)) await this.delta(key, raw.slice(state.raw.length), true);
    else throw new Error('Provider returned inconsistent final text.');
    return state.text;
  }
  async rewrite(frame) {
    if (frame.type === 'response.output_item.added' && frame.item?.type === 'message') this.state(frame.item.id).commentary = frame.item.phase === 'commentary';
    if (frame.choices) {
      for (const choice of frame.choices) {
        const key = `chat:${choice.index ?? 0}`;
        if (choice.delta?.content !== undefined) choice.delta.content = await this.delta(key, choice.delta.content);
        if (choice.finish_reason && this.states.has(key)) {
          const tail = await this.delta(key, '', true);
          if (tail) { choice.delta ??= {}; choice.delta.content = (choice.delta.content ?? '') + tail; }
        }
        if (choice.message?.content !== undefined) choice.message.content = await this.full(key, choice.message.content);
      }
    }
    if (frame.type === 'response.output_text.delta') frame.delta = await this.delta(frame.item_id, frame.delta);
    if (frame.type === 'response.output_text.done') {
      const state = this.state(frame.item_id);
      const before = state.text.length;
      const full = await this.full(frame.item_id, frame.text);
      const tail = full.slice(before);
      // OpenResponses ignores done when it has seen deltas. Reconcile any final
      // unfinished prefix as a delta, while output_item.done retains full text.
      if (tail) { frame.type = 'response.output_text.delta'; frame.delta = tail; delete frame.text; }
      else frame.text = full;
    }
    const rewriteItem = async item => {
      if (item?.type !== 'message') return;
      for (const part of item.content ?? []) if (part.type === 'output_text') part.text = await this.full(item.id, part.text);
    };
    if (frame.type === 'response.output_item.done') await rewriteItem(frame.item);
    if (frame.type === 'response.completed' || frame.object === 'response') for (const item of frame.response?.output ?? frame.output ?? []) await rewriteItem(item);
    return frame;
  }
}

// Incremental UTF-8 + SSE parser. Preserve comments, event IDs, CRLF, multiline
// data and backpressure. Cancellation propagates to the original reader.
export function rewriteSSE(body, adapter) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let pending = '', ended = false;
  async function rewriteEvent(event) {
    const lines = event.split('\n');
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
    if (!data || data === '[DONE]') return event;
    const frame = JSON.parse(data);
    const rewritten = JSON.stringify(await adapter.rewrite(frame));
    // A final-only text event may become a delta, so preserve matching SSE type.
    const metadata = lines.filter(line => !line.startsWith('data:')).map(line => line.startsWith('event:') && frame.type ? `event: ${frame.type}` : line);
    return [...metadata, 'data: ' + rewritten].join('\n');
  }
  return new ReadableStream({
    async pull(controller) {
      try {
        while (true) {
          const boundary = pending.indexOf('\n\n');
          if (boundary >= 0) {
            const event = pending.slice(0, boundary);
            pending = pending.slice(boundary + 2);
            controller.enqueue(encoder.encode(await rewriteEvent(event) + '\n\n'));
            return;
          }
          if (ended) {
            if (pending) controller.enqueue(encoder.encode(await rewriteEvent(pending) + '\n\n'));
            controller.close(); return;
          }
          const chunk = await reader.read();
          ended = chunk.done;
          pending += decoder.decode(chunk.value, { stream: !chunk.done });
          // CRLF can itself split across byte chunks; normalize only complete pairs.
          pending = pending.replaceAll('\r\n', '\n');
          if (pending.length > LIMITS.frameCharacters) throw new Error('Provider SSE frame exceeds delivery limit.');
        }
      } catch (error) { await reader.cancel(error).catch(() => {}); controller.error(error); }
    },
    cancel(reason) { return reader.cancel(reason); },
  });
}
