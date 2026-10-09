import { existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';

export const tempRoot = process.env.GM_TEST_TMPDIR || (existsSync('/tmp/opencode') ? '/tmp/opencode' : tmpdir());
mkdirSync(tempRoot, { recursive: true });
