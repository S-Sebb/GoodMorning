// Parse Markdown into a small DOM allowlist, never agent-supplied HTML.
const markdownEntities = document.createElement('textarea');
function markdownText(text) {
  markdownEntities.innerHTML = text.replaceAll('<', '&lt;');
  return markdownEntities.value;
}

function secretaryMarkdown(source) {
  const element = (tag, children) => {
    const node = document.createElement(tag);
    if (children) node.append(children);
    return node;
  };
  const render = tokens => {
    const fragment = document.createDocumentFragment();
    for (const token of tokens) {
      let node;
      switch (token.type) {
        case 'space': case 'def': continue;
        case 'heading': node = element('h' + token.depth, render(token.tokens)); break;
        case 'paragraph': node = element('p', render(token.tokens)); break;
        case 'strong': case 'em': case 'del':
          node = element(token.type, render(token.tokens)); break;
        case 'blockquote': node = element('blockquote', render(token.tokens)); break;
        case 'br': case 'hr': node = element(token.type); break;
        case 'code':
          node = element('pre', element('code', document.createTextNode(token.text)));
          node.tabIndex = 0;
          break;
        case 'codespan': node = element('code', document.createTextNode(token.text)); break;
        case 'list':
          node = element(token.ordered ? 'ol' : 'ul');
          if (token.ordered && token.start !== 1) node.start = token.start;
          for (const item of token.items) {
            const li = element('li', render(item.tokens));
            if (item.task) li.className = 'markdown-task';
            const checkbox = li.querySelector('input');
            if (item.task && checkbox) checkbox.setAttribute('aria-label', li.textContent);
            node.append(li);
          }
          break;
        case 'checkbox':
          node = element('input'); node.type = 'checkbox';
          node.disabled = true; node.checked = token.checked;
          break;
        case 'table': {
          node = element('div'); node.className = 'markdown-table'; node.tabIndex = 0;
          const table = element('table');
          const row = (cells, header = false) => {
            const tr = element('tr');
            cells.forEach((cell, index) => {
              const td = element(header ? 'th' : 'td', render(cell.tokens));
              if (header) td.scope = 'col';
              if (token.align[index]) td.style.textAlign = token.align[index];
              tr.append(td);
            });
            return tr;
          };
          const body = element('tbody');
          token.rows.forEach(cells => body.append(row(cells)));
          table.append(element('thead', row(token.header, true)), body); node.append(table);
          break;
        }
        case 'link': {
          const label = render(token.tokens);
          const href = markdownText(token.href);
          let url;
          try { url = new URL(href, location.href); } catch { /* Invalid links stay text. */ }
          if (!url || !['http:', 'https:', 'mailto:'].includes(url.protocol) || url.username || url.password) {
            node = label;
          } else {
            node = element('a', label); node.href = url.href;
            if (token.title) node.title = markdownText(token.title);
            if (url.origin !== location.origin) {
              node.target = '_blank'; node.rel = 'noopener noreferrer';
            }
          }
          break;
        }
        case 'text': case 'escape':
          node = token.tokens ? render(token.tokens) : document.createTextNode(markdownText(token.text));
          break;
        // Images keep their alternative text without fetching private or remote URLs.
        case 'image': node = document.createTextNode(markdownText(token.text)); break;
        default: node = document.createTextNode(token.raw || token.text || '');
      }
      fragment.append(node);
    }
    return fragment;
  };
  return render(marked.lexer(source, {gfm: true, breaks: true}));
}
