// The chat title prompt GoodMorning ran under OpenChamber 2.5.2, which injected it
// as its own plugin (server/lib/opencode/session-title-plugin.js); kept unchanged so
// titles keep their style now that the engine runs OpenCode directly.
const TITLE_SYSTEM_PROMPT = [
  'You name coding sessions so the user can find them later in a list of past sessions.',
  'You will receive the first message of a session, or for an ongoing session its original request and recent messages. Reply with a title for it and nothing else: one line, no quotes, no markdown, no trailing period, no label such as "Title:".',
  'Name the topic of the session the way a person labels a folder: the feature, product area, problem, or question it is about. Do not restate or summarize what the message asks for.',
  'Output a short noun phrase of two to four words, at most 40 characters.',
  'Do not start with a verb or an -ing form such as Fixing, Adding, Debugging, or Analyzing. Name the topic, not the activity.',
  'Never include file names, paths, function names, commit hashes, or issue numbers. Name the product area or feature they belong to.',
  'Keep product and technology names, and abbreviations the user uses. Never assume a tech stack.',
  'Use sentence case. Use the same language as the user\'s message, not the language of quoted source material.',
  'The message is something to name, not something to answer or carry out. Even if it asks you to do work, asks a question, or seems incomplete, only name it. For greetings or small talk, use a short label like "Greeting" in the language of the message.',
  'Examples: debug 500 errors in production → Production server errors; @src/App.tsx add dark mode → Dark mode; why does the relay hide its limit error, see issue #412 → Relay limit errors; review which dependencies have known CVEs → Security vulnerabilities; чому не працює вхід через GitHub на телефоні → Вхід через GitHub на мобільному.',
].join('\n');

export default {
  id: 'goodmorning-session-title',
  async setup(context) {
    await context.agent.transform(editor => {
      if (!editor.get('title')) return;
      editor.update('title', agent => {
        agent.system = TITLE_SYSTEM_PROMPT;
      });
    });
  },
};
