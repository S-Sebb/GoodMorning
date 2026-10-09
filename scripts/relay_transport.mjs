import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';

const root = new URL('./vendor/openchamber-relay/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('manifest.json', root), 'utf8'));
for (const [name, expected] of Object.entries(manifest.sha256)) {
  const actual = createHash('sha256').update(readFileSync(new URL(name, root))).digest('hex');
  if (actual !== expected) throw new Error('Vendored relay integrity check failed');
}

// Keep upstream source unchanged. Resolve its TypeScript imports and replace
// only frontend diagnostics, which otherwise import the entire UI platform.
registerHooks({
  resolve(specifier, context, next) {
    if (context.parentURL?.startsWith(root.href)) {
      if (specifier === '../platform' || specifier === '../../../package.json') {
        return { url: new URL('relay_frontend_shim.mjs', import.meta.url).href, shortCircuit: true };
      }
      if (specifier.startsWith('./') && !specifier.endsWith('.ts')) {
        return next(`${specifier}.ts`, context);
      }
    }
    return next(specifier, context);
  },
});

export const { createRelayTunnelClient } = await import(new URL('tunnel-client.ts', root));
