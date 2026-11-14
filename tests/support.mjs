import { mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export const tempRoot = process.env.GM_TEST_TMPDIR || join(homedir(), 'scratch/GoodMorning/tests');
mkdirSync(tempRoot, { recursive: true });
