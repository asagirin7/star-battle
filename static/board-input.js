'use strict';
// Same gestures as the Trameria game. Keep all pointer handling on stable cells.
window.attachBoardInput = function(board, actions) {
  const DOUBLE_MS = 320;
  let drag = null, lastTap = null;
  const cellAt = event => {
    const el = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-index]');
    return el && board.contains(el) ? Number(el.dataset.index) : -1;
  };
  function finish(cancelled=false) {
    if (!drag) return;
    const d = drag; drag = null;
    if (board.hasPointerCapture(d.pointerId)) board.releasePointerCapture(d.pointerId);
    if (d.moved) { lastTap = null; actions.commit(d.prev); }
    else if(cancelled) lastTap = null;
  }
  function paint(i) {
    if (!actions.mutable(i)) return;
    actions.paint(i, drag.mode);
  }
  board.addEventListener('pointerdown', event => {
    if (!event.isPrimary) { finish(true); lastTap=null; return; }
    if (event.button!==0 || actions.blocked()) return;
    const i=cellAt(event); if(i<0)return;
    event.preventDefault();
    drag={start:i, last:i, moved:false, prev:actions.snapshot(),
          mode:actions.value(i)===2?0:2, pointerId:event.pointerId};
    board.setPointerCapture(event.pointerId);
  });
  board.addEventListener('pointermove', event => {
    if(!drag || event.pointerId!==drag.pointerId)return;
    event.preventDefault();
    const i=cellAt(event);if(i<0 || i===drag.last)return;
    if(!drag.moved){drag.moved=true;lastTap=null;paint(drag.start);}
    const n=actions.size(),r0=Math.floor(drag.last/n),c0=drag.last%n,r1=Math.floor(i/n),c1=i%n;
    const steps=Math.max(Math.abs(r1-r0),Math.abs(c1-c0));
    for(let s=1;s<=steps;s++)paint(Math.round(r0+(r1-r0)*s/steps)*n+Math.round(c0+(c1-c0)*s/steps));
    drag.last=i;actions.render();
  });
  board.addEventListener('pointerup', event => {
    if(!drag || event.pointerId!==drag.pointerId)return;
    event.preventDefault();
    const d=drag,i=cellAt(event);
    if(d.moved || i!==d.start){finish(i!==d.start);return;}
    finish();
    if(!actions.mutable(i)){lastTap=null;return;}
    const now=performance.now();
    if(lastTap && lastTap.i===i && now-lastTap.at<DOUBLE_MS){
      const base=lastTap.prev;lastTap=null;
      actions.restoreFirstTap(base,i);actions.star(i);return;
    }
    actions.paint(i,actions.value(i)===2?0:2);
    actions.commit(d.prev);lastTap={i,at:now,prev:d.prev};
  });
  for(const name of ['pointercancel','lostpointercapture'])board.addEventListener(name,()=>finish(true));
  board.addEventListener('contextmenu', event => {
    event.preventDefault();if(actions.blocked())return;
    const i=cellAt(event);if(i<0 || !actions.mutable(i))return;
    finish(true);lastTap=null;actions.star(i);
  });
  board.addEventListener('keydown', event => {
    const button=event.target.closest('[data-index]');if(!button || actions.blocked())return;
    const i=Number(button.dataset.index),n=actions.size();
    const delta={ArrowUp:-n,ArrowDown:n,ArrowLeft:-1,ArrowRight:1}[event.key];
    if(delta!==undefined){event.preventDefault();board.children[Math.max(0,Math.min(n*n-1,i+delta))].focus({preventScroll:true});return;}
    if(event.key===' ' || event.key==='Enter'){
      event.preventDefault();lastTap=null;if(!actions.mutable(i))return;
      if(event.key==='Enter')actions.star(i);
      else{const prev=actions.snapshot();actions.paint(i,actions.value(i)===2?0:2);actions.commit(prev);}
    }
  });
  // Pointer gestures are handled above. Do not also process compatibility click/dblclick.
  board.addEventListener('click', event => event.preventDefault());
  board.addEventListener('dblclick', event => event.preventDefault());
  return {reset(){finish(true);lastTap=null;}};
};
