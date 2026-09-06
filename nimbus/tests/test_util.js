/* Тесты чистой логики фронтенда (util.js). Запуск: node nimbus/tests/test_util.js */
const assert = require('assert');
const U = require('../static/util.js');

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log('  ok  ' + name); }
  catch (e) { failed++; console.log('FAIL  ' + name + '\n      ' + e.message); }
}

console.log('esc / md');
t('экранирует html', () => assert.strictEqual(U.esc('<script>&"'), '&lt;script&gt;&amp;&quot;'));
t('null безопасен', () => assert.strictEqual(U.esc(null), ''));
t('xss в тексте не исполняется', () =>
  assert.ok(!U.md('<img src=x onerror=alert(1)>').includes('<img')));
t('код-блок сохраняется', () => {
  const h = U.md('```py\nprint("hi")\n```');
  assert.ok(h.includes('<pre><code data-lang="py">'));
  assert.ok(h.includes('print(&quot;hi&quot;)'));
});
t('** внутри кода не становится <b>', () => {
  const h = U.md('```\na ** b\n```');
  assert.ok(!h.includes('<b>'), h);
});
t('обратные кавычки внутри блока кода целы', () => {
  const h = U.md('```\nx = `y`\n```');
  assert.ok(!h.includes('<code>y</code>'));
});
t('незакрытый код-блок не ломает вывод', () => {
  const h = U.md('текст\n```js\nlet a=1;');
  assert.ok(h.includes('<pre><code'), h);
});
t('inline code', () => assert.ok(U.md('вот `ls -la` тут').includes('<code>ls -la</code>')));
t('жирный', () => assert.ok(U.md('это **важно**').includes('<b>важно</b>')));
t('курсив', () => assert.ok(U.md('это *да* тут').includes('<i>да</i>')));
t('заголовок', () => assert.ok(U.md('## Итог').includes('<b>Итог</b>')));
t('нет мусорных маркеров', () => assert.ok(!/\u0000/.test(U.md('```\na\n```\n`b` **c**'))));

console.log('titleFrom / newId');
t('обрезает длинное', () => {
  const s = U.titleFrom('я'.repeat(100));
  assert.ok(s.length <= 41 && s.endsWith('…'));
});
t('схлопывает пробелы', () => assert.strictEqual(U.titleFrom('  а\n\n б '), 'а б'));
t('пустое -> Новый чат', () => assert.strictEqual(U.titleFrom('   '), 'Новый чат'));
t('id уникальны подряд', () => {
  const s = new Set();
  for (let i = 0; i < 500; i++) s.add(U.newId());
  assert.strictEqual(s.size, 500);
});

console.log('buildRequest');
t('добавляет системный промпт', () => {
  const b = U.buildRequest([{ role: 'user', content: 'hi' }], 'ты бот', 'deepseek-chat', 0.5);
  assert.strictEqual(b.messages[0].role, 'system');
  assert.strictEqual(b.messages.length, 2);
});
t('пустой системный промпт не добавляется', () => {
  const b = U.buildRequest([{ role: 'user', content: 'hi' }], '   ', 'm', 1);
  assert.strictEqual(b.messages[0].role, 'user');
});
t('обрезает контекст', () => {
  const msgs = [];
  for (let i = 0; i < 200; i++) msgs.push({ role: i % 2 ? 'assistant' : 'user', content: 'm' + i });
  const b = U.buildRequest(msgs, '', 'm', 1);
  assert.strictEqual(b.messages.length, U.MAX_CONTEXT);
  assert.strictEqual(b.messages[b.messages.length - 1].content, 'm199');
});
t('не начинается с assistant после обрезки', () => {
  const msgs = [];
  for (let i = 0; i < 100; i++) msgs.push({ role: i % 2 ? 'user' : 'assistant', content: 'm' + i });
  const b = U.buildRequest(msgs, '', 'm', 1);
  assert.notStrictEqual(b.messages[0].role, 'assistant');
});
t('выбрасывает пустые реплики', () => {
  const b = U.buildRequest([{ role: 'user', content: '  ' }, { role: 'user', content: 'x' }], '', 'm', 1);
  assert.strictEqual(b.messages.length, 1);
});
t('температура ограничена', () => {
  assert.strictEqual(U.buildRequest([{ role: 'user', content: 'x' }], '', 'm', 9).temperature, 2);
  assert.strictEqual(U.buildRequest([{ role: 'user', content: 'x' }], '', 'm', -3).temperature, 0);
});
t('строковая температура из input работает', () =>
  assert.strictEqual(U.buildRequest([{ role: 'user', content: 'x' }], '', 'm', '1.3').temperature, 1.3));

console.log('SSE parser');
t('склеивает разорванные кадры', () => {
  const p = U.createSSEParser();
  assert.deepStrictEqual(p.push('data: {"content":"при'), []);
  const ev = p.push('вет"}\n\n');
  assert.strictEqual(ev[0].content, 'привет');
});
t('несколько событий за раз', () => {
  const p = U.createSSEParser();
  const ev = p.push('data: {"content":"a"}\n\ndata: {"content":"b"}\n\n');
  assert.strictEqual(ev.length, 2);
});
t('[DONE] распознаётся', () => {
  const p = U.createSSEParser();
  assert.ok(p.push('data: [DONE]\n\n')[0].done);
});
t('битый json пропускается', () => {
  const p = U.createSSEParser();
  assert.deepStrictEqual(p.push('data: {broken}\n\n'), []);
});
t('комментарии SSE игнорируются', () => {
  const p = U.createSSEParser();
  assert.deepStrictEqual(p.push(': ping\n\n'), []);
});
t('CRLF поддержан', () => {
  const p = U.createSSEParser();
  assert.strictEqual(p.push('data: {"content":"x"}\r\n\r\n')[0].content, 'x');
});
t('неполный хвост остаётся в буфере', () => {
  const p = U.createSSEParser();
  p.push('data: {"content":"x"}');
  assert.ok(p.rest().length > 0);
});

console.log('normalizeChats');
t('битый json -> []', () => assert.deepStrictEqual(U.normalizeChats('{{{'), []));
t('не-массив -> []', () => assert.deepStrictEqual(U.normalizeChats('{"a":1}'), []));
t('чистит мусорные сообщения', () => {
  const r = U.normalizeChats([{ id: 'a', title: 'T', messages: [
    { role: 'user', content: 'ok' }, { role: 'hacker', content: 'x' }, null, { role: 'user' }] }]);
  assert.strictEqual(r[0].messages.length, 1);
});
t('дедуплицирует id', () => {
  const r = U.normalizeChats([{ id: 'x', messages: [] }, { id: 'x', messages: [] }]);
  assert.strictEqual(r.length, 1);
});
t('ограничивает количество чатов', () => {
  const arr = [];
  for (let i = 0; i < 500; i++) arr.push({ id: 'c' + i, messages: [] });
  assert.strictEqual(U.normalizeChats(arr).length, U.MAX_CHATS);
});
t('восстанавливает отсутствующие поля', () => {
  const r = U.normalizeChats([{ messages: null }]);
  assert.ok(r[0].id && r[0].title === 'Новый чат' && Array.isArray(r[0].messages));
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
