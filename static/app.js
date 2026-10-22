'use strict';
const $ = s => document.querySelector(s);
const colors = ['#b8c8df','#e7c4ae','#c5d4b4','#d2bfde','#e4d59f','#a9d2d2','#dbb6c4','#c0c1e4','#9cc8a0'];
const label = {easy:'EASY', medium:'MEDIUM', hard:'HARD', expert:'EXPERT', expert_relaxed:'9 × 9 / 8 × 8相当'};
let me=null,level='easy',puzzle=null,game=null,cells=[],undo=[],busy=false;
let moveQueue=[],sending=false,pendingStart=null,autoCross=false,autoPreview=new Set();
let celebration=null,expertMode='expert';
try{
  autoCross=localStorage.getItem('star-auto-cross')==='true';
  const savedLevel=localStorage.getItem('star-level');if(label[savedLevel])level=savedLevel;
  if(localStorage.getItem('star-expert-mode')==='expert_relaxed')expertMode='expert_relaxed';
}catch{}
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
function text(el,value){if(el.textContent!==value)el.textContent=value;}
function attribute(el,name,value){if(el.getAttribute(name)!==value)el.setAttribute(name,value);}
function disabled(el,value){if(el.disabled!==value)el.disabled=value;}
function status(message, success = false) { text($('#status'),message); $('#status').classList.toggle('success', success); }
function profileView() {
  text($('#profile-button'),me.name);
  const points=(celebration?celebration.displayed:me.points)+' ';
  if($('#total').firstChild.nodeValue!==points)$('#total').firstChild.nodeValue=points;
  text($('#clear-count'),me.clears+' 問クリア');
}
function celebrate(completed,previousPoints) {
  const dialog=$('#clear-celebration'),reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const start=performance.now(),duration=reduced?150:3000;
  celebration={displayed:previousPoints,frame:0};
  text($('#reward-lives'),'♥'.repeat(completed.lives));
  text($('#reward-multiplier'),String(completed.puzzle.multiplier||''));
  dialog.classList.toggle('fixed-reward',completed.puzzle.scoring==='fixed');
  text($('#reward-earned'),`+${completed.score} pt`);
  text($('#reward-total'),String(previousPoints));
  dialog.dataset.phase='lives';
  dialog.showModal();
  function frame(now) {
    if(!celebration)return;
    const elapsed=now-start,progress=reduced?1:Math.min(1,Math.max(0,(elapsed-1800)/850));
    dialog.dataset.phase=reduced||elapsed>=1800?'total':elapsed>=1100?'earned':elapsed>=550?'multiply':'lives';
    celebration.displayed=Math.round(previousPoints+(me.points-previousPoints)*(1-(1-progress)**3));
    text($('#reward-total'),String(celebration.displayed));profileView();
    if(elapsed>=duration){finishCelebration();return;}
    celebration.frame=requestAnimationFrame(frame);
  }
  celebration.frame=requestAnimationFrame(frame);
}
function finishCelebration() {
  if(!celebration)return;
  cancelAnimationFrame(celebration.frame);celebration=null;
  $('#clear-celebration').close();profileView();
  $('#total').animate([{transform:'scale(1)'},{transform:'scale(1.15)'},{transform:'scale(1)'}],{duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:400});
  $('#overlay-next').focus({preventScroll:true});
}
$('#finish-celebration').onclick=finishCelebration;
$('#clear-celebration').addEventListener('cancel',event=>{event.preventDefault();finishCelebration();});
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
function queueKey() { return `star-queue:${me.id}:${game.id}`; }
function save() { try { localStorage.setItem(savedKey(), JSON.stringify(cells.map(v=>v===2?2:0))); } catch {} saveQueue(); }
function saveQueue() { try {localStorage.setItem(queueKey(),JSON.stringify(moveQueue));} catch {} }
function waiting(i) {return moveQueue.some(m=>m.row*puzzle.size+m.col===i);}
function ended() {return !game || game.completed || game.game_over;}
function mutable(i) {return !busy && !ended() && cells[i]!==1 && !waiting(i);}
function memoSnapshot(){
  const snapshot=cells.slice();
  snapshot.suppressed=Object.fromEntries(moveQueue.map(m=>[m.request_id,[...(m.suppressed||[])]]));
  return snapshot;
}
function restoreMemos(snapshot){
  cells=cells.map((v,i)=>v===1?1:snapshot[i]===2?2:0);
  for(const move of moveQueue)if(snapshot.suppressed?.[move.request_id])move.suppressed=[...snapshot.suppressed[move.request_id]];
}
function forbidden(row,col,i){
  const r=Math.floor(i/puzzle.size),c=i%puzzle.size;
  return r===row||c===col||puzzle.regions[r][c]===puzzle.regions[row][col]||(Math.abs(r-row)<=1&&Math.abs(c-col)<=1);
}
function visibleValue(i){return cells[i]===1?1:cells[i]===2||autoPreview.has(i)?2:0;}
function paintMemo(i,value){
  if(!mutable(i))return;
  cells[i]=value;
  for(const move of moveQueue){
    const suppressed=new Set(move.suppressed||[]);
    if(value===0&&autoCross&&forbidden(move.row,move.col,i))suppressed.add(i);
    else if(value===2)suppressed.delete(i);
    move.suppressed=[...suppressed];
  }
}
function commit(prev){
  const suppression=Object.fromEntries(moveQueue.map(m=>[m.request_id,m.suppressed||[]]));
  if(prev.some((v,i)=>v!==cells[i])||JSON.stringify(prev.suppressed||{})!==JSON.stringify(suppression)){
    undo.push(prev);if(undo.length>500)undo.shift();
  }
  save();render();
}
function applyGame(state, loadMemos=false, draw=true) {
  if(loadMemos)input.reset();
  game=state;puzzle=state.puzzle;level=puzzle.difficulty;
  try{
    localStorage.setItem('star-level',level);
    if(puzzle.size===9){expertMode=level;localStorage.setItem('star-expert-mode',level);}
  }catch{}
  if(loadMemos) {
    cells=Array(puzzle.size**2).fill(0);undo=[];moveQueue=[];
    try {const stored=JSON.parse(localStorage.getItem(savedKey()));if(Array.isArray(stored)&&stored.length===cells.length)cells=stored.map(v=>v===2?2:0);} catch {}
    try {
      const stored=JSON.parse(localStorage.getItem(queueKey()));
      if(Array.isArray(stored))moveQueue=stored.filter(m=>Number.isInteger(m.row)&&Number.isInteger(m.col)&&m.row>=0&&m.col>=0&&m.row<puzzle.size&&m.col<puzzle.size&&typeof m.request_id==='string');
      // Resume an operation saved by the previous version as well.
      const oldKey=`star-pending:${me.id}:${game.id}`,old=JSON.parse(localStorage.getItem(oldKey));
      if(old&&!moveQueue.length)moveQueue=[old];localStorage.removeItem(oldKey);
    } catch {}
  }
  cells=cells.map(v=>v===2?2:0);
  game.stars.forEach(([r,c])=>cells[r*puzzle.size+c]=1);
  if(ended()){moveQueue=[];saveQueue();}
  document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected',(b.dataset.level===level||(b.dataset.level==='expert'&&level==='expert_relaxed'))));
  if(draw)render();
}
function rewardMessage() {
  return puzzle.scoring==='fixed'?`ノーミスクリア！ +${game.score} pt`:`残機 ${game.lives} × ${puzzle.multiplier} = +${game.score} pt`;
}
function gameMessage() {
  if(game.completed)status(`クリア！ ✦ ${rewardMessage()}。次の問題に挑戦しよう。`,true);
  else if(game.game_over)status('ゲームオーバー。NEXTゲームで、もう一度挑戦しよう。');
  else status((puzzle.scoring==='fixed'?`9×9は1ミスで終了、クリアで${puzzle.points} pt。`:'')+'1回タップで×、2回タップで★。ドラッグで×を付け外し。');
}
function controls() {
  const changing=busy||sending||moveQueue.length>0;
  for(const selector of ['#advance','#next','#overlay-next','#expert-mode', '[data-level="easy"]','[data-level="medium"]','[data-level="hard"]','[data-level="expert"]']) disabled($(selector),changing);
  disabled($('#undo'),busy||ended()||!undo.length);
  disabled($('#reset'),busy||ended());
  $('#retry-moves').hidden=!moveQueue.length||sending;
}
async function choose(next=false) {
  if(!me){openProfile();return;}
  if(busy||sending||moveQueue.length)return;
  busy=true;controls();
  const previousLevel=game?.puzzle.difficulty;
  try {
    status('新しい星の配置を準備しています…');
    let state=next?null:await api(`games/current?difficulty=${level}`);
    if(!state){
      if(!pendingStart||pendingStart.difficulty!==level)pendingStart={difficulty:level,request_id:requestId()};
      state=await api('games',pendingStart);pendingStart=null;
    }
    applyGame(state,true);gameMessage();
  }catch(e){
    if(previousLevel)level=previousLevel;
    document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected',(b.dataset.level===level||(b.dataset.level==='expert'&&level==='expert_relaxed'))));
    status(e.message);
  }finally{busy=false;controls();}
  if(moveQueue.length)pumpMoves();
}
function renderCell(button,i) {
  const r=Math.floor(i/puzzle.size),c=i%puzzle.size,value=visibleValue(i),pending=value!==1&&waiting(i);
  button.classList.toggle('locked',value===1);
  button.classList.toggle('pending',pending);
  button.classList.toggle('marked',value===2&&!pending);
  const glyph=value===1||pending?'★':value===2?'×':'';
  const mark=button.firstElementChild;
  if(mark.textContent!==glyph)mark.textContent=glyph;
  const markClass=value===2&&!pending?'mark':'';
  if(mark.className!==markClass)mark.className=markClass;
  attribute(button,'aria-label',`${r+1}行${c+1}列、エリア${puzzle.regions[r][c]+1}、${value===1?'確定した星':pending?'星を確認中':value===2?'除外':'空白'}`);
}
function render() {
  if(!puzzle)return;
  const n=puzzle.size,board=$('#board');
  autoPreview=new Set();
  if(autoCross)for(const move of moveQueue){
    const suppressed=new Set(move.suppressed||[]);
    for(let i=0;i<n*n;i++)if(!suppressed.has(i)&&forbidden(move.row,move.col,i))autoPreview.add(i);
  }
  text($('#puzzle-label'),`${label[level]} / ${puzzle.id.slice(0,8).toUpperCase()}`);
  text($('#puzzle-title'),game.completed?'クリア！ 次の星を探そう ✦':game.game_over?'もう一度、ひらめこう。':'星の居場所を見つけよう。');
  const hearts=$('#lives');
  const maxLives=puzzle.initial_lives||3;
  if(hearts.children.length!==maxLives)hearts.replaceChildren(...Array.from({length:maxLives},()=>Object.assign(document.createElement('span'),{textContent:'♥'})));
  [...hearts.children].forEach((heart,i)=>heart.classList.toggle('lost',i>=game.lives));
  attribute(hearts,'aria-label',`残機 ${game.lives}、ミス ${game.mistakes}回`);
  text($('#advance'),game.completed?'次の問題に挑戦 →':game.game_over?'新しい問題で再挑戦 →':'新しい問題に挑戦 →');
  const result=$('#game-over');
  result.hidden=!(game.completed||game.game_over);
  result.classList.toggle('cleared',game.completed);
  text($('#result-title'),game.completed?'クリア！ ✦':'ゲームオーバー');
  text($('#result-message'),game.completed?rewardMessage():'次の問題で、もう一度。');
  $('#expert-mode').hidden=n!==9;
  text($('#expert-mode'),level==='expert_relaxed'?'難しい9×9に戻す':'8×8相当の難易度にする');
  attribute($('#expert-mode'),'aria-pressed',String(level==='expert_relaxed'));
  text($('#auto-cross'),`自動で× ${autoCross?'ON':'OFF'}`);
  attribute($('#auto-cross'),'aria-pressed',String(autoCross));
  if(board.dataset.puzzle!==puzzle.id){
    board.replaceChildren();board.dataset.puzzle=puzzle.id;
    board.style.gridTemplateColumns=`repeat(${n},minmax(0,1fr))`;
    board.style.gridTemplateRows=`repeat(${n},minmax(0,1fr))`;
    for(let i=0;i<n*n;i++){
      const r=Math.floor(i/n),c=i%n,region=puzzle.regions[r][c];
      const button=document.createElement('button');button.type='button';button.className='cell';button.dataset.index=i;
      button.style.background=colors[region];button.append(document.createElement('span'));
      if(r<n-1&&puzzle.regions[r+1][c]!==region)button.style.borderBottom='2px solid #444357';
      if(c<n-1&&puzzle.regions[r][c+1]!==region)button.style.borderRight='2px solid #444357';
      board.append(button);
    }
  }
  cells.forEach((_,i)=>renderCell(board.children[i],i));
  controls();updateTimer();
}
function autoMark(stars=game.stars,skip=new Set()){
  if(!autoCross)return;
  for(const [r,c] of stars)for(let i=0;i<puzzle.size**2;i++){
    if(cells[i]===0&&!waiting(i)&&!skip.has(i)&&forbidden(r,c,i))cells[i]=2;
  }
}

function star(i) {
  if(!mutable(i))return;
  moveQueue.push({row:Math.floor(i/puzzle.size),col:i%puzzle.size,request_id:requestId()});
  saveQueue();render();pumpMoves();
}
async function pumpMoves() {
  if(sending||busy||!moveQueue.length)return;
  sending=true;controls();
  try {
    while(moveQueue.length&&!ended()){
      const move=moveQueue[0],result=await api(`games/${game.id}/stars`,{row:move.row,col:move.col,request_id:move.request_id});
      moveQueue.shift();saveQueue();
      const justCleared=result.game.completed&&!game.completed;
      const previousPoints=me.points;
      me=result.player;
      if(justCleared)celebrate(result.game,previousPoints);
      profileView();applyGame(result.game,false,false);
      const index=move.row*puzzle.size+move.col,prev=memoSnapshot();
      if(result.correct)autoMark([[move.row,move.col]],new Set(move.suppressed||[]));else cells[index]=2;
      commit(prev);
      if(!result.correct){
        const cell=$('#board').children[index];cell.classList.remove('wrong');void cell.offsetWidth;cell.classList.add('wrong');cell.addEventListener('animationend',()=>cell.classList.remove('wrong'),{once:true});
      }
      if(ended())gameMessage();
      else status(result.correct?'正解！ ✦ 次の星を見つけよう。':`そこには星を置けません。残機 ${game.lives}。`);
    }
  }catch(e){status(`${e.message} 「通信を再試行」で同じ操作から再開できます。`);}
  finally{sending=false;render();}
}
const input=attachBoardInput($('#board'),{
  blocked:()=>busy||ended(),size:()=>puzzle.size,value:i=>waiting(i)?1:visibleValue(i),mutable,
  snapshot:memoSnapshot,paint:paintMemo,
  render:()=>render(),commit,
  restoreFirstTap:(base,i)=>{
    // Only revert this tap: another star response may have added notes between taps.
    if(cells[i]!==1&&!waiting(i))cells[i]=base[i]===2?2:0;
    for(const move of moveQueue)if(base.suppressed?.[move.request_id]){
      const suppressed=new Set(move.suppressed||[]);
      if(base.suppressed[move.request_id].includes(i))suppressed.add(i);else suppressed.delete(i);
      move.suppressed=[...suppressed];
    }
    const entry=undo.indexOf(base);if(entry!==-1)undo.splice(entry,1);
    // star() renders the restored note and pending star together; no blank intermediate frame.
    save();
  },star
});
$('#retry-moves').onclick=pumpMoves;
window.addEventListener('online',pumpMoves);
document.querySelectorAll('[data-level]').forEach(button=>button.onclick=async()=>{
  if(busy||sending||moveQueue.length)return;level=button.dataset.level==='expert'?expertMode:button.dataset.level;await choose();
});
$('#expert-mode').onclick=async()=>{
  if(busy||sending||moveQueue.length)return;
  level=level==='expert_relaxed'?'expert':'expert_relaxed';await choose();
};
$('#next').onclick=()=>choose(true);$('#advance').onclick=()=>choose(true);$('#overlay-next').onclick=()=>choose(true);
function undoMemo(){
  if(busy||!undo.length||ended())return;
  input.reset();restoreMemos(undo.pop());save();render();
}
$('#undo').onclick=undoMemo;
document.addEventListener('keydown',event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'&&!event.target.closest('input,textarea,[contenteditable]')){event.preventDefault();undoMemo();}
});
$('#reset').onclick=()=>{
  if(busy||ended())return;
  input.reset();const prev=memoSnapshot();for(let i=0;i<cells.length;i++)paintMemo(i,0);commit(prev);status('メモを消しました。残機と確定した星はそのままです。');
};
$('#auto-cross').onclick=()=>{
  autoCross=!autoCross;try{localStorage.setItem('star-auto-cross',String(autoCross));}catch{}
  if(game&&!ended()){input.reset();const prev=memoSnapshot();autoMark();commit(prev);}else if(game)render();
  else{$('#auto-cross').textContent=`自動で× ${autoCross?'ON':'OFF'}`;$('#auto-cross').setAttribute('aria-pressed',String(autoCross));}
};
function row(container, position, title, detail, points, mine=false) {
  const el=document.createElement('div');el.className='list-row'+(mine?' mine':'');
  const pos=Object.assign(document.createElement('span'),{className:'position',textContent:position});
  const name=Object.assign(document.createElement('div'),{className:'row-name',textContent:title});
  name.append(Object.assign(document.createElement('small'),{textContent:detail}));
  el.append(pos,name,Object.assign(document.createElement('strong'),{textContent:`${points} pt`}));container.append(el);
}
function empty(container,text) {container.append(Object.assign(document.createElement('p'),{className:'empty',textContent:text}));}
let rankingPeriod='daily',rankingRequest=0,rankingDay=null;
function japanDay(){return Math.floor((Date.now()+9*3600000)/86400000);}
async function loadRanking(){
  const request=++rankingRequest,period=rankingPeriod,container=$('#ranking-list');
  rankingDay=japanDay();
  document.querySelectorAll('[data-ranking]').forEach(button=>{
    button.classList.toggle('selected',button.dataset.ranking===period);
    attribute(button,'aria-pressed',String(button.dataset.ranking===period));
  });
  text($('#ranking-description'),period==='daily'?'今日の獲得ポイント順・日本時間0時更新・上位100人':'累計ポイント順・上位100人');
  container.replaceChildren();empty(container,'読み込み中…');attribute(container,'aria-busy','true');
  try{
    const rows=await api(`ranking?period=${period}`);
    if(request!==rankingRequest)return;
    container.replaceChildren();
    rows.forEach((p,i)=>row(container,String(i+1).padStart(2,'0'),p.name,`${p.clears} 問クリア${p.id===me?.id?' · あなた':''}`,p.points,p.id===me?.id));
    if(!rows.length)empty(container,period==='daily'?'今日のクリアはまだありません。最初の星を集めよう。':'まだ記録がありません。最初の星を集めよう。');
  }catch(e){if(request===rankingRequest){container.replaceChildren();empty(container,e.message);}}
  finally{if(request===rankingRequest)attribute(container,'aria-busy','false');}
}
document.querySelectorAll('[data-ranking]').forEach(button=>button.onclick=()=>{
  rankingPeriod=button.dataset.ranking;loadRanking();
});
function refreshDaily(){
  if(!document.hidden&&!$('#ranking').hidden&&rankingPeriod==='daily'&&rankingDay!==japanDay())loadRanking();
}
setInterval(refreshDaily,1000);
document.addEventListener('visibilitychange',refreshDaily);
async function showTab(tab) {
  document.querySelectorAll('.tab').forEach(s=>s.hidden=s.id!==tab);
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  if(tab==='play')return;
  if(tab==='ranking'){await loadRanking();return;}
  const container=$(`#${tab}-list`);container.replaceChildren();empty(container,'読み込み中…');
  try {
    if(!me){container.replaceChildren();empty(container,'名前を登録すると、クリア記録がここに表示されます。');return;}
    const rows=await api('history');container.replaceChildren();
    rows.forEach(p=>row(container,'✦',`${label[p.difficulty]} / ${p.puzzle_id.slice(0,8).toUpperCase()}`,`${new Date(p.cleared_at*1000).toLocaleDateString('ja-JP')} · ${Math.floor(p.seconds/60)}分${p.seconds%60}秒 · ミス${p.mistakes}回`,p.points));
    if(!rows.length)empty(container,'まだクリア記録がありません。最初の一問に挑戦しよう。');
  } catch(e) {container.replaceChildren();empty(container,e.message);}
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function updateTimer() {
  if(!game)return;
  const seconds=(game.completed || game.game_over)?game.seconds:Math.max(0,Math.floor(Date.now()/1000-game.started_at));
  text($('#timer'),`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`);
}
setInterval(updateTimer,1000);
(async()=>{
  try {me=await api('me');profileView();await choose();}
  catch(e) {if(e.status===401)openProfile();else status(e.message);}
})();
