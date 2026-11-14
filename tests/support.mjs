import { mkdirSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const root = process.env.GM_TEST_TMPDIR || join(homedir(), 'scratch/GoodMorning/tests');
mkdirSync(root, { recursive: true });
// Resolved: ~/scratch is a symlink, and runtimes refuse symlinked paths.
export const tempRoot = realpathSync(root);
