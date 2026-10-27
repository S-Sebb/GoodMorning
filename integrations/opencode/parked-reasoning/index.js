// OpenCode 2.1.4–2.2.0 lowers interrupted reasoning into text in model history.
// Change only that outgoing projection; keep the native session unchanged.
// DeepSeek declares reasoningField: retain same-model reasoning privately for
// its tool loop. Muse/Responses has no such field: omit interrupted reasoning,
// whose provider-bound state may no longer be replayable, rather than send text.
export function projectReasoning(messages, originals, model, retainReasoning) {
  const interrupted = new Map(originals.filter(message => message.type === 'assistant' && (
    message.error || message.content.some(part => part.type === 'reasoning'
      && part.time && part.time.completed === undefined)
  )).map(message => [message.id, message]));
  return messages.flatMap(message => {
    const original = interrupted.get(message.id);
    if (message.role !== 'assistant' || !original) return [message];
    const textParts = original.content.filter(part =>
      (part.type === 'text' || part.type === 'reasoning') && part.text !== '');
    const retain = retainReasoning && original.model.providerID === model.providerID
      && original.model.id === model.id;
    let index = 0;
    const content = message.content.flatMap(part => {
      if (part.type !== 'text') return [part];
      const source = textParts[index++];
      if (!source || source.text !== part.text) {
        throw new Error('Interrupted reasoning projection does not match the native message');
      }
      if (source.type !== 'reasoning') return [part];
      return retain ? [{type: 'reasoning', text: source.text}] : [];
    });
    return content.length ? [{...message, content}] : [];
  });
}

export default {
  id: 'goodmorning-parked-reasoning',
  async setup(context) {
    const project = async event => {
      const originals = await context.session.context({sessionID: event.sessionID});
      const models = (await context.model.list()).data;
      const model = models.find(item => item.providerID === event.model.providerID && item.id === event.model.id);
      event.messages = projectReasoning(event.messages, originals, event.model,
        Boolean(model?.compatibility?.reasoningField));
    };
    const hooks = await Promise.all(['context', 'compaction', 'generate', 'title'].map(name =>
      context.session.hook(name, project, {providerID: 'opencode-go'})));
    return () => Promise.all(hooks.map(hook => hook.dispose()));
  },
};
