import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL('../assets/web/network.js', import.meta.url), 'utf8'), context);
const read = response => context.goodmorningJSON(response);

test('JSON success and application errors keep their original values', async () => {
  for (const value of [{saved: true}, {error: 'The queue is full'}]) {
    assert.equal(await read({status: 200, json: async () => value}), value);
  }
});

test('HTML errors produce useful messages instead of JSON parse failures', async () => {
  for (const [status, text] of [[429, 'Too many requests'], [401, 'sign in'], [502, 'temporarily unavailable'], [200, 'unreadable response']]) {
    await assert.rejects(read({status, json: async () => { throw new SyntaxError('Unexpected token <'); }}), error => {
      assert.equal(error.status, status);
      assert.ok(error.message.includes(text));
      assert.ok(!error.message.includes('Unexpected token'));
      return true;
    });
  }
});

test('malformed JSON objects are rejected and messages are translated at request time', async () => {
  for (const value of [null, 'invalid', 42]) {
    await assert.rejects(read({status: 200, json: async () => value}), /unreadable response/);
  }
  context.goodmorningT = key => 'Translated: ' + key;
  await assert.rejects(read({status: 429, json: async () => { throw new Error(); }}), /Translated: Too many requests/);
});
