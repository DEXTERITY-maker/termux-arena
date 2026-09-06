/* Nimbus AI — интерфейс чата. Логика без DOM вынесена в util.js. */
(function () {
  'use strict';
  var U = window.NimbusUtil;
  var $ = function (s) { return document.querySelector(s); };

  var messagesEl = $('#messages'), inputEl = $('#input'), modelEl = $('#model'),
      sendBtn = $('#send'), titleEl = $('#title');

  var STORE = 'nimbus.chats';
  var chats = U.normalizeChats(localStorage.getItem(STORE) || '[]');
  var currentId = null;
  var controller = null;      // активный AbortController или null
  var streaming = false;

  var SUGGESTIONS = [
    'Объясни квантовую запутанность простыми словами',
    'Напиши bash-скрипт бэкапа папки',
    'Придумай план изучения Python на месяц'
  ];

  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(chats)); }
    catch (e) {
      // переполнение квоты — сбрасываем самые старые чаты
      while (chats.length > 1) {
        chats.pop();
        try { localStorage.setItem(STORE, JSON.stringify(chats)); return; } catch (e2) { /* дальше */ }
      }
    }
  }
  function cur() {
    for (var i = 0; i < chats.length; i++) if (chats[i].id === currentId) return chats[i];
    return null;
  }

  /* ---------------- модели ---------------- */
  function loadModels() {
    return fetch('/api/models').then(function (r) { return r.json(); }).then(function (d) {
      var models = (d && d.models) || [];
      modelEl.innerHTML = '';
      models.forEach(function (m) {
        var o = document.createElement('option');
        o.value = m.id; o.textContent = m.name || m.id;
        o.dataset.d = m.desc || '';
        modelEl.appendChild(o);
      });
      var saved = localStorage.getItem('nimbus.model');
      if (saved) {
        for (var i = 0; i < modelEl.options.length; i++) {
          if (modelEl.options[i].value === saved) { modelEl.value = saved; break; }
        }
      }
      $('#keyState').textContent = d.hasKey
        ? '🔑 Ключ подключён · v' + (d.version || '') + (d.live ? ' · список моделей из API' : ' · встроенный список')
        : '⚠️ Ключ не найден — добавьте DEEPSEEK_API_KEY в .env и перезапустите сервер';
      showDesc();
    }).catch(function () {
      $('#keyState').textContent = '⚠️ Сервер Nimbus недоступен';
    });
  }
  function showDesc() {
    var o = modelEl.options[modelEl.selectedIndex];
    $('#modelDesc').textContent = o ? (o.dataset.d || '') : '';
    // у reasoner температура не применяется
    var reasoner = o && /reasoner/.test(o.value);
    $('#temp').disabled = !!reasoner;
    $('#tempRow').style.opacity = reasoner ? 0.45 : 1;
  }

  /* ---------------- рендер ---------------- */
  function newChat() {
    // не плодим пустые чаты
    var c = cur();
    if (c && !c.messages.length) { render(); return; }
    currentId = U.newId();
    chats.unshift({ id: currentId, title: 'Новый чат', messages: [] });
    save(); renderList(); render(); inputEl.focus();
  }

  function renderList() {
    var list = $('#chatList');
    list.innerHTML = '';
    chats.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'chat-item' + (c.id === currentId ? ' active' : '');
      var name = document.createElement('span');
      name.textContent = '💬 ' + c.title;
      var del = document.createElement('b');
      del.textContent = '✕'; del.title = 'Удалить чат';
      row.appendChild(name); row.appendChild(del);

      del.addEventListener('click', function (e) {
        e.stopPropagation();
        if (streaming && c.id === currentId) abort();
        chats = chats.filter(function (x) { return x.id !== c.id; });
        if (currentId === c.id) currentId = chats.length ? chats[0].id : null;
        save();
        if (!currentId) newChat(); else { renderList(); render(); }
      });
      row.addEventListener('click', function () {
        if (c.id === currentId) { closeNav(); return; }
        if (streaming) abort();
        currentId = c.id; renderList(); render(); closeNav();
      });
      list.appendChild(row);
    });
  }

  function render() {
    var c = cur();
    titleEl.textContent = c ? c.title : 'Новый чат';
    messagesEl.innerHTML = '';
    if (!c || !c.messages.length) { renderEmpty(); return; }
    c.messages.forEach(function (m) { messagesEl.appendChild(bubble(m)); });
    scroll(true);
  }

  function renderEmpty() {
    var wrap = document.createElement('div');
    wrap.className = 'empty';
    wrap.innerHTML = '<div class="empty-logo">☁</div><h1>Nimbus AI</h1>' +
      '<p>Общайтесь с моделями DeepSeek. Выберите модель слева и задайте вопрос.</p>';
    var chips = document.createElement('div');
    chips.className = 'chips';
    SUGGESTIONS.forEach(function (s) {
      var b = document.createElement('button');
      b.className = 'chip'; b.type = 'button'; b.textContent = s;
      b.addEventListener('click', function () { inputEl.value = s; autosize(); send(); });
      chips.appendChild(b);
    });
    wrap.appendChild(chips);
    messagesEl.appendChild(wrap);
  }

  function bubble(m) {
    var node = document.createElement('div');
    node.className = 'msg ' + m.role;
    var av = document.createElement('div');
    av.className = 'avatar'; av.textContent = m.role === 'user' ? '🧑' : '☁';
    var box = document.createElement('div');
    box.className = 'bubble';
    var who = document.createElement('div');
    who.className = 'who'; who.textContent = m.role === 'user' ? 'Вы' : 'Nimbus';
    box.appendChild(who);
    if (m.reasoning) box.appendChild(thinkBlock(m.reasoning, false));
    var content = document.createElement('div');
    content.className = 'content';
    if (m.role === 'user') content.textContent = m.content;
    else content.innerHTML = U.md(m.content);
    box.appendChild(content);
    node.appendChild(av); node.appendChild(box);
    return node;
  }

  function thinkBlock(text, open) {
    var d = document.createElement('details');
    d.className = 'think'; d.open = !!open;
    var s = document.createElement('summary'); s.textContent = 'Рассуждения';
    var body = document.createElement('div'); body.textContent = text;
    d.appendChild(s); d.appendChild(body);
    return d;
  }

  /* автопрокрутка только если пользователь у нижнего края */
  var pinned = true;
  messagesEl.addEventListener('scroll', function () {
    pinned = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
  });
  function scroll(force) {
    if (force || pinned) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  /* ---------------- отправка ---------------- */
  function setBusy(on) {
    streaming = on;
    sendBtn.classList.toggle('stop', on);
    sendBtn.textContent = on ? '■' : '➤';
    sendBtn.title = on ? 'Остановить' : 'Отправить';
    modelEl.disabled = on;
  }
  function abort() { if (controller) { controller.abort(); controller = null; } }

  function send() {
    if (streaming) return;
    var text = inputEl.value.trim();
    if (!text) return;
    var c = cur();
    if (!c) { newChat(); c = cur(); }

    var isFirst = c.messages.length === 0;
    c.messages.push({ role: 'user', content: text, reasoning: '' });
    if (isFirst) { c.title = U.titleFrom(text); titleEl.textContent = c.title; renderList(); }
    inputEl.value = ''; autosize(); save();

    if (isFirst) messagesEl.innerHTML = '';
    messagesEl.appendChild(bubble(c.messages[c.messages.length - 1]));

    var node = bubble({ role: 'assistant', content: '', reasoning: '' });
    var contentEl = node.querySelector('.content');
    contentEl.classList.add('cursor');
    messagesEl.appendChild(node);
    pinned = true; scroll(true);

    var chatId = c.id;      // ответ должен приземлиться в свой чат
    var body = U.buildRequest(c.messages, $('#system').value, modelEl.value,
                              $('#temp').value);
    controller = new AbortController();
    setBusy(true);
    stream(body, chatId, node, contentEl);
  }

  function stream(body, chatId, node, contentEl) {
    var content = '', reasoning = '', aborted = false, failed = false;
    var think = null;
    var parser = U.createSSEParser();

    fetch('/api/chat', {
      method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok || !r.body) {
        return r.json().catch(function () { return { error: 'HTTP ' + r.status }; })
          .then(function (e) { throw new Error(e.error || ('HTTP ' + r.status)); });
      }
      var reader = r.body.getReader(), dec = new TextDecoder();
      return (function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          parser.push(dec.decode(res.value, { stream: true })).forEach(apply);
          scroll();
          return pump();
        });
      })();
    }).catch(function (e) {
      if (e && e.name === 'AbortError') { aborted = true; return; }
      failed = true;
      var err = document.createElement('div');
      err.className = 'err'; err.textContent = '⚠️ ' + (e.message || 'Ошибка запроса');
      node.querySelector('.bubble').appendChild(err);
    }).then(function () {
      contentEl.classList.remove('cursor');
      controller = null; setBusy(false);
      if (think) think.open = false;
      if (aborted && content) content += '\n\n_(остановлено)_';

      var chat = null;
      for (var i = 0; i < chats.length; i++) if (chats[i].id === chatId) chat = chats[i];
      if (chat && (content || reasoning)) {
        chat.messages.push({ role: 'assistant', content: content, reasoning: reasoning });
        save();
      } else if (chat && failed) {
        // ответа нет — вернём вопрос в поле ввода, чтобы не потерять его
        var last = chat.messages[chat.messages.length - 1];
        if (last && last.role === 'user' && !inputEl.value) {
          inputEl.value = last.content; autosize();
          chat.messages.pop(); save(); renderList();
        }
      }
      if (chatId !== currentId) render();
      inputEl.focus();
    });

    function apply(ev) {
      if (ev.done) return;
      if (ev.error) { failed = true;
        var err = document.createElement('div');
        err.className = 'err'; err.textContent = '⚠️ ' + ev.error;
        node.querySelector('.bubble').appendChild(err); return; }
      if (ev.reasoning) {
        reasoning += ev.reasoning;
        if (!think) { think = thinkBlock('', true);
          node.querySelector('.bubble').insertBefore(think, contentEl); }
        think.lastElementChild.textContent = reasoning;
      }
      if (ev.content) { content += ev.content; contentEl.innerHTML = U.md(content); }
      if (ev.warning) {
        var w = document.createElement('div');
        w.className = 'err'; w.textContent = 'ℹ️ ' + ev.warning;
        node.querySelector('.bubble').appendChild(w);
      }
    }
  }

  /* ---------------- события ---------------- */
  function autosize() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + 'px';
  }
  function closeNav() { document.body.classList.remove('nav'); }

  $('#composer').addEventListener('submit', function (e) {
    e.preventDefault();
    if (streaming) abort(); else send();
  });
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  inputEl.addEventListener('input', autosize);
  modelEl.addEventListener('change', function () {
    showDesc(); localStorage.setItem('nimbus.model', modelEl.value);
  });
  $('#newChat').addEventListener('click', function () { newChat(); closeNav(); });
  $('#clearBtn').addEventListener('click', function () {
    var c = cur(); if (!c || !c.messages.length) return;
    if (!confirm('Очистить этот чат?')) return;
    if (streaming) abort();
    c.messages = []; c.title = 'Новый чат'; save(); renderList(); render();
  });
  $('#menuBtn').addEventListener('click', function () { document.body.classList.toggle('nav'); });
  $('#scrim').addEventListener('click', closeNav);
  $('#temp').addEventListener('input', function (e) {
    $('#tempVal').textContent = Number(e.target.value).toFixed(1);
    localStorage.setItem('nimbus.temp', e.target.value);
  });
  $('#system').addEventListener('input', function (e) {
    localStorage.setItem('nimbus.sys', e.target.value);
  });
  window.addEventListener('beforeunload', function (e) {
    if (streaming) { e.preventDefault(); e.returnValue = ''; }
  });

  /* ---------------- старт ---------------- */
  $('#system').value = localStorage.getItem('nimbus.sys') || '';
  var t = localStorage.getItem('nimbus.temp');
  if (t !== null) { $('#temp').value = t; $('#tempVal').textContent = Number(t).toFixed(1); }
  if (!chats.length) newChat();
  else { currentId = chats[0].id; renderList(); render(); }
  loadModels();
  autosize();
})();
