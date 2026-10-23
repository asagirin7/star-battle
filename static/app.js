'use strict';
const $ = s => document.querySelector(s);
const colors = ['#b8c8df','#e7c4ae','#c5d4b4','#d2bfde','#e4d59f','#a9d2d2','#dbb6c4','#c0c1e4','#9cc8a0'];
const hintLabels={star_exclusion:'確定星から除外',single_candidate:'残り1マス',region_to_line:'領域→行・列',line_to_region:'行・列→領域',same_region_intersection:'同じ領域の交点',n_to_n:'排他',shape_exclusion:'候補の形'};
const label = {easy:'EASY', medium:'MEDIUM', hard:'HARD', expert:'EXPERT', expert_relaxed:'9 × 9 / 8 × 8相当'};
let me=null,level='easy',puzzle=null,game=null,cells=[],undo=[],busy=false;
let moveQueue=[],sending=false,pendingStart=null,autoCross=false,autoPreview=new Set();
let celebration=null,expertMode='expert';
let hintLoading=false,hintAttempt=null,hintDisplay=null,hintMessageContext=null;
let launchPending=false,launchRefreshing=false,accountRefreshing=false;
let accountMode='register',sharedId=new URLSearchParams(location.search).get('p');
let memoBase=[],memoTimer=null,memoPromise=null;
let sharedClearId=new URLSearchParams(location.search).get('c'),shareMessage='';
const dismissedResults=new Set();
const memoValue=v=>v===2||v===3?v:0;
function baseKey(){return savedKey()+':synced';}
function importMergedNotes(){
  for(const oldId of me?.legacy_player_ids||[]){
    for(const prefix of ['star-battle:','star-queue:']){
      const oldPrefix=prefix+oldId+':',entries=[];
      try{
        for(let i=0;i<localStorage.length;i++){
          const key=localStorage.key(i);
          if(key?.startsWith(oldPrefix)&&!key.endsWith(':synced'))entries.push([key,localStorage.getItem(key)]);
        }
        for(const [key,value] of entries){
          const newKey=prefix+me.id+':'+key.slice(oldPrefix.length);
          if(localStorage.getItem(newKey)===null)localStorage.setItem(newKey,value);
        }
      }catch{}
    }
  }
}

function localSave(){
  try{
    localStorage.setItem(savedKey(),JSON.stringify(cells.map(memoValue)));
    if(me?.username)localStorage.setItem(baseKey(),JSON.stringify(memoBase));
  }catch{}
}
function hasMemoChanges(){return cells.some((v,i)=>memoValue(v)!==(memoBase[i]||0));}
async function flushMemos(){
  clearTimeout(memoTimer);
  if(memoPromise){await memoPromise;return flushMemos();}
  if(!me?.username||!game||!hasMemoChanges())return;
  const id=game.id,owner=me.id,sent=cells.map(memoValue),changes={};
  sent.forEach((v,i)=>{if(v!==(memoBase[i]||0))changes[i]=v;});
  memoPromise=(async()=>{
    const result=await api('games/'+id+'/memos',{changes});
    if(game?.id!==id||me?.id!==owner)return;
    cells=cells.map((v,i)=>v===1||memoValue(v)!==sent[i]?v:result.memos[i]);
    memoBase=result.memos;game.memo_revision=result.memo_revision;
    localSave();render();
  })();
  try{await memoPromise;}finally{memoPromise=null;}
}
function scheduleMemos(){
  if(!me?.username||!game)return;
  clearTimeout(memoTimer);
  memoTimer=setTimeout(()=>flushMemos().catch(()=>status('メモはこの端末に保存しています。通信回復後に同期します。')),350);
}
function loadServerMemos(state){
  if(!me?.username)return;
  const server=state.memos||Array(cells.length).fill(0);
  let base=null;
  try{base=JSON.parse(localStorage.getItem(baseKey()));}catch{}
  if(Array.isArray(base)&&base.length===cells.length){
    cells=cells.map((v,i)=>memoValue(v)!==base[i]?v:server[i]);
  }else if(state.memos){cells=server.slice();}
  memoBase=server.slice();localSave();
  if(hasMemoChanges())scheduleMemos();
}

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
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', keepalive:true, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (!response.ok) {
    let message = '通信に失敗しました。もう一度お試しください。',code;
    try { const error = await response.json(); if (typeof error.detail === 'string') message = error.detail; else if(error.detail?.message){message=error.detail.message;code=error.detail.code;} } catch {}
    const e = new Error(message); e.status = response.status;e.code=code; throw e;
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
  hintView();
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
$('#profile-login').onclick=()=>{$('#profile-dialog').close();accountView('login');$('#account-dialog').showModal();};
$('#close-profile').onclick = () => $('#profile-dialog').close();
$('#profile-form').onsubmit = async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  try {
    me = await api('profile', {name:$('#name').value}); profileView(); $('#profile-dialog').close();
    if(sharedId)await startShared();else if (!game) await choose();
  } catch (e) { $('#profile-error').textContent = e.message; }
  finally { submit.disabled = false; }
};
function savedKey() { return `star-battle:${me.id}:${game.id}`; }
function queueKey() { return `star-queue:${me.id}:${game.id}`; }
function save() {localSave();saveQueue();scheduleMemos();}
function saveQueue() { try {localStorage.setItem(queueKey(),JSON.stringify(moveQueue));} catch {} }
function waiting(i) {return moveQueue.some(m=>m.row*puzzle.size+m.col===i);}
function ended() {return !game || game.completed || game.game_over;}
function mutable(i) {return !hintLoading && !launchRefreshing && !busy && !ended() && cells[i]!==1 && !waiting(i);}
function memoSnapshot(){
  const snapshot=cells.slice();
  snapshot.suppressed=Object.fromEntries(moveQueue.map(m=>[m.request_id,[...(m.suppressed||[])]]));
  return snapshot;
}
function restoreMemos(snapshot){
  cells=cells.map((v,i)=>v===1?1:snapshot[i]===2||snapshot[i]===3?snapshot[i]:0);
  for(const move of moveQueue)if(snapshot.suppressed?.[move.request_id])move.suppressed=[...snapshot.suppressed[move.request_id]];
}
function forbidden(row,col,i){
  const r=Math.floor(i/puzzle.size),c=i%puzzle.size;
  return r===row||c===col||puzzle.regions[r][c]===puzzle.regions[row][col]||(Math.abs(r-row)<=1&&Math.abs(c-col)<=1);
}
function visibleValue(i){return cells[i]===1?1:cells[i]===3?3:cells[i]===2||autoPreview.has(i)?2:0;}
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
  if(!loadMemos&&me?.username&&state.memos&&state.memo_revision!==game?.memo_revision){
    cells=cells.map((v,i)=>v===1||memoValue(v)!==(memoBase[i]||0)?v:state.memos[i]);
    memoBase=state.memos.slice();
  }
  game=state;puzzle=state.puzzle;level=puzzle.difficulty;
  try{
    localStorage.setItem('star-level',level);
    if(puzzle.size===9){expertMode=level;localStorage.setItem('star-expert-mode',level);}
  }catch{}
  if(loadMemos) {
    try{if(localStorage.getItem(savedKey()+':result-hidden')==='true')dismissedResults.add(game.id);}catch{}
    cells=Array(puzzle.size**2).fill(0);undo=[];moveQueue=[];
    try {const stored=JSON.parse(localStorage.getItem(savedKey()));if(Array.isArray(stored)&&stored.length===cells.length)cells=stored.map(v=>v===2||v===3?v:0);} catch {}
    loadServerMemos(state);
    try {
      const stored=JSON.parse(localStorage.getItem(queueKey()));
      if(Array.isArray(stored))moveQueue=stored.filter(m=>Number.isInteger(m.row)&&Number.isInteger(m.col)&&m.row>=0&&m.col>=0&&m.row<puzzle.size&&m.col<puzzle.size&&typeof m.request_id==='string');
      // Resume an operation saved by the previous version as well.
      const oldKey=`star-pending:${me.id}:${game.id}`,old=JSON.parse(localStorage.getItem(oldKey));
      if(old&&!moveQueue.length)moveQueue=[old];localStorage.removeItem(oldKey);
    } catch {}
  }
  cells=cells.map(v=>v===2||v===3?v:0);
  game.stars.forEach(([r,c])=>cells[r*puzzle.size+c]=1);
  if(ended()){moveQueue=[];saveQueue();}
  document.querySelectorAll('[data-level]').forEach(b=>b.classList.toggle('selected',(b.dataset.level===level||(b.dataset.level==='expert'&&level==='expert_relaxed'))));
  if(draw)render();
}
function hintContext(){
  if(!game)return '';
  return JSON.stringify([me?.id,game.id,game.stars,cells.flatMap((v,i)=>v===2?[i]:[])]);
}
function hintView(){
  const context=hintContext();
  if(hintMessageContext!==null&&hintMessageContext!==context){
    hintDisplay=null;hintMessageContext=null;
    text($('#hint-message'),'根拠と次の一手を示します。星や×は自動で入りません。');
    $('#hint-legend').hidden=true;
  }
  text($('#hint-balance'),`残り ${Number.isInteger(me?.hints)?me.hints:'—'} 回`);
  text($('#streak'),`${label[level]} 連続クリア ${me?.streaks?.[level]||0} 問`);
  text($('#hint'),hintLoading?'ヒントを確認中…':'ヒントを見る');
}
$('#hint').onclick=async()=>{
  if(hintLoading||launchRefreshing||busy||sending||moveQueue.length||ended()||!(me?.hints>0))return;
  input.reset();
  const context=hintContext(),owner=me.id,id=game.id;
  if(hintAttempt?.context!==context){
    const key='star-hint:'+owner+':'+id;
    let stored=null;try{stored=JSON.parse(sessionStorage.getItem(key));}catch{}
    hintAttempt=stored?.context===context?stored:{context,request_id:requestId()};
    try{sessionStorage.setItem(key,JSON.stringify(hintAttempt));}catch{}
  }
  hintLoading=true;hintMessageContext=context;hintView();controls();
  text($('#hint-message'),'今の盤面から使える手を確認しています…');
  try{
    const result=await api('hints',{game_id:id,request_id:hintAttempt.request_id,crosses:cells.flatMap((v,i)=>v===2?[i]:[])});
    if(me?.id!==owner)return;
    me.hints=result.balance;
    if(context!==hintContext())return;
    hintDisplay={context,hint:result.hint};
    const targets=result.hint.target_cells.map(([r,c])=>`${r+1}行${c+1}列`).join('、');
    text($('#hint-message'),`${hintLabels[result.hint.technique]||result.hint.technique}（難易度点 ${result.hint.points}）\n${result.hint.explanation}\n次の一手：${targets}に${result.hint.action==='star'?'星を置けます':'×を付けられます'}。`);
    $('#hint-legend').hidden=false;
  }catch(e){
    if(context===hintContext())text($('#hint-message'),e.message);
    // Retry a failed connection with the same ID, including after reload.
    if(e.status&&e.status<500){hintAttempt=null;try{sessionStorage.removeItem('star-hint:'+owner+':'+id);}catch{}}
    if(e.status===409){
      try{const fresh=await api('me?launch=false');if(me?.id===owner){me=fresh;profileView();}}catch{}
    }
  }finally{hintLoading=false;render();}
};
function rewardMessage() {
  if(game.retries)return `リトライ${game.retries}回・クリア +0 pt`;
  return puzzle.scoring==='fixed'?`ノーミスクリア！ +${game.score} pt`:`残機 ${game.lives} × ${puzzle.multiplier} = +${game.score} pt`;
}
function gameMessage() {
  if(game.completed)status(`クリア！ ✦ ${rewardMessage()}。次の盤面に挑戦しよう。`,true);
  else if(game.game_over)status(`ゲームオーバー。リトライ${game.retries||0}回。同じ盤面を0点でリトライできます。`);
  else if(game.retries)status(`リトライ${game.retries}回・この挑戦のクリアは0 pt。`);
  else status((puzzle.scoring==='fixed'?`9×9は1ミスで終了、クリアで${puzzle.points} pt。`:'')+'1回タップで×、2回タップで★。ドラッグで×を付け外し。');
}
function controls() {
  const changing=busy||hintLoading||launchRefreshing||sending||moveQueue.length>0;
  for(const selector of ['#retry-board','#overlay-retry','#advance','#overlay-next','#expert-mode', '[data-level="easy"]','[data-level="medium"]','[data-level="hard"]','[data-level="expert"]']) disabled($(selector),changing);
  disabled($('#undo'),busy||hintLoading||launchRefreshing||ended()||!undo.length);
  disabled($('#reset'),busy||hintLoading||launchRefreshing||ended());
  disabled($('#hint'),changing||ended()||!me||!(me.hints>0));
  disabled($('#auto-cross'),hintLoading);
  $('#retry-moves').hidden=!moveQueue.length||sending;
}
async function choose(next=false) {
  if(!me){openProfile();return;}
  if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)return;
  busy=true;controls();
  const previousLevel=game?.puzzle.difficulty;
  try {
    await flushMemos();
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
  const matches=coords=>coords?.some(([row,col])=>row===r&&col===c);
  button.classList.toggle('hint-source',Boolean(matches(hintDisplay?.hint.source_cells)));
  button.classList.toggle('hint-target',Boolean(matches(hintDisplay?.hint.target_cells)));
  button.classList.toggle('pending',pending);
  button.classList.toggle('marked',value===2&&!pending);
  const glyph=value===1||pending?'★':value===2?'×':value===3?'⚑':'';
  const mark=button.firstElementChild;
  if(mark.textContent!==glyph)mark.textContent=glyph;
  const markClass=value===2&&!pending?'mark':value===3&&!pending?'flag':'';
  if(mark.className!==markClass)mark.className=markClass;
  attribute(button,'aria-label',`${r+1}行${c+1}列、エリア${puzzle.regions[r][c]+1}、${value===1?'確定した星':pending?'星を確認中':value===2?'除外':value===3?'旗':'空白'}${matches(hintDisplay?.hint.source_cells)?'、ヒントの根拠':''}${matches(hintDisplay?.hint.target_cells)?'、ヒントの次の一手':''}`);
}
function render() {
  if(!puzzle)return;
  hintView();
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
  text($('#share-puzzle'),game.completed?'クリア結果を共有':'盤面を共有');
  text($('#advance'),game.completed?'次の盤面に挑戦 →':game.game_over?'新しい盤面で再挑戦 →':'新しい盤面に挑戦 →');
  const result=$('#game-over');
  result.hidden=!(game.completed||game.game_over)||dismissedResults.has(game.id);
  $('#dismiss-result').hidden=!game.game_over;
  $('#overlay-share').hidden=!game.completed;
  $('#retry-board').hidden=!game.game_over||game.completed;
  $('#overlay-retry').hidden=!game.game_over||game.completed;
  result.classList.toggle('cleared',game.completed);
  text($('#result-title'),game.completed?'クリア！ ✦':'ゲームオーバー');
  text($('#result-message'),game.completed?rewardMessage():'次の盤面で、もう一度。');
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
  let replaceInvalid=false;
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
  }catch(e){
    if(e.code==='invalid_puzzle'){moveQueue=[];saveQueue();replaceInvalid=true;status(e.message);}
    else status(`${e.message} 「通信を再試行」で同じ操作から再開できます。`);
  }
  finally{sending=false;render();}
  if(replaceInvalid){
    const oldGame=game.id;await choose(true);
    if(game.id!==oldGame)status('盤面を再検証し、新しい盤面に切り替えました。ミスには数えていません。');
  }
}
const input=attachBoardInput($('#board'),{
  blocked:()=>busy||hintLoading||launchRefreshing||ended(),size:()=>puzzle.size,value:i=>waiting(i)?1:visibleValue(i),mutable,
  snapshot:memoSnapshot,paint:paintMemo,
  flag:i=>{const prev=memoSnapshot();paintMemo(i,cells[i]===3?0:3);commit(prev);},
  render:()=>render(),commit,
  restoreFirstTap:(base,i)=>{
    // Only revert this tap: another star response may have added notes between taps.
    if(cells[i]!==1&&!waiting(i))cells[i]=base[i]===2||base[i]===3?base[i]:0;
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
  if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)return;level=button.dataset.level==='expert'?expertMode:button.dataset.level;await choose();
});
$('#expert-mode').onclick=async()=>{
  if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)return;
  level=level==='expert_relaxed'?'expert':'expert_relaxed';await choose();
};
$('#dismiss-result').onclick=()=>{
  if(!game?.game_over)return;
  dismissedResults.add(game.id);
  try{localStorage.setItem(savedKey()+':result-hidden','true');}catch{}
  render();status('ゲームオーバー。盤面を確認できます。同じ盤面をリトライするか、新しい盤面へ進めます。');
  $('#advance').focus({preventScroll:true});
};
async function retryBoard(){
  if(busy||hintLoading||launchRefreshing||sending||moveQueue.length||!game?.game_over)return;
  busy=true;controls();
  try{
    await flushMemos();
    const state=await api('games/'+game.id+'/retry',{});
    applyGame(state,true);gameMessage();
  }catch(e){status(e.message);}finally{busy=false;controls();}
}
$('#retry-board').onclick=retryBoard;$('#overlay-retry').onclick=retryBoard;
$('#advance').onclick=()=>choose(true);$('#overlay-next').onclick=()=>choose(true);
function undoMemo(){
  if(busy||hintLoading||launchRefreshing||!undo.length||ended())return;
  input.reset();restoreMemos(undo.pop());save();render();
}
$('#undo').onclick=undoMemo;
document.addEventListener('keydown',event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'&&!event.target.closest('input,textarea,[contenteditable]')){event.preventDefault();undoMemo();}
});
$('#reset').onclick=()=>{
  if(busy||hintLoading||launchRefreshing||ended())return;
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
async function resumeOrChoose(){
  if(me?.username&&!game){
    const state=await api('account/resume');
    if(state){applyGame(state,true);gameMessage();controls();if(moveQueue.length)pumpMoves();return;}
  }
  await choose();
}
async function migrateGuestMemos(){
  // Upgrade notes for every locally played difficulty, preserving the guest's Player ID.
  const prefix='star-battle:'+me.id+':',saved=[];
  for(let i=0;i<localStorage.length;i++){
    const key=localStorage.key(i);
    if(key?.startsWith(prefix)&&/^[a-f0-9-]{36}$/.test(key.slice(prefix.length))){
      try{
        const notes=JSON.parse(localStorage.getItem(key));
        if(Array.isArray(notes))saved.push([key.slice(prefix.length),notes]);
      }catch{}
    }
  }
  let complete=true;
  for(const [id,notes] of saved){
    const changes={};notes.forEach((v,i)=>{if(v===2||v===3)changes[i]=v;});
    if(Object.keys(changes).length){
      try{await api('games/'+id+'/memos',{changes});}catch(e){if(e.status!==404)complete=false;}
    }
  }
  return complete;
}
function accountView(mode=accountMode){
  accountMode=mode;
  const registered=Boolean(me?.username),login=mode==='login';
  $('#account-state').textContent=registered?'ログイン中: '+me.username:'今の得点・記録を残したままアカウントにできます。';
  $('#account-form').hidden=registered;$('#account-manage').hidden=!registered;$('#account-tabs').hidden=registered;
  $('#password-confirm').hidden=login;$('#password-confirm-label').hidden=login;$('#password-confirm').required=!login;
  $('#account-password').autocomplete=login?'current-password':'new-password';
  $('#account-submit').textContent=login?'ログイン':'今の記録でアカウント登録';
  $('#account-help').textContent=login?'登録したIDで別端末から続けられます。現在のゲスト記録との統合は行いません。':'メール登録は不要です。パスワードを忘れた場合の再発行はできないため、パスワード管理アプリ等に保存してください。';
  document.querySelectorAll('[data-account-mode]').forEach(b=>b.classList.toggle('selected',b.dataset.accountMode===mode));
}
$('#account-button').onclick=()=>{accountView();$('#account-error').textContent='';$('#account-dialog').showModal();};
$('#close-account').onclick=()=>$('#account-dialog').close();
document.querySelectorAll('[data-account-mode]').forEach(b=>b.onclick=()=>{accountView(b.dataset.accountMode);$('#account-error').textContent='';});
$('#account-form').onsubmit=async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  let warning='';
  try{
    if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)throw new Error('盤面の操作が終わってからお試しください。');
    if(accountMode==='register'&&$('#account-password').value!==$('#password-confirm').value)throw new Error('パスワードが一致しません。');
    await flushMemos();
    if(accountMode==='register'&&!me)me=await api('profile',{name:$('#login-id').value.slice(0,24)});
    const previous=me?.id;
    me=await api('account/'+accountMode,{username:$('#login-id').value,password:$('#account-password').value});
    importMergedNotes();
    if(accountMode==='register'&&!await migrateGuestMemos())warning='登録しました。一部のメモはこの端末に残っています。元の端末でその盤面を開くと再同期します。';
    profileView();$('#account-form').reset();$('#account-dialog').close();
    if(previous===me.id&&game){memoBase=game.memos||Array(cells.length).fill(0);await flushMemos();}
    else{input.reset();game=null;puzzle=null;cells=[];undo=[];moveQueue=[];memoBase=[];pendingStart=null;}
    if(sharedId)await startShared();else if(!game)await resumeOrChoose();
    status(warning||'ログインしました。別端末でも同じIDで続けられます。',true);
  }catch(e){if(me?.username){profileView();accountView();}$('#account-error').textContent=e.message;}
  finally{button.disabled=false;}
};
$('#password-form').onsubmit=async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{
    await api('account/password',{current_password:$('#old-password').value,new_password:$('#new-password').value});
    $('#password-form').reset();$('#account-error').textContent='変更しました。他の端末では再ログインしてください。';
  }catch(e){$('#account-error').textContent=e.message;}finally{button.disabled=false;}
};
$('#logout').onclick=async()=>{
  const button=$('#logout');button.disabled=true;
  try{
    if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)throw new Error('星の送信が終わってからログアウトしてください。');
    await flushMemos();await api('account/logout',{});location.reload();
  }catch(e){$('#account-error').textContent=e.message;}finally{button.disabled=false;}
};
$('#share-puzzle').onclick=async()=>{
  if(!puzzle)return;
  const current=game.id,url=new URL('/',location.origin);url.searchParams.set('p',puzzle.id);
  if(game.completed&&game.clear_id)url.searchParams.set('c',game.clear_id);
  shareMessage=puzzle.size+' × '+puzzle.size+'の盤面に挑戦！';
  $('#share-title').textContent='この盤面をシェア';$('#result-share-text').hidden=true;$('#copy-result').hidden=true;
  $('#share-url').value=url.href;$('#share-link').href=url.href;$('#share-link').textContent=url.href;
  $('#share-status').textContent='リンクをコピーするか、URLを長押しして共有できます。';
  $('#native-share').hidden=typeof navigator.share!=='function';
  $('#native-share').disabled=Boolean(game.completed);
  $('#share-dialog').showModal();
  if(game.completed){
    $('#share-status').textContent='公式のクリア結果を確認しています…';
    try{
      if(!game.clear_id)throw new Error('クリア結果を取得できませんでした。');
      const verifiedClear=await api('clears/'+game.clear_id);
      if(game.id!==current||!$('#share-dialog').open)return;
      if(verifiedClear.puzzle.id!==puzzle.id)throw new Error('クリア結果と盤面が一致しません。');
      url.searchParams.set('c',verifiedClear.id);
      shareMessage=`Star Battle ${verifiedClear.puzzle.size}×${verifiedClear.puzzle.size}を${verifiedClear.seconds}秒でクリア！ ${verifiedClear.points}pt・リトライ${verifiedClear.retries||0}回`;
      $('#share-title').textContent='クリア結果をシェア';
      $('#share-url').value=url.href;$('#share-link').href=url.href;$('#share-link').textContent=url.href;
      $('#result-share-text').value=shareMessage+'\n'+url.href;$('#result-share-text').hidden=false;$('#copy-result').hidden=false;
      $('#share-status').textContent='公式のクリア秒数付きで共有できます。';
      $('#native-share').disabled=false;
    }catch(e){
      if(game.id===current){
        url.searchParams.delete('c');
        $('#share-url').value=url.href;$('#share-link').href=url.href;$('#share-link').textContent=url.href;
        $('#native-share').disabled=false;
        $('#share-status').textContent=e.message+' 盤面のURLは共有できます。';
      }
    }
  }
};
$('#overlay-share').onclick=()=>$('#share-puzzle').onclick();
function selectShareUrl(){
  const input=$('#share-url');input.focus();input.select();input.setSelectionRange(0,input.value.length);
}
$('#share-url').onclick=selectShareUrl;
async function copyShare(button,input){
  button.disabled=true;
  let copied=false;
  const select=()=>{input.focus();input.select();input.setSelectionRange(0,input.value.length);};
  try{
    if(typeof navigator.clipboard?.writeText==='function'){
      try{await navigator.clipboard.writeText(input.value);copied=true;}catch{}
    }
    if(!copied){select();try{copied=document.execCommand('copy')===true;}catch{}}
    if(copied)$('#share-status').textContent='コピーしました。リンクを相手に送ってください。';
    else{select();$('#share-status').textContent='自動コピーできませんでした。選択した内容を長押し、またはコピー操作で持ち出してください。表示中のリンクも長押しできます。';}
  }finally{button.disabled=false;}
}
$('#copy-share').onclick=()=>copyShare($('#copy-share'),$('#share-url'));
$('#copy-result').onclick=()=>copyShare($('#copy-result'),$('#result-share-text'));
$('#native-share').onclick=async()=>{
  try{await navigator.share({title:'Star Battle',text:shareMessage,url:$('#share-url').value});}
  catch(e){$('#share-status').textContent=e.name==='AbortError'?'共有をキャンセルしました。表示中のURLも利用できます。':'共有メニューを開けませんでした。表示中のURLをコピーしてください。';}
};
$('#close-share').onclick=()=>$('#share-dialog').close();
async function previewShared(){
  try{
    if(!/^[a-f0-9]{32}$/.test(sharedId))throw new Error('共有URLが正しくありません。');
    const shared=await api('puzzles/'+sharedId);
    $('#shared-title').textContent='共有された盤面';
    $('#shared-result').textContent='';
    if(sharedClearId){
      try{
        if(!/^[a-f0-9-]{36}$/.test(sharedClearId))throw new Error('クリア結果のURLが正しくありません。');
        const result=await api('clears/'+sharedClearId);
        if(result.puzzle.id!==sharedId)throw new Error('クリア結果と盤面が一致しません。');
        $('#shared-title').textContent='共有されたクリア結果';
        $('#shared-result').textContent=`${result.name}：${result.seconds}秒でクリア！ ${result.points}pt・リトライ${result.retries||0}回`;
      }catch{ $('#shared-result').textContent='このクリア結果は確認できません。盤面には挑戦できます。'; }
    }
    $('#shared-description').textContent=shared.size+' × '+shared.size+' / クリア最大 '+shared.points+' pt。同じ盤面に挑戦します。以前遊んだ盤面なら自分の続きから再開します。';
    $('#shared-dialog').showModal();
  }catch(e){sharedId=null;sharedClearId=null;history.replaceState(null,'','/');status(e.message);if(me)await choose();else openProfile();}
}
async function startShared(){
  if(!sharedId)return;
  if(!me){$('#shared-dialog').close();openProfile();return;}
  if(busy||hintLoading||launchRefreshing||sending||moveQueue.length)throw new Error('星の送信が終わってから盤面を開いてください。');
  busy=true;controls();
  try{
    await flushMemos();
    const state=await api('games',{request_id:requestId(),puzzle_id:sharedId});
    applyGame(state,true);gameMessage();$('#shared-dialog').close();
    sharedId=null;sharedClearId=null;history.replaceState(null,'','/');
  }finally{busy=false;controls();}
}
$('#play-shared').onclick=()=>startShared().catch(e=>{$('#shared-description').textContent=e.message;});
$('#close-shared').onclick=()=>{sharedId=null;sharedClearId=null;history.replaceState(null,'','/');$('#shared-dialog').close();if(me)choose();else openProfile();};
$('#shared-dialog').addEventListener('cancel',()=>{sharedId=null;sharedClearId=null;history.replaceState(null,'','/');if(me)choose();else openProfile();});
async function refreshAccountGame(){
  if(accountRefreshing||!me?.username||!game||document.hidden||busy||hintLoading||launchRefreshing||sending||moveQueue.length||memoPromise)return;
  accountRefreshing=true;
  try{
    await flushMemos();
    const id=game.id,state=await api('games/'+game.id);
    if(game.id!==id||busy||hintLoading||launchRefreshing||sending||moveQueue.length)return;
    if(state.memo_revision!==game.memo_revision){
      const server=state.memos||Array(cells.length).fill(0);
      cells=cells.map((v,i)=>memoValue(v)!==(memoBase[i]||0)?v:server[i]);
      memoBase=server.slice();
    }
    applyGame(state);localSave();me=await api('me?launch=false');profileView();controls();
  }catch{}finally{accountRefreshing=false;}
}
async function refreshLaunch(){
  if(!launchPending||launchRefreshing||accountRefreshing||document.hidden||!me||busy||hintLoading||sending||moveQueue.length||memoPromise)return;
  launchPending=false;launchRefreshing=true;controls();
  const owner=me.id;
  try{
    const fresh=await api('me');
    if(me?.id===owner){me=fresh;profileView();}
  }catch{launchPending=true;}
  finally{launchRefreshing=false;controls();}
  await refreshAccountGame();
}
setInterval(()=>{if(launchPending)refreshLaunch();else refreshAccountGame();},10000);
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){flushMemos().catch(()=>{});}
  else{launchPending=true;refreshLaunch();}
});
window.addEventListener('online',()=>{flushMemos().catch(()=>{});});
(async()=>{
  try {me=await api('me');importMergedNotes();profileView();if(sharedId)await previewShared();else await resumeOrChoose();}
  catch(e) {if(e.status===401){if(sharedId)await previewShared();else openProfile();}else status(e.message);}
})();
