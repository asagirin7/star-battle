'use strict';
const $ = s => document.querySelector(s);
const colors = ['#b8c8df','#e7c4ae','#c5d4b4','#d2bfde','#e4d59f','#a9d2d2','#dbb6c4','#c0c1e4'];
const label = {easy:'EASY', medium:'MEDIUM', hard:'HARD'};
let me = null, level = 'easy', puzzle = null, game = null, cells = [], undo = [], busy = false, mode = 'star';
let pendingMove = null, pendingStart = null;
function requestId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
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
    if (!game) await choose();
  } catch (e) { $('#profile-error').textContent = e.message; }
  finally { submit.disabled = false; }
};
function savedKey() { return `star-battle:${me.id}:${game.id}`; }
function save() { try { localStorage.setItem(savedKey(), JSON.stringify(cells.map(v=>v===2?2:0))); } catch {} }
function applyGame(state, loadMemos=false) {
  game=state;puzzle=state.puzzle;level=puzzle.difficulty;
  if(loadMemos) {
    cells=Array(puzzle.size**2).fill(0);undo=[];
    try {const stored=JSON.parse(localStorage.getItem(savedKey()));if(Array.isArray(stored)&&stored.length===cells.length) cells=stored.map(v=>v===2?2:0);} catch {}
  }
  cells=cells.map(v=>v===2?2:0);
  game.stars.forEach(([r,c])=>cells[r*puzzle.size+c]=1);
  document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected', b.dataset.level===level));
  render();
}
function gameMessage() {
  if(game.completed) status(`クリア！ ✦ 残機 ${game.score} = +${game.score} pt。次の問題に挑戦しよう。`, true);
  else if(game.game_over) status('ゲームオーバー。新しい問題で、もう一度挑戦しよう。');
  else status('★ 星 / × メモ を選んで、マスをタップ。正解の星は固定されます。');
}
async function choose(next = false) {
  if (!me) { openProfile(); return; }
  if (busy) return;
  busy = true; $('#advance').disabled=true;
  const previousLevel=game?.puzzle.difficulty;
  try {
    status('新しい星の配置を準備しています…');
    let state = next ? null : await api(`games/current?difficulty=${level}`);
    if(!state) {
      if(!pendingStart || pendingStart.difficulty!==level)pendingStart={difficulty:level,request_id:requestId()};
      state=await api('games',pendingStart);pendingStart=null;
    }
    applyGame(state,true);gameMessage();
  } catch(e) {
    if(previousLevel)level=previousLevel;
    document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected',b.dataset.level===level));
    status(e.message);
  } finally { busy = false; $('#advance').disabled=false; }
}
function renderCell(button, i) {
  const r=Math.floor(i/puzzle.size),c=i%puzzle.size,value=cells[i];
  button.className='cell'+(value===1?' locked':value===2?' marked':'');
  button.textContent=value===1?'★':value===2?'×':'';
  button.setAttribute('aria-label',`${r+1}行${c+1}列、エリア${puzzle.regions[r][c]+1}、${value===1?'確定した星':value===2?'除外':'空白'}`);
}
function render() {
  const n = puzzle.size;
  $('#puzzle-label').textContent = `${label[level]} / ${puzzle.id.slice(0,8).toUpperCase()}`;
  $('#puzzle-title').textContent = game.completed ? 'クリア！ 次の星を探そう ✦' : game.game_over?'もう一度、ひらめこう。':'星の居場所を見つけよう。';
  $('#lives').replaceChildren();
  for(let i=0;i<3;i++) $('#lives').append(Object.assign(document.createElement('span'),{textContent:'♥',className:i<game.lives?'':'lost'}));
  $('#lives').setAttribute('aria-label',`残機 ${game.lives}、ミス ${game.mistakes}回`);
  $('#advance').textContent=game.completed?'次の問題に挑戦 →':game.game_over?'新しい問題で再挑戦 →':'新しい問題に挑戦 →';
  const board = $('#board'); board.replaceChildren(); board.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  cells.forEach((value, i) => {
    const r = Math.floor(i/n), c = i%n, region = puzzle.regions[r][c];
    const button = document.createElement('button');button.dataset.index=i;renderCell(button,i);
    button.style.background = colors[region];
    if (r<n-1 && puzzle.regions[r+1][c]!==region) button.style.borderBottom = '2px solid #444357';
    if (c<n-1 && puzzle.regions[r][c+1]!==region) button.style.borderRight = '2px solid #444357';
    button.onkeydown = event => {
      const delta = {ArrowUp:-n,ArrowDown:n,ArrowLeft:-1,ArrowRight:1}[event.key];
      if (delta !== undefined) {event.preventDefault();board.children[Math.max(0,Math.min(n*n-1,i+delta))].focus();}
    };
    board.append(button);
  });
  updateTimer();
}
function memo(i) {
  if(busy || !game || game.completed || game.game_over || cells[i]===1)return;
  undo.push(cells.slice());cells[i]=cells[i]===2?0:2;save();renderCell($('#board').children[i],i);
}
async function star(i) {
  if(busy || !game || game.completed || game.game_over || cells[i]===1)return;
  busy=true;
  try {
    const row=Math.floor(i/puzzle.size),col=i%puzzle.size;
    // Preserve the operation ID after a network error, including after reload.
    const key=`star-pending:${me.id}:${game.id}`;
    if(!pendingMove) {try {pendingMove=JSON.parse(localStorage.getItem(key));} catch {}}
    const retry=!!pendingMove;
    if(!pendingMove)pendingMove={row,col,request_id:requestId()};
    try {localStorage.setItem(key,JSON.stringify(pendingMove));} catch {}
    const move=pendingMove;
    const result=await api(`games/${game.id}/stars`,move);
    pendingMove=null;try {localStorage.removeItem(key);} catch {}
    me=result.player;profileView();applyGame(result.game);
    const index=move.row*puzzle.size+move.col;
    if(!result.correct) {cells[index]=2;save();renderCell($('#board').children[index],index);$('#board').children[index].classList.add('wrong');}
    if(game.completed || game.game_over)gameMessage();
    else if(!result.correct)status(`そこには星を置けません。残機 ${game.lives}。`);
    else status(retry?'前の操作を確認しました。続けて星を置けます。':'正解！ ✦ 次の星を見つけよう。');
    $('#board').children[index].focus({preventScroll:true});
  } catch(e) {status(`${e.message} 次に星をタップすると、前の操作を再確認します。`);}
  finally {busy=false;}
}
$('#board').onclick=event=>{const b=event.target.closest('[data-index]');if(!b)return;const i=Number(b.dataset.index);if(mode==='star')star(i);else if(event.detail<2)memo(i);};
$('#board').ondblclick=event=>{if(mode==='memo'){const b=event.target.closest('[data-index]');if(b)star(Number(b.dataset.index));}};
$('#board').oncontextmenu=event=>{const b=event.target.closest('[data-index]');if(b){event.preventDefault();star(Number(b.dataset.index));}};
function setMode(value) {mode=value;['star','memo'].forEach(v=>{const b=$(`#${v}-mode`);b.classList.toggle('selected',mode===v);b.setAttribute('aria-pressed',String(mode===v));});}
$('#star-mode').onclick=()=>setMode('star');$('#memo-mode').onclick=()=>setMode('memo');
document.querySelectorAll('[data-level]').forEach(button => button.onclick = async () => {
  if (busy) return;level=button.dataset.level;pendingMove=null;await choose();
});
$('#next').onclick = () => {pendingMove=null;choose(true);};
$('#advance').onclick = () => {pendingMove=null;choose(true);};
$('#undo').onclick = () => {
  if(busy || !undo.length || !game || game.completed || game.game_over)return;
  const memoState=undo.pop();cells=cells.map((v,i)=>v===1?1:memoState[i]===2?2:0);save();render();
};
$('#reset').onclick = () => {if(!busy && game && !game.completed && !game.game_over){undo.push(cells.slice());cells=cells.map(v=>v===1?1:0);save();render();status('メモを消しました。残機と確定した星はそのままです。');}};
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
      const rows=await api('ranking');container.replaceChildren();
      rows.forEach((p,i)=>row(container,String(i+1).padStart(2,'0'),p.name,`${p.clears} 問クリア${p.id===me?.id?' · あなた':''}`,p.points,p.id===me?.id));
      if(!rows.length)empty(container,'まだ記録がありません。最初の星を集めよう。');
    } else {
      if(!me){container.replaceChildren();empty(container,'名前を登録すると、クリア記録がここに表示されます。');return;}
      const rows=await api('history');container.replaceChildren();
      rows.forEach(p=>row(container,'✦',`${label[p.difficulty]} / ${p.puzzle_id.slice(0,8).toUpperCase()}`,`${new Date(p.cleared_at*1000).toLocaleDateString('ja-JP')} · ${Math.floor(p.seconds/60)}分${p.seconds%60}秒 · ミス${p.mistakes}回`,p.points));
      if(!rows.length)empty(container,'まだクリア記録がありません。最初の一問に挑戦しよう。');
    }
  } catch(e) {container.replaceChildren();empty(container,e.message);}
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function updateTimer() {
  if(!game)return;
  const seconds=(game.completed || game.game_over)?game.seconds:Math.max(0,Math.floor(Date.now()/1000-game.started_at));
  $('#timer').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}
setInterval(updateTimer,1000);
(async()=>{
  try {me=await api('me');profileView();await choose();}
  catch(e) {if(e.status===401)openProfile();else status(e.message);}
})();
