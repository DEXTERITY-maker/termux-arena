const $ = s => document.querySelector(s);
const messagesEl = $('#messages'), inputEl = $('#input'), modelEl = $('#model');
let chats = JSON.parse(localStorage.getItem('nimbus.chats') || '[]');
let currentId = null, controller = null;

const save = () => localStorage.setItem('nimbus.chats', JSON.stringify(chats));
const cur = () => chats.find(c => c.id === currentId);

function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function md(s){
  return esc(s)
    .replace(/```(\w*)\n([\s\S]*?)```/g,(m,l,c)=>`<pre><code>${c}</code></pre>`)
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
}

/* ---------- models ---------- */
async function loadModels(){
  try{
    const r = await fetch('/api/models'), d = await r.json();
    modelEl.innerHTML = d.models.map(m=>`<option value="${m.id}" data-d="${m.desc||''}">${m.name}</option>`).join('');
    const saved = localStorage.getItem('nimbus.model');
    if (saved && [...modelEl.options].some(o=>o.value===saved)) modelEl.value = saved;
    $('#keyState').textContent = d.hasKey ? '🔑 Ключ DeepSeek подключён' : '⚠️ Ключ не найден — добавьте DEEPSEEK_API_KEY в .env';
    showDesc();
  }catch(e){ $('#keyState').textContent = 'Сервер недоступен'; }
}
const showDesc = () => $('#modelDesc').textContent = modelEl.selectedOptions[0]?.dataset.d || '';
modelEl.onchange = () => { showDesc(); localStorage.setItem('nimbus.model', modelEl.value); };

/* ---------- chats ---------- */
function newChat(){
  currentId = Date.now().toString(36);
  chats.unshift({id:currentId, title:'Новый чат', messages:[]});
  save(); renderList(); render();
}
function renderList(){
  $('#chatList').innerHTML = chats.map(c=>
    `<div class="chat-item ${c.id===currentId?'active':''}" data-id="${c.id}">
      <span>💬 ${esc(c.title)}</span><b data-del="${c.id}">✕</b></div>`).join('');
  $('#chatList').querySelectorAll('.chat-item').forEach(el=>{
    el.onclick = e => {
      const del = e.target.dataset.del;
      if (del){ chats = chats.filter(c=>c.id!==del); if(currentId===del) currentId=chats[0]?.id||null;
        if(!currentId) newChat(); else {save();renderList();render();} return; }
      currentId = el.dataset.id; renderList(); render(); document.body.classList.remove('nav');
    };
  });
}
function render(){
  const c = cur();
  $('#title').textContent = c?.title || 'Новый чат';
  if (!c || !c.messages.length){
    messagesEl.innerHTML = `<div class="empty"><div class="empty-logo">☁</div><h1>Nimbus AI</h1>
      <p>Общайтесь с моделями DeepSeek. Выберите модель слева и задайте вопрос.</p>
      <div class="chips">
        <button class="chip">Объясни квантовую запутанность простыми словами</button>
        <button class="chip">Напиши bash-скрипт бэкапа папки</button>
        <button class="chip">Придумай план изучения Python на месяц</button>
      </div></div>`;
    bindChips(); return;
  }
  messagesEl.innerHTML = c.messages.map(m=>bubble(m)).join('');
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
function bubble(m){
  const think = m.reasoning ? `<details class="think"><summary>Рассуждения</summary>${esc(m.reasoning)}</details>` : '';
  return `<div class="msg ${m.role}">
    <div class="avatar">${m.role==='user'?'🧑':'☁'}</div>
    <div class="bubble"><div class="who">${m.role==='user'?'Вы':'Nimbus'}</div>
      ${think}<div class="content">${md(m.content||'')}</div></div></div>`;
}
function bindChips(){
  messagesEl.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{inputEl.value=b.textContent;send();});
}

/* ---------- send ---------- */
async function send(){
  const text = inputEl.value.trim();
  if (!text || controller) return;
  const c = cur();
  c.messages.push({role:'user', content:text});
  if (c.messages.length === 1) c.title = text.slice(0,40);
  inputEl.value=''; inputEl.style.height='auto';
  save(); renderList(); render();

  const holder = document.createElement('div');
  holder.innerHTML = bubble({role:'assistant', content:''});
  messagesEl.appendChild(holder.firstElementChild);
  const node = messagesEl.lastElementChild;
  const contentEl = node.querySelector('.content');
  contentEl.classList.add('cursor');
  messagesEl.scrollTop = messagesEl.scrollHeight;

  const sys = $('#system').value.trim();
  const msgs = (sys ? [{role:'system', content:sys}] : [])
    .concat(c.messages.map(m=>({role:m.role, content:m.content})));

  controller = new AbortController();
  $('#send').classList.add('stop'); $('#send').textContent='■';
  let content='', reasoning='';
  try{
    const r = await fetch('/api/chat', {method:'POST', signal:controller.signal,
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model:modelEl.value, messages:msgs, temperature:parseFloat($('#temp').value)})});
    if (!r.ok || !r.body){ const e = await r.json().catch(()=>({error:'Ошибка'}));
      contentEl.innerHTML = `<div class="err">${esc(e.error||'Ошибка')}</div>`; throw 0; }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf='';
    while(true){
      const {value, done} = await reader.read(); if (done) break;
      buf += dec.decode(value, {stream:true});
      const parts = buf.split('\n\n'); buf = parts.pop();
      for (const p of parts){
        const line = p.trim(); if (!line.startsWith('data:')) continue;
        const d = line.slice(5).trim(); if (d === '[DONE]') continue;
        try{ const j = JSON.parse(d);
          if (j.reasoning){ reasoning += j.reasoning;
            let det = node.querySelector('details.think');
            if (!det){ det = document.createElement('details'); det.className='think'; det.open=true;
              det.innerHTML='<summary>Рассуждения</summary><div></div>';
              node.querySelector('.bubble').insertBefore(det, contentEl); }
            det.lastElementChild.textContent = reasoning;
          }
          if (j.content){ content += j.content; contentEl.innerHTML = md(content); }
        }catch(_){}
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }
  }catch(e){ if (e && e.name === 'AbortError') content += '\n\n_(остановлено)_'; }
  finally{
    contentEl.classList.remove('cursor');
    controller = null; $('#send').classList.remove('stop'); $('#send').textContent='➤';
    if (content || reasoning){ c.messages.push({role:'assistant', content, reasoning}); save(); }
    const d = node.querySelector('details.think'); if (d) d.open = false;
  }
}

/* ---------- events ---------- */
$('#composer').onsubmit = e => { e.preventDefault(); controller ? controller.abort() : send(); };
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
inputEl.addEventListener('input', () => {
  inputEl.style.height='auto'; inputEl.style.height = Math.min(inputEl.scrollHeight,180)+'px';
});
$('#newChat').onclick = () => { newChat(); document.body.classList.remove('nav'); };
$('#clearBtn').onclick = () => { const c=cur(); if(c){c.messages=[];c.title='Новый чат';save();renderList();render();} };
$('#menuBtn').onclick = () => document.body.classList.toggle('nav');
$('#scrim').onclick = () => document.body.classList.remove('nav');
$('#temp').oninput = e => $('#tempVal').textContent = e.target.value;
$('#system').value = localStorage.getItem('nimbus.sys') || '';
$('#system').oninput = e => localStorage.setItem('nimbus.sys', e.target.value);

loadModels();
if (!chats.length) newChat(); else { currentId = chats[0].id; renderList(); render(); }
