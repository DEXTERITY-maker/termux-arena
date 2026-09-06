/* Nimbus AI — чистые функции без DOM. Используются приложением и тестами. */
(function (root) {
  'use strict';

  var MAX_CONTEXT = 40;      // сколько последних реплик уходит в модель
  var MAX_CHATS = 100;       // потолок истории в localStorage

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* Мини-Markdown: блоки кода вырезаются ПЕРВЫМИ, чтобы ** и ` внутри них
     не превращались в разметку. Всё экранируется — XSS невозможен. */
  function md(src) {
    var text = String(src == null ? '' : src);
    var blocks = [];
    text = text.replace(/```[ \t]*([\w+-]*)[ \t]*\r?\n?([\s\S]*?)(?:```|$)/g,
      function (m, lang, code) {
        blocks.push('<pre><code data-lang="' + esc(lang) + '">' + esc(code.replace(/\n$/, '')) + '</code></pre>');
        return '\u0000B' + (blocks.length - 1) + '\u0000';
      });

    var inline = [];
    text = text.replace(/`([^`\n]+)`/g, function (m, code) {
      inline.push('<code>' + esc(code) + '</code>');
      return '\u0000I' + (inline.length - 1) + '\u0000';
    });

    text = esc(text)
      .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?]|$)/g, '$1<i>$2</i>')
      .replace(/^### (.+)$/gm, '<b>$1</b>')
      .replace(/^## (.+)$/gm, '<b>$1</b>')
      .replace(/^# (.+)$/gm, '<b>$1</b>');

    return text
      .replace(/\u0000I(\d+)\u0000/g, function (m, i) { return inline[+i]; })
      .replace(/\u0000B(\d+)\u0000/g, function (m, i) { return blocks[+i]; });
  }

  /* Заголовок чата из первого сообщения */
  function titleFrom(text) {
    var t = String(text || '').replace(/\s+/g, ' ').trim();
    if (!t) return 'Новый чат';
    return t.length > 40 ? t.slice(0, 40).trimEnd() + '…' : t;
  }

  /* Уникальный id даже при нескольких вызовах в одну миллисекунду */
  var seq = 0;
  function newId() {
    seq = (seq + 1) % 1296;
    return Date.now().toString(36) + '-' + seq.toString(36);
  }

  /* Тело запроса к /api/chat: системный промпт + хвост истории */
  function buildRequest(messages, systemPrompt, model, temperature) {
    var out = [];
    var sys = String(systemPrompt || '').trim();
    if (sys) out.push({ role: 'system', content: sys });

    var tail = (messages || [])
      .filter(function (m) { return m && m.content && String(m.content).trim(); })
      .slice(-MAX_CONTEXT)
      .map(function (m) { return { role: m.role, content: String(m.content) }; });

    // модель не должна получать историю, начинающуюся с ответа ассистента
    while (tail.length && tail[0].role === 'assistant') tail.shift();

    var body = { model: model || 'deepseek-chat', messages: out.concat(tail) };
    var t = Number(temperature);
    if (isFinite(t)) body.temperature = Math.min(Math.max(t, 0), 2);
    return body;
  }

  /* Инкрементальный парсер SSE: скармливаем куски, получаем события */
  function createSSEParser() {
    var buf = '';
    return {
      push: function (chunk) {
        buf += chunk;
        var parts = buf.split(/\r?\n\r?\n/);
        buf = parts.pop();
        var events = [];
        for (var i = 0; i < parts.length; i++) {
          var data = parts[i].split(/\r?\n/)
            .filter(function (l) { return l.indexOf('data:') === 0; })
            .map(function (l) { return l.slice(5).trim(); })
            .join('\n');
          if (!data) continue;
          if (data === '[DONE]') { events.push({ done: true }); continue; }
          try { events.push(JSON.parse(data)); } catch (e) { /* битый кадр */ }
        }
        return events;
      },
      rest: function () { return buf; }
    };
  }

  /* Санитайзер загруженной из localStorage истории */
  function normalizeChats(raw) {
    var arr;
    try { arr = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { return []; }
    if (!Array.isArray(arr)) return [];
    var seen = {};
    var out = [];
    for (var i = 0; i < arr.length && out.length < MAX_CHATS; i++) {
      var c = arr[i];
      if (!c || typeof c !== 'object') continue;
      var id = typeof c.id === 'string' && c.id ? c.id : newId();
      if (seen[id]) continue;
      seen[id] = 1;
      var msgs = Array.isArray(c.messages) ? c.messages.filter(function (m) {
        return m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string';
      }).map(function (m) {
        return { role: m.role, content: m.content,
                 reasoning: typeof m.reasoning === 'string' ? m.reasoning : '' };
      }) : [];
      out.push({ id: id, title: typeof c.title === 'string' && c.title ? c.title : 'Новый чат',
                 messages: msgs });
    }
    return out;
  }

  var api = { esc: esc, md: md, titleFrom: titleFrom, newId: newId,
              buildRequest: buildRequest, createSSEParser: createSSEParser,
              normalizeChats: normalizeChats, MAX_CONTEXT: MAX_CONTEXT, MAX_CHATS: MAX_CHATS };

  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.NimbusUtil = api;
})(typeof self !== 'undefined' ? self : this);
