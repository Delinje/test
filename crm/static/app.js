const app=document.querySelector('#app');let state,orders=[],view='home',branch='',query='',filter='all',current,tab='info';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rub=v=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:2}).format((v||0)/100);
const date=v=>v?new Date(v.includes(' ') ? v.replace(' ','T')+'Z':v).toLocaleString('ru-RU'):'—';
const done=s=>['Выдан','Выдан без ремонта','Передан на склад'].includes(s);const ready=s=>['Готов к выдаче','Без ремонта','Уведомить о готовности'].includes(s);
const badge=s=>`<span class="badge ${done(s)?'done':s.includes('Ждем')||s.includes('Ожида')?'wait':s.includes('Ремонт')||s.includes('Диагност')?'repair':''}">${esc(s)}</span>`;
async function api(path,data){let r=await fetch('/api/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});let j=await r.json();if(!r.ok)throw Error(j.error||'Ошибка запроса');return j}
function toast(t){let x=document.querySelector('#toast');x.textContent=t;x.style.display='block';clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>x.style.display='none',5000)}
const field=(name,title,type='text',value='',required=false)=>`<label>${title}<input name="${name}" type="${type}" ${type==='number'?`step="${['price','estimate','amount','unit_cost'].includes(name)?'0.01':'1'}" min="${name==='quantity'?'1':'0'}"`:''} value="${esc(value)}" ${required?'required':''}></label>`;
const select=(name,title,values,value='')=>`<label>${title}<select name="${name}" aria-label="${esc(title)}">${values.map(x=>`<option value="${esc(x.id??x)}" ${String(x.id??x)===String(value)?'selected':''}>${esc(x.name??x)}</option>`).join('')}</select></label>`;
function maskPhone(value){
 let d=String(value||'').replace(/\D/g,'');
 if(d.startsWith('7')||d.startsWith('8'))d=d.slice(1);
 d=d.slice(0,10);
 if(!d)return '+7 (';
 let out='+7 ('+d.slice(0,3);
 if(d.length>=3)out+=') ';
 if(d.length>3)out+=d.slice(3,6);
 if(d.length>6)out+='-'+d.slice(6,8);
 if(d.length>8)out+='-'+d.slice(8,10);
 return out;
}
function bindRussianPhone(input){
 input.placeholder='+7 (___) ___-__-__';input.maxLength=18;input.inputMode='tel';input.pattern='\\+7 \\([0-9]{3}\\) [0-9]{3}-[0-9]{2}-[0-9]{2}';
 input.addEventListener('input',()=>{
  const before=input.value,position=input.selectionStart,count=(before.slice(0,position).match(/\d/g)||[]).length;
  input.value=maskPhone(before);let seen=0,caret=input.value.length;
  for(let i=0;i<input.value.length;i++)if(/\d/.test(input.value[i])&&++seen===count){caret=i+1;break}
  if(position===before.length)caret=input.value.length;
  input.setSelectionRange(Math.max(4,caret),Math.max(4,caret));
 });
 input.addEventListener('beforeinput',e=>{
  if(!['deleteContentBackward','deleteContentForward'].includes(e.inputType)||input.selectionStart!==input.selectionEnd)return;
  let pos=input.selectionStart,index=e.inputType==='deleteContentBackward'?pos-1:pos;
  if(index<4)return;
  if(/\d/.test(input.value[index]||''))return;
  const direction=e.inputType==='deleteContentBackward'?-1:1;
  while(index>=4&&index<input.value.length&&!/\d/.test(input.value[index]))index+=direction;
  if(index<4||index>=input.value.length)return;
  e.preventDefault();input.value=input.value.slice(0,index)+input.value.slice(index+1);input.setSelectionRange(index,index);input.dispatchEvent(new Event('input'));
 });
 input.addEventListener('blur',()=>{if(input.value==='+7 (')input.value=''});
}
function preventOrderAutofill(form){
 if(!form)return;form.autocomplete='off';
 form.querySelectorAll('input,textarea').forEach(el=>{el.autocomplete='off';el.setAttribute('data-1p-ignore','true');el.setAttribute('data-lpignore','true');el.setAttribute('data-form-type','other')});
}
function checkboxSuggestions(input,provider,onSelect){
 const box=document.createElement('div');box.className='suggestion-list';box.hidden=true;input.after(box);input.autocomplete='off';input.setAttribute('aria-expanded','false');
 let timer,revision=0;
 const hide=()=>{box.hidden=true;input.setAttribute('aria-expanded','false')};
 input.addEventListener('input',()=>{
  clearTimeout(timer);const term=input.value.trim(),version=++revision;hide();
  if(term.length<2)return;
  timer=setTimeout(async()=>{try{
   const options=await provider(term);if(version!==revision||!input.isConnected)return;
   box.innerHTML=options.slice(0,20).map((x,i)=>`<label class="suggestion-item"><input type="checkbox" data-option="${i}"><span>${esc(x.label??x.value)}</span></label>`).join('');
   box.hidden=!options.length;input.setAttribute('aria-expanded',String(!!options.length));
   box.querySelectorAll('input').forEach(el=>el.onchange=()=>{if(el.checked){onSelect(options[Number(el.dataset.option)]);revision++;hide()}});
  }catch(e){toast(e.message)}},180)
 });
 input.addEventListener('keydown',e=>{if(e.key==='Escape'){revision++;hide()}});
 input.addEventListener('focusout',()=>setTimeout(()=>{if(!box.contains(document.activeElement))hide()},180));
 return box;
}
const matchingOptions=(rows,term)=>rows.filter(x=>(x.value??x.name??'').toLocaleLowerCase('ru').includes(term.toLocaleLowerCase('ru')));
function decorateDbSelects(root){
 if(!root)return;
 root.querySelectorAll('select').forEach(select=>{
  if(!['branch_id','master_id','item_id','stock_id','group_id'].includes(select.name)||select.dataset.suggested)return;
  select.dataset.suggested='1';const title=select.getAttribute('aria-label')||'Выбор';
  const input=document.createElement('input');input.type='text';input.className='db-picker';input.autocomplete='off';input.placeholder='Начните вводить…';input.setAttribute('aria-label',title);
  const initial=Array.from(select.options).find(o=>o.selected&&o.value);input.value=initial?.textContent||'';
  select.hidden=true;select.removeAttribute('required');select.after(input);
  input.addEventListener('input',()=>{select.value=''});
  select.addEventListener('change',()=>{input.value=select.selectedOptions[0]?.value?select.selectedOptions[0].textContent:''});
  checkboxSuggestions(input,term=>matchingOptions(Array.from(select.options).filter(o=>o.value).map(o=>({value:o.textContent,id:o.value})),term),option=>{select.value=option.id;input.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}))});
 });
}
function formBind(id,fn){document.getElementById(id)?.addEventListener('submit',async e=>{e.preventDefault();let button=e.target.querySelector('[type=submit]');if(button)button.disabled=true;try{await fn(Object.fromEntries(new FormData(e.target)),e.target)}catch(err){toast(err.message)}finally{if(button)button.disabled=false}})}
async function boot(){try{let s=await api('setup');if(s.required)return auth(true);await load()}catch(e){auth(false)}}
function auth(setup){app.innerHTML=`<section class="auth"><h1>◈ Контур ремонта</h1><p>${setup?'Создайте учётную запись владельца компании':'Войдите в рабочее пространство'}</p><form id="auth">${setup?field('name','Ваше имя','text','',true)+field('branch','Первый филиал','text','Основной сервис',true):''}${field('email','Email','email','',true)}${field('password',setup?'Пароль — минимум 12 символов':'Пароль','password','',true)}<button class="primary" type="submit">${setup?'Создать компанию':'Войти'}</button><small class="muted">Ремонты · Филиалы · Команда</small></form></section>`;formBind('auth',async d=>{if(setup)await api('setup',d);await api('login',{email:d.email,password:d.password});await load()})}
async function load(){state=await api('state');orders=await api('orders');render()}
function render(){let owner=state.user.role==='owner';app.innerHTML=`<div class="layout"><aside><h2>◈ Контур ремонта</h2><button data-view="home" class="${view==='home'?'active':''}">⌂ Главная</button><button data-view="orders" class="${view==='orders'?'active':''}">▤ Заказы</button><button data-view="works" class="${view==='works'?'active':''}">⚒ База работ</button><button data-view="stock" class="${view==='stock'?'active':''}">▦ Склад запчастей</button><button data-view="clients" class="${view==='clients'?'active':''}">♙ Клиенты</button>${owner?`<button data-view="team" class="${view==='team'?'active':''}">♧ Сотрудники</button><button data-view="branches" class="${view==='branches'?'active':''}">⌂ Филиалы</button>`:''}<div class="profile">${esc(state.user.name)}<br><small>${{owner:'Владелец',manager:'Приёмщик',master:'Мастер'}[state.user.role]}</small></div><button id="logout">Выйти</button></aside><main id="main"></main></div>`;document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;render()});document.querySelector('#logout').onclick=async()=>{await api('logout',{});auth(false)};if(view==='home')renderDashboard();if(view==='works')renderWorks();if(view==='stock')renderStock();if(view==='orders')renderOrders();if(view==='clients')renderClients();if(view==='team')renderTeam();if(view==='branches')renderBranches()}
let orderMaster='',orderOverdue=false,orderFiltersOpen=false;
function orderDeadline(o){
 if(!o.deadline)return '<span class="muted">—</span>';
 const left=new Date(o.deadline).getTime()-Date.now(),days=Math.ceil(Math.abs(left)/86400000);
 return `<span class="deadline ${left<0&&!done(o.status)?'late':''}">${done(o.status)?'Завершён':left<0?'Просрочен · '+days+' дн.':days===0?'Сегодня':'Осталось '+days+' дн.'}</span><small>${date(o.deadline)}</small>`;
}
function renderOrders(){
 const scoped=orders.filter(o=>!branch||String(o.branch_id)===branch);
 const matches=(o,k)=>k==='all'||k==='done'&&done(o.status)||k==='ready'&&ready(o.status)||k==='work'&&!done(o.status)&&!ready(o.status);
 const list=scoped.filter(o=>(!query||[o.id,o.client,o.phone,o.device,o.serial,o.fault].join(' ').toLowerCase().includes(query.toLowerCase()))&&matches(o,filter)&&(!orderMaster||String(o.master_id)===orderMaster)&&(!orderOverdue||o.deadline&&!done(o.status)&&new Date(o.deadline)<new Date()));
 document.querySelector('#main').innerHTML=`<section class="orders-page"><header><h1>Заказы <span class="location-title">${esc(state.branches.find(b=>String(b.id)===branch)?.name||'Все филиалы')}</span></h1></header><div class="orders-toolbar">${state.user.role!=='master'?'<button class="primary" id="new">＋ Создать</button>':''}<input id="search" aria-label="Поиск заказов" placeholder="Поиск по заказам…" value="${esc(query)}"><div class="order-filter-tabs">${[['all','Все заказы'],['work','В работе'],['ready','Готовые'],['done','Выданные']].map(([k,t])=>`<button data-filter="${k}" class="${filter===k?'active':''}">${t}${k==='all'?'':` <span>${scoped.filter(o=>matches(o,k)).length}</span>`}</button>`).join('')}</div><button id="toggleOrderFilters" aria-expanded="${orderFiltersOpen}">☷ Фильтры</button></div><div class="orders-filter-panel" ${orderFiltersOpen?'':'hidden'}><label>Филиал<select id="branch"><option value="">Все доступные филиалы</option>${state.branches.map(b=>`<option value="${b.id}" ${branch===String(b.id)?'selected':''}>${esc(b.name)}</option>`).join('')}</select></label>${select('orderMaster','Основной мастер',[{id:'',name:'Все мастера'},...state.users],orderMaster)}<label class="checkbox-label"><input id="onlyOverdue" type="checkbox" ${orderOverdue?'checked':''}> Только просроченные</label><button id="resetOrderFilters">Сбросить</button></div><div class="tablewrap orders-table"><table><thead><tr><th>Заказ</th><th>Статус</th><th>Крайний срок</th><th>Мастер / создан</th><th>Устройство</th><th>Неисправность</th><th>Клиент</th><th class="money-cell">Сумма</th></tr></thead><tbody>${list.map(o=>`<tr data-id="${o.id}" tabindex="0" aria-label="Открыть заказ Р-${o.id}"><td><b class="order-number">Р-${o.id}</b><small>${esc(o.branch_name)}</small></td><td>${badge(o.status)}</td><td>${orderDeadline(o)}</td><td>${esc(o.master_name||'Не назначен')}<small>${date(o.created)}</small></td><td>${esc(o.device)}</td><td>${esc(o.fault)}</td><td><span class="client-name">${esc(o.client)}</span><small>${esc(o.phone)}</small></td><td class="money-cell"><b>${rub(o.total)}</b><small>Внесено ${rub(o.paid)}</small></td></tr>`).join('')}</tbody></table>${!list.length?'<div class="empty">Заказы не найдены. Измените фильтры или создайте новый заказ.</div>':''}</div><footer class="orders-list-footer"><span>Всего заказов: <b>${list.length}</b></span><div><span class="legend-dot new"></span>Новые ${scoped.filter(o=>o.status==='Новый'||o.status==='Ожидается прием').length}<span class="legend-dot repair"></span>В работе ${scoped.filter(o=>matches(o,'work')).length}<span class="legend-dot ready"></span>Готовые ${scoped.filter(o=>ready(o.status)).length}<span class="legend-dot done"></span>Выданные ${scoped.filter(o=>done(o.status)).length}</div></footer></section>`;
 document.querySelector('#new')?.addEventListener('click',newOrder);
 document.querySelector('#search').oninput=e=>{query=e.target.value;const pos=e.target.selectionStart;renderOrders();const el=document.querySelector('#search');el.focus();el.setSelectionRange(pos,pos)};
 document.querySelector('#branch').onchange=e=>{branch=e.target.value;renderOrders()};document.querySelector('[name="orderMaster"]').onchange=e=>{orderMaster=e.target.value;renderOrders()};document.querySelector('#onlyOverdue').onchange=e=>{orderOverdue=e.target.checked;renderOrders()};document.querySelector('#toggleOrderFilters').onclick=()=>{orderFiltersOpen=!orderFiltersOpen;renderOrders()};document.querySelector('#resetOrderFilters').onclick=()=>{branch='';orderMaster='';orderOverdue=false;renderOrders()};
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;renderOrders()});document.querySelectorAll('[data-id]').forEach(r=>{r.onclick=()=>openOrder(r.dataset.id);r.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();openOrder(r.dataset.id)}}});
}
function modal(title,html){document.querySelector('.overlay')?.remove();let el=document.createElement('div');el.className='overlay';el.innerHTML=`<section class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2><button id="close">✕ Закрыть</button></header>${html}</section>`;app.append(el);document.querySelector('#close').onclick=()=>el.remove();el.onclick=e=>{if(e.target===el)el.remove()}}
async function newOrder(){
 if(!state.branches.length)return toast('Сначала создайте филиал');let catalog;
 try{catalog=await api('catalog')}catch(e){toast(e.message);return}
 const reusable=(kind,title,required=false)=>`<div class="reusable"><label>${title}<input name="${kind}" maxlength="300" ${required?'required':''} autocomplete="off" placeholder="Начните вводить…"></label><button type="button" data-save="${kind}">＋ В справочник</button></div>`;
 const tags=(kind,title)=>`<div class="full"><label>${title}</label><div class="taglist" id="${kind}Tags"></div><div class="row taginput"><label class="grow">Добавить вариант<input id="${kind}Input" maxlength="300" autocomplete="off" placeholder="Начните вводить или укажите новый вариант"></label><button type="button" data-tag="${kind}">＋ Добавить</button></div><input type="hidden" name="${kind}"></div>`;
 modal('Новый заказ',`<form id="orderForm" class="stack" autocomplete="off"><section class="panel grid">${select('branch_id','Филиал',state.branches,branch)}${select('master_id','Основной мастер',[{id:'',name:'Не назначен'},...state.users.filter(u=>u.active)])}<h3 class="full">Клиент</h3>${field('client','ФИО *','text','',true)}${field('phone','Телефон *','tel','',true)}<small class="muted full">Начните вводить фамилию или телефон. Если клиент найден, отметьте его чекбоксом — заполнятся оба поля.</small><h3 class="full">Устройство</h3>${reusable('brand','Марка')}${reusable('device','Модель устройства *',true)}${field('device_serial_number','IMEI / серийный номер *','text','',true)}${field('screen_access_code','Пароль устройства *','text','',true)}${tags('appearance','Внешний вид *')}${reusable('equipment','Комплектация *',true)}${tags('fault','Неисправность *')}<small class="muted full">Если пароля или комплектации нет, укажите «нет». Для ПК вместо IMEI укажите серийный номер. Новые варианты сохраняются в базе.</small>${field('estimate','Ориентировочная стоимость, ₽','number','0')}${field('deadline','Крайний срок','datetime-local')}<label class="full">Комментарий<textarea name="comment"></textarea></label></section><button class="primary" type="submit">Создать заказ</button></form>`);
 const form=document.querySelector('#orderForm'),selected={appearance:[],fault:[]};preventOrderAutofill(form);bindRussianPhone(form.elements.phone);decorateDbSelects(form);
 const normalize=v=>v.trim().replace(/\s+/g,' ');
 async function save(kind,value){catalog=await api('catalog',{kind,value})}
 function drawTags(kind){form.elements[kind].value=selected[kind].join('; ');const list=document.getElementById(kind+'Tags');list.innerHTML=selected[kind].map((v,i)=>`<button type="button" class="chip" data-index="${i}" aria-label="Удалить ${esc(v)}">${esc(v)} ×</button>`).join('');list.querySelectorAll('button').forEach(b=>b.onclick=()=>{selected[kind].splice(Number(b.dataset.index),1);drawTags(kind)})}
 function chooseTag(kind,value){if(!selected[kind].some(v=>v.toLocaleLowerCase('ru')===value.toLocaleLowerCase('ru')))selected[kind].push(value);drawTags(kind);document.getElementById(kind+'Input').value=''}
 async function addTag(kind){const input=document.getElementById(kind+'Input'),value=normalize(input.value);if(!value)return;if(value.includes(';'))throw Error('Добавляйте каждый вариант отдельно');await save(kind,value);chooseTag(kind,value)}
 for(const kind of ['brand','device','equipment'])checkboxSuggestions(form.elements[kind],term=>matchingOptions(catalog.filter(x=>x.kind===kind),term),option=>{form.elements[kind].value=option.value});
 checkboxSuggestions(form.elements.device_serial_number,term=>{
  const unique=new Map();orders.filter(o=>o.serial&&o.serial.toLocaleLowerCase('ru').includes(term.toLocaleLowerCase('ru'))).forEach(o=>{if(!unique.has(o.serial))unique.set(o.serial,{...o,label:o.serial+' · '+o.device})});return [...unique.values()];
 },device=>{form.elements.device_serial_number.value=device.serial;form.elements.device.value=device.device;form.elements.brand.value=device.brand||''});
 for(const kind of ['appearance','fault']){
  checkboxSuggestions(document.getElementById(kind+'Input'),term=>matchingOptions(catalog.filter(x=>x.kind===kind),term),option=>chooseTag(kind,option.value));
  const button=form.querySelector(`[data-tag="${kind}"]`);button.onclick=async()=>{try{await addTag(kind)}catch(e){toast(e.message)}};document.getElementById(kind+'Input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();button.click()}};
 }
 form.querySelectorAll('[data-save]').forEach(button=>button.onclick=async()=>{try{await save(button.dataset.save,normalize(form.elements[button.dataset.save].value));toast('Вариант сохранён')}catch(e){toast(e.message)}});
 for(const key of ['client','phone'])checkboxSuggestions(form.elements[key],async term=>{
  if(key==='phone'&&term.replace(/\D/g,'').length<4)return [];
  const clients=await api('clients?q='+encodeURIComponent(term));return clients.map(c=>({...c,label:c.name+' · '+c.phone}));
 },client=>{form.elements.client.value=client.name;form.elements.phone.value=maskPhone(client.phone)});
 formBind('orderForm',async()=>{for(const kind of ['appearance','fault'])await addTag(kind);if(!selected.appearance.length||!selected.fault.length)throw Error('Добавьте внешний вид и неисправность');const d=Object.fromEntries(new FormData(form));d.serial=d.device_serial_number;d.device_password=d.screen_access_code;const r=await api('orders',d);await load();tab='info';await openOrder(r.id);toast('Заказ создан')});
}
async function openOrder(id){
 try{
  const [detail,stock,works]=await Promise.all([api('orders/'+id),api('stock'),api('works')]);
  current=detail;current.stock=stock;current.works=works;drawOrder();
 }catch(e){toast(e.message)}
}
function drawOrder(){
 const {order:o,items,payments,events,parts,stock,works}=current;
 const total=o.no_payment?0:items.reduce((s,i)=>s+i.price*i.quantity,0),paid=payments.reduce((s,p)=>s+p.amount,0),cost=parts.reduce((s,p)=>s+p.quantity*p.unit_cost,0);
 const closed=!!o.issued_at||done(o.status),canIssue=state.user.role!=='master'&&!closed;
 const candidates=state.users.filter(u=>u.active),workItems=items.filter(i=>i.kind==='Работа'),available=stock.filter(p=>p.branch_id===o.branch_id&&p.quantity>0);
 const masterOptions=[{id:'',name:'Выберите мастера'},...candidates];
 const lineItems=items.map(i=>{
  const consumed=parts.filter(p=>p.item_id===i.id),itemCost=consumed.reduce((s,p)=>s+p.quantity*p.unit_cost,0),salary=Math.round(Math.max(0,i.quantity*i.price-itemCost)*.4);
  return `<tr class="work-row"><td><span class="work-symbol">⚒</span><b>${esc(i.name)}</b><small class="part-note">${esc(i.master_name||'Мастер не назначен')} · Мастеру 40%: ${rub(salary)}</small></td><td>${i.quantity}</td><td>${i.warranty} дн.</td><td>${rub(i.price)}</td><td><b>${rub(i.price*i.quantity)}</b></td><td>${!closed&&i.kind==='Работа'?`<button type="button" data-add-part="${i.id}" title="Добавить запчасть">＋ Запчасть</button><button type="button" data-assign-work="${i.id}">Мастер</button><button type="button" class="danger-button" data-delete-work="${i.id}">Удалить</button>`:''}</td></tr>${consumed.map(p=>`<tr class="nested-part"><td><span class="part-branch">└</span>${esc(p.name)}<small>Себестоимость · не печатается в акте работ</small></td><td>${p.quantity}</td><td>—</td><td>${rub(p.unit_cost)}</td><td>${rub(p.quantity*p.unit_cost)}</td><td></td></tr>`).join('')}`;
 }).join('');
 modal('Заказ Р-'+o.id,`<div class="compact-order"><div class="order-status"><form id="statusForm" class="row">${select('status','Статус заказа',o.issued_at?state.statuses:state.statuses.filter(s=>!done(s)),o.status)}${!closed||state.user.role!=='master'?'<button type="submit">Сохранить статус</button>':''}</form><small class="muted">${esc(o.device)} · ${date(o.created)}</small></div><div class="tabs"><button id="infoTab" class="${tab==='info'?'active':''}">Информация о заказе</button><button id="itemsTab" class="${tab==='items'?'active':''}">Работы</button></div><section class="panel">${tab==='info'||tab==='receipt'?`<div class="grid order-all-info">${[['Клиент',o.client],['Телефон',o.phone],['Марка',o.brand],['Модель',o.device],['IMEI / серийный номер',o.serial],['Пароль устройства',o.device_password],['Внешний вид',o.appearance],['Комплектация',o.equipment],['Неисправность',o.fault],['Комментарий',o.comment],['Срок',date(o.deadline)]].map(([k,v])=>`<div><label>${k}</label><p>${esc(v||'—')}</p></div>`).join('')}</div>`:`<div class="tablewrap"><table><thead><tr><th>Наименование / мастер</th><th>Кол-во</th><th>Гарантия</th><th>Цена, ₽</th><th>Сумма, ₽</th><th></th></tr></thead><tbody>${lineItems}</tbody></table>${!items.length?'<p>Работы ещё не добавлены</p>':''}</div>${!closed?`<form id="itemForm" class="compact-grid section"><label class="span2">Выполненная работа<input name="name" autocomplete="off" maxlength="300" required placeholder="Выберите или введите новую"></label>${select('master_id','Мастер работы',masterOptions,o.master_id||(state.user.role==='master'?state.user.id:''))}${field('price','Цена клиенту, ₽','number','0',true)}${field('quantity','Количество','number','1',true)}${field('warranty','Гарантия, дней','number','30')}<button type="submit" class="primary">Добавить работу</button><button id="saveWork" type="button">В базу работ</button></form><form id="partForm" class="compact-grid section" hidden>${select('item_id','Работа',workItems.map(i=>({id:i.id,name:i.name})))}${select('stock_id','Запчасть',available.map(p=>({id:p.id,name:p.name+' · '+p.quantity+' шт. · '+rub(p.unit_cost)})))}${field('quantity','Количество запчастей','number','1',true)}<button type="submit" class="primary" ${!available.length?'disabled':''}>Списать запчасть</button>${!available.length?'<p class="full">В филиале нет доступных запчастей.</p>':''}</form><form id="assignForm" class="row section" hidden><input type="hidden" name="item_id">${select('master_id','Назначить мастера работы',masterOptions)}<button type="submit">Назначить</button></form>`:''}`}</section><div class="order-tools"><details class="panel"><summary>Заключение диагностики ${o.diagnosis?'✓':''}</summary><form id="diagnosisForm" class="stack"><label>Заключение диагностики<textarea name="text" maxlength="10000" rows="3" ${closed?'readonly':''}>${esc(o.diagnosis)}</textarea></label>${!closed?'<button type="submit">Сохранить заключение</button>':''}</form></details><details class="panel"><summary>История · ${events.length}</summary><form id="commentForm" class="row"><input name="text" placeholder="Комментарий для коллег" required><button type="submit">Добавить</button></form><div class="compact-history">${events.map(e=>`<div class="event"><small>${date(e.created)} · ${esc(e.author)}</small><p>${esc(e.text)}</p></div>`).join('')}</div></details></div><div class="print-actions">${[['intake','Акт приема на диагностику'],['completion','Акт выполненных работ'],['diagnosis','Акт диагностики']].map(([k,t])=>k==='diagnosis'&&!o.diagnosis.trim()?`<button disabled title="Сохраните заключение">${t}</button>`:`<a class="document-button" href="/api/orders/${o.id}/print?type=${k}" target="_blank" rel="noopener">${t}</a>`).join('')}</div><footer class="order-bottom"><div class="financial-detail"><span>Запчасти: ${rub(cost)}</span><span>Прибыль: ${rub(total-cost)}</span><span>Оплачено: ${rub(paid)}</span></div><div class="row"><div><label>Итого клиенту</label><strong class="order-total">${rub(total)}</strong><small>${o.no_payment?'Без оплаты · бесплатно':paid>total?'Переплата: '+rub(paid-total):'К оплате: '+rub(total-paid)}</small></div>${canIssue?'<div class="issue-buttons"><button type="button" class="primary" data-issue="Выдан">Выдать</button><button type="button" data-issue="Выдан без ремонта">Выдать без ремонта</button></div>':badge(o.status)}</div><form id="issueForm" class="panel compact-grid section" hidden><h3 class="full" id="issueTitle"></h3><input type="hidden" name="status">${select('method','Способ оплаты',[{id:'',name:'Выберите способ оплаты'},'Наличные','Карта','Перевод','Без оплаты'])}<p class="span2" id="issuePaymentHint">Принять при выдаче: <b>${rub(Math.max(0,total-paid))}</b>. ${paid?'Ранее внесённая оплата учтена.':''} Будут записаны оплата, статус и начисления мастерам.</p><button type="submit" class="primary">Подтвердить выдачу</button></form></footer></div>`);
 const drawer=document.querySelector('.drawer');drawer.classList.add('repair-drawer');
 const compact=drawer.querySelector('.compact-order');
 const historyDetails=compact.querySelector('.order-tools details:last-child');
 const history=document.createElement('section');history.className='repair-history';history.setAttribute('aria-label','История заказа');
 const comment=historyDetails.querySelector('#commentForm');
 history.innerHTML='<h2>История</h2><div class="history-scroll"></div><div class="history-comment"></div>';
 const timeline=history.querySelector('.history-scroll');
 timeline.innerHTML=events.slice().reverse().map(e=>{
  const payment=e.text.startsWith('Оплата'),status=e.text.includes('→')||e.text==='Заказ создан',part=e.text.includes('списана запчасть'),work=e.text.startsWith('Добавлено:');
  return `<article class="timeline-event ${payment?'payment':status?'status-event':''}"><span class="timeline-icon">${payment?'₽':part?'▦':work?'⚒':status?'✓':'✎'}</span><div class="timeline-meta"><b>${payment?'Оплата':part?'Добавлена запчасть':work?'Добавлена работа':status?'Статус заказа':'Комментарий'}</b><time>${date(e.created)}</time></div><p>${esc(e.text)}</p><small>${esc(e.author)}</small></article>`;
 }).join('')+'<span class="timeline-now">Сейчас</span>';
 history.querySelector('.history-comment').append(comment);historyDetails.remove();
 const body=document.createElement('div');body.className='repair-body';
 const content=document.createElement('div');content.className='repair-content';
 compact.before(body);body.append(content,history);content.append(compact);
 const footer=compact.querySelector('.order-bottom');footer.classList.add('repair-footer');content.append(footer);
 const print=compact.querySelector('.print-actions');footer.prepend(print);
 const close=document.createElement('button');close.type='button';close.className='footer-close';close.textContent='Закрыть';close.onclick=()=>drawer.closest('.overlay').remove();print.prepend(close);
 drawer.querySelector('header h2').textContent='Заказ № Р-'+o.id;
 drawer.querySelector('#close').textContent='✕';drawer.querySelector('#close').setAttribute('aria-label','Закрыть карточку');
 const historyToggle=document.createElement('button');historyToggle.type='button';historyToggle.className='history-toggle';historyToggle.textContent='История · '+events.length;historyToggle.setAttribute('aria-expanded','false');historyToggle.onclick=()=>{const expanded=history.classList.toggle('mobile-history-open');historyToggle.setAttribute('aria-expanded',String(expanded))};drawer.querySelector('header').append(historyToggle);
 document.querySelector('#infoTab').onclick=()=>{tab='info';drawOrder()};document.querySelector('#itemsTab').onclick=()=>{tab='items';drawOrder()};
 document.querySelector('#showPassword')?.addEventListener('click',()=>{const x=document.querySelector('#devicePassword');x.type=x.type==='password'?'text':'password'});
 const post=async(action,d)=>{await api(`orders/${o.id}/${action}`,d);orders=await api('orders');render();await openOrder(o.id);toast('Сохранено')};
 formBind('itemForm',d=>post('items',{...d,kind:'Работа'}));formBind('partForm',d=>post('parts',d));formBind('assignForm',d=>post('assign-work',d));formBind('diagnosisForm',d=>post('diagnosis',{...d,version:o.version}));formBind('commentForm',d=>post('comment',d));formBind('statusForm',d=>post('status',{...d,version:o.version}));formBind('issueForm',d=>post('issue',{...d,version:o.version}));

 preventOrderAutofill(document.querySelector('#itemForm'));decorateDbSelects(document.querySelector('#itemForm'));decorateDbSelects(document.querySelector('#partForm'));decorateDbSelects(document.querySelector('#assignForm'));
 const itemForm=document.querySelector('#itemForm');
 if(itemForm)checkboxSuggestions(itemForm.elements.name,term=>matchingOptions(current.works.filter(w=>w.active),term),work=>{itemForm.elements.name.value=work.value;itemForm.elements.warranty.value=work.warranty});
 document.querySelectorAll('[data-delete-work]').forEach(button=>button.onclick=()=>{
  const row=items.find(i=>i.id===Number(button.dataset.deleteWork));
  const area=document.createElement('div');area.className='delete-confirm';area.innerHTML=`<p>Удалить работу «${esc(row.name)}»? Связанные запчасти вернутся на склад.</p><button type="button" class="danger-button">Удалить работу</button><button type="button">Отмена</button>`;
  button.closest('td').append(area);button.disabled=true;
  area.querySelector('button').onclick=async()=>{try{await post('delete-work',{item_id:row.id,version:o.version})}catch(e){toast(e.message)}};
  area.querySelectorAll('button')[1].onclick=()=>{area.remove();button.disabled=false};
 });
 const method=document.querySelector('#issueForm').elements.method;
 method.onchange=()=>{document.querySelector('#issuePaymentHint').textContent=method.value==='Без оплаты'?'Бесплатная выдача: долг и начисление мастеру не создаются. Расход запчастей останется учтён.':'Принять при выдаче: '+rub(Math.max(0,total-paid))+'. Ранее внесённая оплата учтена.'};

 document.querySelectorAll('[data-add-part]').forEach(b=>b.onclick=()=>{const f=document.querySelector('#partForm');f.hidden=false;f.elements.item_id.value=b.dataset.addPart;f.elements.item_id.dispatchEvent(new Event('change'));f.scrollIntoView({behavior:'smooth',block:'center'})});
 document.querySelectorAll('[data-assign-work]').forEach(b=>b.onclick=()=>{const f=document.querySelector('#assignForm');f.hidden=false;f.elements.item_id.value=b.dataset.assignWork;f.elements.master_id.required=false});
 document.querySelectorAll('[data-issue]').forEach(b=>b.onclick=()=>{const f=document.querySelector('#issueForm');f.hidden=false;f.elements.status.value=b.dataset.issue;f.elements.method.required=true;document.querySelector('#issueTitle').textContent=b.dataset.issue==='Выдан'?'Выдача после ремонта':'Выдача без ремонта (оплата добавленных работ, включая диагностику)';f.scrollIntoView({behavior:'smooth',block:'center'})});
 document.querySelector('#saveWork')?.addEventListener('click',async()=>{try{current.works=await api('works',{value:document.querySelector('#itemForm').elements.name.value,warranty:document.querySelector('#itemForm').elements.warranty.value});toast('Название сохранено')}catch(e){toast(e.message)}});
}
const moscowToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let reportFrom=moscowToday().slice(0,8)+'01',reportTo=moscowToday(),reportBranch='',reportVersion=0;
async function renderDashboard(){
 const version=++reportVersion;
 try{
  const r=await api('dashboard?from='+reportFrom+'&to='+reportTo+'&branch='+reportBranch);
  if(view!=='home'||version!==reportVersion)return;
  document.querySelector('#main').innerHTML=`<header><div><h1>Главная</h1><p>Работа сервисов и начисления мастерам</p></div><button id="homeNew" class="primary" ${state.user.role==='master'?'hidden':''}>＋ Новый заказ</button></header><form id="reportForm" class="toolbar">${field('from','С даты','date',reportFrom,true)}${field('to','По дату включительно','date',reportTo,true)}${select('branch','Филиал',[{id:'',name:'Все доступные филиалы'},...state.branches],reportBranch)}<button type="submit" class="primary">Показать</button><div class="tabs"><button type="button" data-period="day">Сегодня</button><button type="button" data-period="week">7 дней</button><button type="button" data-period="month">Месяц</button></div></form><div class="cards"><div class="card">Принято техники<strong>${r.accepted}</strong></div><div class="card">Выдано техники<strong>${r.issued}</strong></div><div class="card">Сумма выданных ремонтов<strong>${rub(r.revenue)}</strong></div><div class="card">Себестоимость запчастей<strong>${rub(r.cost)}</strong></div><div class="card">Чистая прибыль по работам<strong>${rub(r.profit)}</strong></div><div class="card">Начислено мастерам · 40%<strong>${rub(r.salary)}</strong></div><div class="card">Доля сервиса · 60%<strong>${rub(r.service)}</strong></div></div><p>Период по московскому времени. Приём — по дате создания, выдача и начисления — по дате выдачи. Доли считаются после вычета запчастей, до прочих расходов. ${state.user.role==='master'?'Показаны ваши работы и начисления.':''}</p><h2>Зарплата мастеров</h2><div class="tablewrap"><table><thead><tr><th>Мастер</th><th>Работ</th><th>Сумма работ</th><th>Запчасти</th><th>Начислено 40%</th><th>Сервису</th></tr></thead><tbody>${r.payroll.map(p=>`<tr><td><b>${esc(p.name)}</b><details><summary>По заказам</summary>${p.details.map(d=>`<p>Р-${d.order_id} · ${esc(d.name)} · ${rub(d.salary)}</p>`).join('')}</details></td><td>${p.works}</td><td>${rub(p.revenue)}</td><td>${rub(p.cost)}</td><td><b>${rub(p.salary)}</b></td><td>${rub(p.service)}</td></tr>`).join('')}</tbody></table>${!r.payroll.length?'<div class="empty">За этот период нет начислений по выданным заказам.</div>':''}</div>`;
  formBind('reportForm',async d=>{reportFrom=d.from;reportTo=d.to;reportBranch=d.branch;await renderDashboard()});
  document.querySelector('#homeNew').onclick=newOrder;
  document.querySelectorAll('[data-period]').forEach(b=>b.onclick=()=>{reportTo=moscowToday();const dt=new Date(reportTo+'T12:00:00Z');if(b.dataset.period==='week')dt.setUTCDate(dt.getUTCDate()-6);reportFrom=b.dataset.period==='month'?reportTo.slice(0,8)+'01':dt.toISOString().slice(0,10);renderDashboard()});
 }catch(e){toast(e.message)}
}
let stockQuery='',stockGroup='',stockBranch='',stockAvailable=false,stockRenderVersion=0;
async function renderStock(){
 const version=++stockRenderVersion;
 try{
  const [stock,groups]=await Promise.all([api('stock'),api('stock-groups')]);if(view!=='stock'||version!==stockRenderVersion)return;
  const term=stockQuery.toLocaleLowerCase('ru');const rows=stock.filter(p=>(!term||[p.name,p.sku].some(v=>v.toLocaleLowerCase('ru').includes(term)))&&(!stockGroup||String(p.group_id||'none')===stockGroup)&&(!stockBranch||String(p.branch_id)===stockBranch)&&(!stockAvailable||p.quantity>0));
  document.querySelector('#main').innerHTML=`<header><div><h1>Склад запчастей</h1><p>Остатки, группы и закупочная стоимость</p></div>${state.user.role!=='master'?'<div class="row"><button id="newStockGroup">＋ Группа</button><button id="newPart" class="primary">＋ Добавить запчасть</button></div>':''}</header><div class="toolbar stock-toolbar"><label>Поиск по названию или артикулу<input id="stockSearch" value="${esc(stockQuery)}" autocomplete="off" placeholder="Название / артикул"></label>${select('stockGroupFilter','Группа',[{id:'',name:'Все группы'},{id:'none',name:'Без группы'},...groups],stockGroup)}${select('stockBranchFilter','Филиал',[{id:'',name:'Все филиалы'},...state.branches],stockBranch)}<label class="checkbox-label"><input type="checkbox" id="stockAvailable" ${stockAvailable?'checked':''}> Только в наличии</label><button id="stockReset">Сбросить</button></div><div class="tablewrap"><table><thead><tr><th>Название</th><th>Артикул</th><th>Группа</th><th>Филиал</th><th>Остаток</th><th>Себестоимость</th><th></th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.sku)}</td><td>${esc(p.group_name||'Без группы')}</td><td>${esc(p.branch_name)}</td><td>${p.quantity} шт.</td><td>${rub(p.unit_cost)}</td><td>${state.user.role!=='master'?`<button data-receive="${p.id}">＋ Поступление</button><button data-part-group="${p.id}">Группа</button>`:''}</td></tr>`).join('')}</tbody></table>${!rows.length?'<div class="empty">Запчасти не найдены</div>':''}</div><p>Показано позиций: ${rows.length}. Запчасти списываются к работе из филиала заказа.</p>`;
  document.querySelector('#stockSearch').oninput=e=>{stockQuery=e.target.value;const pos=e.target.selectionStart;renderStock().then(()=>{const x=document.querySelector('#stockSearch');if(x){x.focus();x.setSelectionRange(pos,pos)}})};
  document.querySelector('[name="stockGroupFilter"]').onchange=e=>{stockGroup=e.target.value;renderStock()};document.querySelector('[name="stockBranchFilter"]').onchange=e=>{stockBranch=e.target.value;renderStock()};document.querySelector('#stockAvailable').onchange=e=>{stockAvailable=e.target.checked;renderStock()};document.querySelector('#stockReset').onclick=()=>{stockQuery=stockGroup=stockBranch='';stockAvailable=false;renderStock()};
  const receipt=part=>{
   modal(part?'Поступление: '+part.name:'Новая запчасть',`<form id="stockForm" class="panel grid" autocomplete="off">${!part?select('branch_id','Филиал',state.branches)+field('name','Название запчасти','text','',true)+field('sku','Артикул','text','',true)+select('group_id','Группа',[{id:'',name:'Без группы'},...groups]):''}${field('quantity','Количество поступления','number','1',true)}${field('unit_cost','Закупочная цена за штуку, ₽','number',part?String(part.unit_cost/100):'0',true)}<button type="submit" class="primary full">Оприходовать</button></form>`);preventOrderAutofill(document.querySelector('#stockForm'));decorateDbSelects(document.querySelector('#stockForm'));formBind('stockForm',async d=>{await api(part?'stock/'+part.id+'/receive':'stock',d);document.querySelector('.overlay').remove();await renderStock();toast('Поступление сохранено')});
  };
  document.querySelector('#newPart')?.addEventListener('click',()=>receipt(null));document.querySelectorAll('[data-receive]').forEach(b=>b.onclick=()=>receipt(stock.find(p=>p.id===Number(b.dataset.receive))));
  document.querySelectorAll('[data-part-group]').forEach(button=>button.onclick=()=>{
   const part=stock.find(p=>p.id===Number(button.dataset.partGroup));modal('Группа: '+part.name,`<form id="partGroupForm" class="stack">${select('group_id','Группа',[{id:'',name:'Без группы'},...groups],part.group_id||'')}<button type="submit" class="primary">Сохранить</button></form>`);decorateDbSelects(document.querySelector('#partGroupForm'));formBind('partGroupForm',async d=>{await api('stock/'+part.id+'/group',d);document.querySelector('.overlay').remove();await renderStock();toast('Группа изменена')});
  });
  document.querySelector('#newStockGroup')?.addEventListener('click',()=>{modal('Новая группа запчастей',`<form id="stockGroupForm" class="stack">${field('name','Название группы','text','',true)}<button type="submit" class="primary">Добавить группу</button></form>`);formBind('stockGroupForm',async d=>{await api('stock-groups',d);document.querySelector('.overlay').remove();await renderStock();toast('Группа добавлена')})});
 }catch(e){toast(e.message)}
}
let workSearch='';
async function renderWorks(){
 try{
  const works=await api('works');if(view!=='works')return;const rows=matchingOptions(works,workSearch);
  document.querySelector('#main').innerHTML=`<header><div><h1>База выполненных работ</h1><p>Названия и гарантия для будущих заказов. Цену указываете при добавлении работы.</p></div><button id="newCatalogWork" class="primary">＋ Добавить работу</button></header><div class="toolbar"><label>Найти работу<input id="workSearch" value="${esc(workSearch)}" autocomplete="off"></label></div><div class="tablewrap"><table><thead><tr><th>Название</th><th>Категория</th><th>Гарантия</th><th>Состояние</th><th></th></tr></thead><tbody>${rows.map(w=>`<tr><td>${esc(w.value)}</td><td>${esc(w.work_group||'Общие')}</td><td>${w.warranty} дн.</td><td>${w.active?'Используется':'В архиве'}</td><td>${state.user.role!=='master'?`<button data-edit-work="${w.id}">Изменить</button>`:''}</td></tr>`).join('')}</tbody></table></div><p>Работ: ${rows.length}. Изменение гарантии в базе не меняет ранее оформленные заказы.</p>`;
  document.querySelector('#workSearch').oninput=e=>{workSearch=e.target.value;const pos=e.target.selectionStart;renderWorks().then(()=>{const x=document.querySelector('#workSearch');if(x){x.focus();x.setSelectionRange(pos,pos)}})};
  function edit(work){modal(work?'Изменить работу':'Новая работа',`<form id="catalogWorkForm" class="stack">${field('value','Название работы','text',work?.value||'',true)}${field('work_group','Категория','text',work?.work_group||'')}${field('warranty','Гарантия, дней','number',work?.warranty??30,true)}${work?`<label class="checkbox-label"><input type="checkbox" name="archived" ${!work.active?'checked':''}> Убрать в архив</label>`:''}<button type="submit" class="primary">Сохранить</button></form>`);formBind('catalogWorkForm',async d=>{await api('works',{...d,id:work?.id,archived:!!d.archived});document.querySelector('.overlay').remove();await renderWorks();toast('Работа сохранена')})}
  document.querySelector('#newCatalogWork').onclick=()=>edit(null);document.querySelectorAll('[data-edit-work]').forEach(b=>b.onclick=()=>edit(works.find(w=>w.id===Number(b.dataset.editWork))));
 }catch(e){toast(e.message)}
}
function renderClients(){let clients=new Map;orders.forEach(o=>{let k=o.phone;let c=clients.get(k)||{name:o.client,phone:o.phone,count:0};c.count++;clients.set(k,c)});document.querySelector('#main').innerHTML=`<h1>Клиенты</h1><p>Список по доступным вам заказам. Общая история по номеру телефона.</p><div class="tablewrap"><table><thead><tr><th>Клиент</th><th>Телефон</th><th>Заказов</th></tr></thead><tbody>${[...clients.values()].map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.phone)}</td><td>${c.count}</td></tr>`).join('')}</tbody></table>${!clients.size?'<div class="empty">Клиенты появятся после создания заказов</div>':''}</div>`}
function renderTeam(){document.querySelector('#main').innerHTML=`<header><div><h1>Сотрудники</h1><p>Личные учётные записи и доступ к филиалам</p></div><button id="addUser" class="primary">＋ Сотрудник</button></header><div class="tablewrap"><table><thead><tr><th>Имя</th><th>Email</th><th>Роль</th><th>Доступ</th><th></th></tr></thead><tbody>${state.users.map(u=>`<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${{owner:'Владелец',manager:'Приёмщик',master:'Мастер'}[u.role]}</td><td>${u.active?'Активен':'Отключён'}</td><td>${u.id!==state.user.id&&u.active?`<button data-disable="${u.id}">Отключить</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;document.querySelectorAll('[data-disable]').forEach(b=>b.onclick=async()=>{try{await api('users',{disable:b.dataset.disable});await load()}catch(e){toast(e.message)}});document.querySelector('#addUser').onclick=()=>{modal('Новый сотрудник',`<form id="userForm" class="panel stack">${field('name','Имя','text','',true)}${field('email','Email','email','',true)}${field('password','Начальный пароль — минимум 12 символов','password','',true)}${select('role','Роль',[{id:'manager',name:'Приёмщик — заказы и оплата'},{id:'master',name:'Мастер — только назначенные заказы'}])}<label>Доступ к филиалам<select name="branches" multiple required size="4">${state.branches.map(b=>`<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select></label><small class="muted">Для выбора нескольких на ПК удерживайте Ctrl / Cmd.</small><button class="primary" type="submit">Создать учётную запись</button></form>`);formBind('userForm',async(d,f)=>{await api('users',{...d,branches:new FormData(f).getAll('branches')});await load();toast('Сотрудник создан')})}}
function renderBranches(){document.querySelector('#main').innerHTML=`<h1>Филиалы</h1><p>Общая компания — отдельные рабочие пространства</p><div class="cards">${state.branches.map(b=>`<div class="card"><h2>${esc(b.name)}</h2><p>${orders.filter(o=>o.branch_id===b.id).length} заказов</p></div>`).join('')}</div><form id="branchForm" class="panel toolbar">${field('name','Название нового филиала','text','',true)}<button type="submit" class="primary">Добавить филиал</button></form>`;formBind('branchForm',async d=>{await api('branches',d);await load();toast('Филиал создан')})}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelector('.overlay')?.remove()});boot();
