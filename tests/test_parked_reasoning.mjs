import assert from 'node:assert/strict';
import test from 'node:test';
import plugin, {projectReasoning} from '../integrations/opencode/parked-reasoning/index.js';

const model = {providerID: 'opencode-go', id: 'synthetic'};
const call = {type: 'tool-call', id: 'call_question', name: 'question', input: {}};
const result = {role: 'tool', content: [{type: 'tool-result', id: 'call_question', resultType: 'error'}]};

function fixture(error = {type: 'aborted'}) {
  const original = {id: 'assistant_1', type: 'assistant', model, error, content: [
    {type: 'text', text: 'A real update.'},
    {type: 'reasoning', text: 'Private synthetic reasoning.', time: {completed: 1}},
    {type: 'tool', id: 'call_question'},
  ]};
  const projected = {id: original.id, role: 'assistant', metadata: {kept: true}, content: [
    {type: 'text', text: 'A real update.'},
    {type: 'text', text: 'Private synthetic reasoning.'}, call,
  ]};
  return {original, projected};
}

test('retains interrupted reasoning privately without changing real text or tool results', () => {
  const {original, projected} = fixture();
  const before = structuredClone(original);
  const actual = projectReasoning([projected, result], [original], model, true);
  assert.deepEqual(actual[0].content, [projected.content[0], {type: 'reasoning', text: original.content[1].text}, call]);
  assert.equal(actual[0].metadata, projected.metadata);
  assert.equal(actual[1], result);
  assert.deepEqual(original, before);
  assert.equal(projected.content[1].type, 'text');
});

test('drop projection omits only private reasoning', () => {
  const {original, projected} = fixture();
  assert.deepEqual(projectReasoning([projected, result], [original], model, false)[0].content,
    [projected.content[0], call]);
});

test('healthy reasoning and unrelated messages are left unchanged', () => {
  const {original, projected} = fixture(undefined);
  delete original.error;
  projected.content[1].type = 'reasoning';
  assert.equal(projectReasoning([projected], [original], model, true)[0], projected);
});

test('unfinished reasoning is protected even without a message error', () => {
  const {original, projected} = fixture();
  delete original.error;
  delete original.content[1].time.completed;
  assert.equal(projectReasoning([projected], [original], model, true)[0].content[1].type, 'reasoning');
});

test('a model switch drops interrupted reasoning instead of replaying provider-bound state', () => {
  const {original, projected} = fixture();
  assert.deepEqual(projectReasoning([projected], [original], {...model, id: 'other'}, true)[0].content,
    [projected.content[0], call]);
});

test('a changed projection fails before dispatch instead of guessing which text to remove', () => {
  const {original, projected} = fixture();
  projected.content[1].text = 'Changed by another plugin.';
  assert.throws(() => projectReasoning([projected], [original], model, false), /does not match/);
});

test('session hooks select private replay only for a declared reasoning field', async () => {
  for (const compatibility of [{reasoningField: 'reasoning_content'}, undefined]) {
    const {original, projected} = fixture();
    const hooks = new Map();
    let disposed = 0;
    const cleanup = await plugin.setup({
      session: {
        context: async ({sessionID}) => {
          assert.equal(sessionID, 'session_1');
          return [original];
        },
        hook: async (name, callback, options) => {
          assert.deepEqual(options, {providerID: 'opencode-go'});
          hooks.set(name, callback);
          return {dispose: async () => { disposed++; }};
        },
      },
      model: {list: async () => ({data: [{...model, compatibility}]})},
    });
    assert.deepEqual([...hooks.keys()], ['context', 'compaction', 'generate', 'title']);
    for (const callback of hooks.values()) {
      const event = {sessionID: 'session_1', model, messages: [projected, result]};
      await callback(event);
      assert.deepEqual(event.messages[0].content,
        compatibility ? [projected.content[0], {type: 'reasoning', text: original.content[1].text}, call]
          : [projected.content[0], call]);
      assert.equal(event.messages[1], result);
    }
    await cleanup();
    assert.equal(disposed, 4);
  }
});
