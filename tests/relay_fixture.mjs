// Real upstream encryption and framing; an in-memory relay/host replaces only
// network delivery. No external server, credentials, or app state is changed.
import { createRelayTunnelClient } from '../scripts/relay_transport.mjs';
const { createHostHandshake } = await import('../scripts/vendor/openchamber-relay/handshake.ts');
const { generateEcdhKeyPair, exportPublicKeyJwk } = await import('../scripts/vendor/openchamber-relay/crypto.ts');
const { TunnelFrameType: F } = await import('../scripts/vendor/openchamber-relay/protocol.ts');
const { chunkPayload, encodeTunnelFrame, decodeTunnelFrame, encodeFrameBatch, decodeFrameBatch, encodeJsonPayload } = await import('../scripts/vendor/openchamber-relay/tunnel-codec.ts');

export async function fixture(handle, options = {}) {
  const keys = await generateEcdhKeyPair();
  const host = { id: 'fixture', label: 'fixture', clientToken: 'fake-paired-token', relay: { relayUrl: 'wss://example.invalid/ws', serverId: 'fixture', hostEncPubJwk: await exportPublicKeyJwk(keys.publicKey) } };
  const wires = [];
  const urls = [];
  const requests = [];
  const factory = config => createRelayTunnelClient({ ...config, reconnectBaseDelayMs: 5, batchWindowMs: 1, ...options.client, createWireSocket(url) {
    urls.push(url);
    const handshake = createHostHandshake(keys.privateKey, { batch: options.batch !== false });
    let channel, batch, closed = false, chain = Promise.resolve();
    const heads = new Map();
    const wire = {
      readyState: 0, onopen: null, onmessage: null, onclose: null, onerror: null,
      close(code = 1000) {
        if (closed) return;
        closed = true;
        wire.readyState = 3;
        queueMicrotask(() => wire.onclose?.({ code, reason: '' }));
      },
      send(data) {
        chain = chain.then(async () => {
          if (closed) return;
          if (typeof data === 'string') {
            const action = await handshake.handleText(data);
            if (action.type === 'established') {
              channel = action.channel; batch = action.batch;
              wire.onmessage?.({ data: action.replyText });
            } else if (action.type === 'send-text') wire.onmessage?.({ data: action.text });
            return;
          }
          const plaintext = await channel.decryptor.decrypt(new Uint8Array(data));
          for (const bytes of batch ? decodeFrameBatch(plaintext) : [plaintext]) {
            const frame = decodeTunnelFrame(bytes);
            if (frame.frameType === F.HttpRequest) {
              heads.set(frame.streamId, { ...JSON.parse(Buffer.from(frame.payload)), body: [] });
            } else if (frame.frameType === F.HttpBody) {
              heads.get(frame.streamId).body.push(Buffer.from(frame.payload));
            } else if (frame.frameType === F.StreamEnd) {
              const request = heads.get(frame.streamId);
              request.body = Buffer.concat(request.body).toString();
              requests.push(request);
              const result = await handle(request, { wire, requests, wires });
              if (!result || closed) continue;
              await deliver(encodeTunnelFrame(F.HttpResponse, frame.streamId, encodeJsonPayload({ status: result.status ?? 200, headers: {} })));
              for (const piece of chunkPayload(Buffer.from(JSON.stringify(result.body)))) await deliver(encodeTunnelFrame(F.HttpBody, frame.streamId, piece));
              await deliver(encodeTunnelFrame(F.StreamEnd, frame.streamId, new Uint8Array()));
            } else if (frame.frameType === F.Ping) await deliver(encodeTunnelFrame(F.Pong, frame.streamId, new Uint8Array()));
          }
        }).catch(() => wire.close(1011));
      },
    };
    async function deliver(frame) {
      const encrypted = await channel.encryptor.encrypt(batch ? encodeFrameBatch([frame]) : frame);
      if (!closed) wire.onmessage?.({ data: encrypted });
    }
    wires.push(wire);
    queueMicrotask(() => {
      if (options.authFailed) wire.close(4010);
      else { wire.readyState = 1; wire.onopen?.(); }
    });
    return wire;
  } });
  return { host, factory, wires, requests, urls };
}
