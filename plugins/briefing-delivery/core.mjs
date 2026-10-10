import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { open, realpath } from 'node:fs/promises';
import { join, basename, sep } from 'node:path';

export const LIMITS = Object.freeze({ images: 12, imageBytes: 1_000_000, totalBytes: 3_000_000, manifestBytes: 32_000, sourceBytes: 150_000, frameCharacters: 8_000_000 });
export const sha = value => createHash('sha256').update(value).digest('hex');
export const markerFor = id => `[[GM_CARD:${id}]]`;
const ID = /^[a-f0-9]{32}$/;
const BEGIN = /<!-- gm-card:([a-f0-9]{32}):begin -->|\[gm-card-([a-f0-9]{32})-begin\]: #/g;
export const hasOwnedBlock = text => /<!-- gm-card:[a-f0-9]{32}:begin -->|\[gm-card-[a-f0-9]{32}-begin\]: #/.test(text);

export function briefingInstruction(messages) {
  const latest = [...messages].reverse().find(message => message.role === 'user');
  const text = (latest?.content ?? []).filter(part => part.type === 'text').map(part => part.text).join('\n').trimStart();
  if (!/^\/(gm|gn)(?:\s|$)/i.test(text)) return null;
  return 'For this /gm or /gn, use image-card delivery by default unless the user explicitly requests text only. Follow the GoodMorning workflow and its duplicate/consent rules. Save complete text first, then call briefing_cards with the profile-local date and kind. Put its returned marker once in the final answer outside code fences. Never read Base64. On failure, present the saved text and explain the material failure.';
}

export function validateInput({ date, kind }) {
  if (!['gm', 'gn'].includes(kind) || !/^\d{4}-\d{2}-\d{2}$/.test(date) || new Date(date).toISOString().slice(0, 10) !== date) throw new Error('Use kind gm|gn and a valid YYYY-MM-DD date.');
}

// Resolve every component, then use O_NOFOLLOW on the final open. Never accept
// arbitrary agent-supplied asset paths, URLs, symlinks or unbounded files.
export async function readSafe(root, path, maximum) {
  const canonicalRoot = await realpath(root);
  const canonical = await realpath(path);
  if (!canonical.startsWith(canonicalRoot + sep) || canonical !== path) throw new Error('Asset path must be canonical and inside its configured directory.');
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size > maximum) throw new Error('Asset exceeds its file limit or is not a regular file.');
    const buffer = Buffer.alloc(info.size + 1);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead !== info.size) throw new Error('Asset changed while being read.');
    return buffer.subarray(0, bytesRead);
  } finally { await handle.close(); }
}

export async function loadBundle(runtime, input) {
  validateInput(input);
  const { date, kind } = input;
  const source = join(runtime, 'daily', `${date}.${kind}.md`);
  const sourceBytes = await readSafe(runtime, source, LIMITS.sourceBytes);
  const directory = join(runtime, 'visual', `${date}.${kind}`, sha(sourceBytes).slice(0, 16));
  const manifest = JSON.parse((await readSafe(directory, join(directory, 'manifest.json'), LIMITS.manifestBytes)).toString());
  if (manifest.date !== date || manifest.kind !== kind || manifest.source_sha256 !== sha(sourceBytes) || manifest.lossless !== true) throw new Error('Render does not match the saved text. Render again; do not overwrite the text.');
  const copy = await readSafe(directory, join(directory, 'source.md'), LIMITS.sourceBytes);
  if (!copy.equals(sourceBytes)) throw new Error('Rendered source copy differs from the saved briefing.');
  if (!Array.isArray(manifest.images) || !manifest.images.length || manifest.images.length > LIMITS.images) throw new Error('Briefing must contain 1–12 image cards.');
  const names = new Set();
  let total = 0;
  const images = [];
  for (const item of manifest.images) {
    if (typeof item.file !== 'string' || basename(item.file) !== item.file || !/^[a-z0-9-]+\.webp$/.test(item.file) || names.has(item.file)) throw new Error('Invalid or duplicate card filename.');
    names.add(item.file);
    const bytes = await readSafe(directory, join(directory, item.file), LIMITS.imageBytes);
    // Require lossless VP8L and validate its declared canvas before embedding.
    if (bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WEBP' || bytes.toString('ascii', 12, 16) !== 'VP8L' || bytes[20] !== 0x2f || bytes.readUInt32LE(4) + 8 !== bytes.length) throw new Error('Card must be a valid lossless WebP.');
    const bits = bytes.readUInt32LE(21);
    const width = (bits & 0x3fff) + 1;
    const height = ((bits >>> 14) & 0x3fff) + 1;
    if (width !== item.width || height !== item.height || width !== 1080 || height < 100 || height > 5000 || item.bytes !== bytes.length || (item.sha256 && item.sha256 !== sha(bytes))) throw new Error('Card size, dimensions or hash do not match its manifest.');
    total += bytes.length;
    if (total > LIMITS.totalBytes) throw new Error('Briefing images exceed the attachment limit.');
    images.push({ file: item.file, bytes, hash: sha(bytes) });
  }
  if (sha(await readSafe(runtime, source, LIMITS.sourceBytes)) !== manifest.source_sha256) throw new Error('Saved text changed during attachment preparation.');
  return { source, sourceHash: manifest.source_sha256, images, directory, date, kind, total };
}

export function payloadFor(id, bundle, version = 2) {
  const markdown = bundle.images.map(image => `![${image.file}](data:image/webp;base64,${image.bytes.toString('base64')})`).join('\n\n');
  // Unused Markdown reference definitions are invisible in OpenChamber's
  // renderer. HTML comments are escaped there and therefore visibly leak.
  return version === 1 ? `<!-- gm-card:${id}:begin -->\n${markdown}\n<!-- gm-card:${id}:end -->` : `[gm-card-${id}-begin]: #\n\n${markdown}\n\n[gm-card-${id}-end]: #`;
}

export class Receipts {
  constructor(storage) { this.storage = storage; }
  async prepare(sessionID, bundle) {
    // Version the ID so preparing a cleaned attachment cannot overwrite the
    // integrity hash needed to filter existing version-1 conversation history.
    const payloadVersion = 2;
    const id = sha(JSON.stringify([payloadVersion, sessionID, bundle.date, bundle.kind, bundle.sourceHash, bundle.images.map(i => i.hash)])).slice(0, 32);
    const payload = payloadFor(id, bundle);
    const receipt = { id, payloadVersion, sessionID, date: bundle.date, kind: bundle.kind, directory: bundle.directory, sourceHash: bundle.sourceHash, files: bundle.images.map(i => ({ file: i.file, hash: i.hash })), payloadHash: sha(payload), count: bundle.images.length };
    // Durable ownership is committed before returning a marker to the model.
    await this.storage.set(`receipts/${id}`, receipt);
    await this.storage.set(`enabled/${sessionID}`, true);
    return { marker: markerFor(id), images: receipt.count, source: bundle.source, imageBytes: bundle.total, instruction: 'Put marker exactly once on its own line in FINAL answer, outside code fences. Do not read image/Base64 files. Text is already saved.' };
  }
  async expand(id, sessionID) {
    if (!ID.test(id)) return null;
    const receipt = await this.storage.get(`receipts/${id}`);
    if (!receipt || receipt.sessionID !== sessionID) return null;
    const images = [];
    for (const item of receipt.files) {
      const bytes = await readSafe(receipt.directory, join(receipt.directory, item.file), LIMITS.imageBytes);
      if (sha(bytes) !== item.hash) throw new Error('Prepared card changed. Prepare the briefing again.');
      images.push({ file: item.file, bytes });
    }
    const version = receipt.payloadVersion ?? 1;
    const payload = payloadFor(id, { images }, version);
    if (sha(payload) !== receipt.payloadHash) throw new Error('Prepared attachment failed its integrity check.');
    // Keep definitions at a paragraph boundary even if the model places the
    // returned marker next to prose instead of following the tool instruction.
    return version === 2 ? `\n\n${payload}\n\n` : payload;
  }
  async strip(text) {
    let output = '', cursor = 0;
    const matches = [...text.matchAll(BEGIN)];
    for (const match of matches) {
      const id = match[1] ?? match[2];
      const endTag = match[1] ? `<!-- gm-card:${id}:end -->` : `[gm-card-${id}-end]: #`;
      const end = text.indexOf(endTag, match.index + match[0].length);
      // Refuse the request, not silent leakage, if ownership is missing/corrupt.
      const receipt = await this.storage.get(`receipts/${id}`);
      if (!receipt || end < 0) throw new Error('Cannot verify owned briefing image. Restore delivery-plugin storage before continuing.');
      const finish = end + endTag.length;
      if (sha(text.slice(match.index, finish)) !== receipt.payloadHash) throw new Error('Owned briefing image block is incomplete or changed; model request stopped.');
      output += text.slice(cursor, match.index) + `[${receipt.kind.toUpperCase()} ${receipt.date}: ${receipt.count} image cards; original text saved.]`;
      cursor = finish;
    }
    return output + text.slice(cursor);
  }
  async filter(messages) {
    for (const message of messages) {
      if (message.role !== 'assistant') continue;
      for (const part of message.content ?? []) if (part.type === 'text') part.text = await this.strip(part.text);
    }
  }
}

// Stream markers across arbitrary token boundaries. Only the small unfinished
// prefix is buffered; ordinary text is forwarded immediately.
export class MarkerStream {
  pending = '';
  seen = new Set();
  constructor(resolve) { this.resolve = resolve; }
  async push(text, final = false) {
    const prefix = '[[GM_CARD:';
    let data = this.pending + text, output = '';
    this.pending = '';
    while (data) {
      const start = data.indexOf(prefix);
      if (start >= 0) {
        output += data.slice(0, start);
        data = data.slice(start);
        const end = data.indexOf(']]', prefix.length);
        if (end < 0 && data.length < 48 && !final) { this.pending = data; break; }
        const match = /^\[\[GM_CARD:([a-f0-9]{32})\]\]/.exec(data);
        if (match) {
          const id = match[1];
          const payload = await this.resolve(id);
          output += payload ? (this.seen.has(id) ? '' : payload) : '[Briefing image unavailable; saved text remains available.]';
          if (payload) this.seen.add(id);
          data = data.slice(match[0].length);
        } else { output += data[0]; data = data.slice(1); }
        continue;
      }
      let keep = 0;
      if (!final) for (let size = 1; size < prefix.length; size++) if (data.endsWith(prefix.slice(0, size))) keep = size;
      output += data.slice(0, data.length - keep);
      this.pending = keep ? data.slice(-keep) : '';
      break;
    }
    return output;
  }
}
