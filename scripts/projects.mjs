#!/usr/bin/env node
import { main } from '../integrations/projects/index.mjs';

await main();
// Native WebSocket close timers must not keep a finished CLI alive.
await new Promise(resolve => process.stdout.write('', resolve));
process.exit(process.exitCode ?? 0);
