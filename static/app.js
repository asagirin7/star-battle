'use strict';
const $ = s => document.querySelector(s);
const colors = ['#b8c8df','#e7c4ae','#c5d4b4','#d2bfde','#e4d59f','#a9d2d2','#dbb6c4','#c0c1e4'];
let me = null, catalog = [], level = 'easy', puzzle = null, game = null, cells = [], undo = [], busy = false;
const label = {easy:'EASY', medium:'MEDIUM', hard:'HARD'};
async function api(path, data) {
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (!response.ok) {
    let message = '通信に失敗しました。もう一度お試しください。';
    try { const error = await response.json(); if (typeof error.detail === 'string') message = error.detail; } catch {}
    const e = new Error(message); e.status = response.status; throw e;
  }
  return response.json();
}
function status(message, success = false) { $('#status').textContent = message; $('#status').classList.toggle('success', success); }
function profileView() {
  $('#profile-button').textContent = me.name;
  $('#total').replaceChildren(document.createTextNode(me.points + ' '), Object.assign(document.createElement('small'), {textContent:'pt'}));
  $('#clear-count').textContent = me.clears + ' 問クリア';
}
function openProfile() { $('#name').value = me?.name || ''; $('#profile-dialog').showModal(); }
$('#profile-button').onclick = openProfile;
$('#close-profile').onclick = () => $('#profile-dialog').close();
$('#profile-form').onsubmit = async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  try {
    me = await api('profile', {name:$('#name').value}); profileView(); $('#profile-dialog').close();
    if (!catalog.length) { catalog = await api('puzzles'); await choose(); }
  } catch (e) { $('#profile-error').textContent = e.message; }
  finally { submit.disabled = false; }
};
function savedKey() { return `star-battle:${me.id}:${puzzle.id}`; }
function save() { try { localStorage.setItem(savedKey(), JSON.stringify(cells)); } catch {} }
async function choose(next = false) {
  if (!me) { openProfile(); return; }
  if (busy) return;
  busy = true;
  try {
    const available = catalog.filter(p => p.difficulty === level);
    const currentIndex = available.findIndex(p => p.id === puzzle?.id);
    const target = next ? available[(currentIndex+1) % available.length] : available.find(p => !p.cleared) || available[0];
    const attempt = await api('games', {puzzle_id:target.id});
    puzzle = target; game = attempt; cells = Array(puzzle.size**2).fill(0); undo = [];
    try { const stored = JSON.parse(localStorage.getItem(savedKey())); if (Array.isArray(stored) && stored.length === cells.length && stored.every(v=>[0,1,2].includes(v))) cells = stored; } catch {}
    render(); status(puzzle.cleared ? 'クリア済みの問題です。もう一度練習できます。' : 'タップで 星 → × → 空白 に切り替わります。');
  } catch(e) { status(e.message); }
  finally { busy = false; }
}
function render() {
  const n = puzzle.size;
  $('#puzzle-label').textContent = `${label[level]} / No. ${puzzle.id.split('-')[1]} / ${puzzle.points} PT`;
  $('#puzzle-title').textContent = puzzle.cleared ? 'クリア済み ✦' : '星の居場所を見つけよう。';
  const board = $('#board'); board.replaceChildren(); board.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  cells.forEach((value, i) => {
    const r = Math.floor(i/n), c = i%n, region = puzzle.regions[r][c];
    const button = document.createElement('button'); button.className = 'cell' + (value===2?' marked':'');
    button.textContent = value===1?'★':value===2?'×':'';
    button.setAttribute('aria-label', `${r+1}行${c+1}列、エリア${region+1}、${value===1?'星':value===2?'除外':'空白'}`);
    button.style.background = colors[region];
    if (r<n-1 && puzzle.regions[r+1][c]!==region) button.style.borderBottom = '2px solid #444357';
    if (c<n-1 && puzzle.regions[r][c+1]!==region) button.style.borderRight = '2px solid #444357';
    button.onclick = () => { if(busy)return; undo.push(cells.slice()); cells[i]=(cells[i]+1)%3; save(); render(); };
    button.onkeydown = event => {
      const delta = {ArrowUp:-n,ArrowDown:n,ArrowLeft:-1,ArrowRight:1}[event.key];
      if (delta !== undefined) { event.preventDefault(); board.children[Math.max(0,Math.min(n*n-1,i+delta))].focus(); }
    };
    board.append(button);
  });
}
document.querySelectorAll('[data-level]').forEach(button => button.onclick = async () => {
  if (busy) return;
  level = button.dataset.level;
  document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected', b===button));
  await choose();
});
$('#next').onclick = () => choose(true);
$('#undo').onclick = () => { if(!busy && undo.length) {cells=undo.pop(); save();render();} };
$('#reset').onclick = () => { if(!busy && puzzle) {undo.push(cells.slice());cells.fill(0);save();render();status('盤面をリセットしました。');} };
$('#check').onclick = async () => {
  if(!me) {openProfile();return;} if(!game || busy)return;
  const stars = cells.flatMap((v,i)=>v===1?[[Math.floor(i/puzzle.size),i%puzzle.size]]:[]);
  if(stars.length!==puzzle.size) {status(`星を${puzzle.size}個置いてください。いま${stars.length}個です。`);return;}
  busy=true; $('#check').disabled=true;
  try {
    const result = await api(`games/${game.id}/complete`, {stars});
    me=result.player; profileView();puzzle.cleared=true;render();
    status(result.awarded ? `クリア！ ✦ +${result.awarded} pt を獲得しました。` : 'クリア！ この問題のポイントは獲得済みです。',true);
  } catch(e) {status(e.message);}
  finally {busy=false;$('#check').disabled=false;}
};
function row(container, position, title, detail, points, mine=false) {
  const el=document.createElement('div');el.className='list-row'+(mine?' mine':'');
  const pos=Object.assign(document.createElement('span'),{className:'position',textContent:position});
  const name=Object.assign(document.createElement('div'),{className:'row-name',textContent:title});
  name.append(Object.assign(document.createElement('small'),{textContent:detail}));
  el.append(pos,name,Object.assign(document.createElement('strong'),{textContent:`${points} pt`}));container.append(el);
}
function empty(container,text) {container.append(Object.assign(document.createElement('p'),{className:'empty',textContent:text}));}
async function showTab(tab) {
  document.querySelectorAll('.tab').forEach(s=>s.hidden=s.id!==tab);
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  if(tab==='play')return;
  const container=$(`#${tab}-list`);container.replaceChildren();empty(container,'読み込み中…');
  try {
    if(tab==='ranking') {
      const rows=await api('ranking'); container.replaceChildren();
      rows.forEach((p,i)=>row(container,String(i+1).padStart(2,'0'),p.name,`${p.clears} 問クリア${p.id===me?.id?' · あなた':''}`,p.points,p.id===me?.id));
      if(!rows.length)empty(container,'まだ記録がありません。最初の星を集めよう。');
    } else {
      if(!me) {container.replaceChildren();empty(container,'名前を登録すると、クリア記録がここに表示されます。');return;}
      const rows=await api('history');container.replaceChildren();
      rows.forEach(p=>row(container,'✦',`${label[p.puzzle_id.split('-')[0]]} / No. ${p.puzzle_id.split('-')[1]}`,`${new Date(p.cleared_at*1000).toLocaleDateString('ja-JP')} · ${Math.floor(p.seconds/60)}分${p.seconds%60}秒`,p.points));
      if(!rows.length)empty(container,'まだクリア記録がありません。最初の一問に挑戦しよう。');
    }
  } catch(e) {container.replaceChildren();empty(container,e.message);}
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
setInterval(()=>{
  if(!game || puzzle?.cleared)return;
  const seconds=Math.max(0,Math.floor(Date.now()/1000-game.started_at));
  $('#timer').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
},1000);
(async()=>{
  try {me=await api('me');profileView();catalog=await api('puzzles');await choose();}
  catch(e) {if(e.status===401)openProfile();else status(e.message);}
})();
