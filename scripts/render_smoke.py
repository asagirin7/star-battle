"""Sample painted frames during slow star confirmations, checking for flicker."""
import os
import sys
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')

with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,touch in [(390,True),(1280,False)]:
        context=browser.new_context(viewport={'width':width,'height':900},has_touch=touch,is_mobile=touch)
        page=context.new_page()
        page.goto(BASE)
        page.locator('#name').fill(f'描画検証{width}')
        page.get_by_role('button',name='この名前ではじめる').click()
        expect(page.locator('.cell')).to_have_count(36)
        page.locator('#board').scroll_into_view_if_needed()
        game=page.request.get(BASE+'/api/games/current').json()
        cols=solutions(game['puzzle']['regions'])[0]
        targets=[cols[0],6+cols[1]]
        page.evaluate('''indices=>{
          const els=indices.map(i=>document.querySelectorAll('.cell')[i]);
          window.frames=[];window.hudMutations=[];window.sampling=true;
          window.originalCells=els;window.originalHearts=[...document.querySelector('#lives').children];
          window.hudObserver=new MutationObserver(ms=>window.hudMutations.push(...ms.map(m=>m.target.id||m.target.parentElement?.id)));
          for(const id of ['lives','total','clear-count','profile-button'])
            window.hudObserver.observe(document.getElementById(id),{childList:true,subtree:true,characterData:true,attributes:true});
          function sample(){
            window.frames.push({cells:els.map(e=>{const s=getComputedStyle(e);return {glyph:e.textContent,opacity:s.opacity,color:s.color,background:s.backgroundColor,filter:s.filter,pending:e.classList.contains('pending')};}),
              controls:['next','advance'].map(id=>getComputedStyle(document.getElementById(id)).opacity)});
            if(window.sampling)requestAnimationFrame(sample);
          }requestAnimationFrame(sample);
        }''',targets)
        cdp=context.new_cdp_session(page)
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':600,'downloadThroughput':-1,'uploadThroughput':-1})
        for i in targets:
            box=page.locator('.cell').nth(i).bounding_box()
            x,y=box['x']+box['width']/2,box['y']+box['height']/2
            if touch:
                page.touchscreen.tap(x,y);page.wait_for_timeout(60);page.touchscreen.tap(x,y)
            else:page.mouse.dblclick(x,y,delay=60)
        for i in targets:expect(page.locator('.cell').nth(i)).to_have_class('cell locked',timeout=15000)
        page.wait_for_timeout(80)
        data=page.evaluate('''()=>{window.sampling=false;window.hudObserver.disconnect();return {frames:window.frames,hud:window.hudMutations,
          sameCells:window.originalCells.every(e=>e.isConnected),sameHearts:window.originalHearts.every((e,i)=>e===document.querySelector('#lives').children[i])};}''')
        assert data['sameCells']
        for position in range(2):
            frames=[f['cells'][position] for f in data['frames']]
            assert any(f['pending'] for f in frames),'Did not sample network wait'
            first=next(i for i,f in enumerate(frames) if f['glyph']=='★')
            visible=frames[first:]
            assert all(f['glyph']=='★' for f in visible),'Star disappeared before confirmation'
            styles={(f['opacity'],f['color'],f['background'],f['filter']) for f in visible}
            assert len(styles)==1,f'Star appearance changed while confirming: {styles}'
            assert visible[0]['opacity']=='1','Pending star faded the whole cell'
        assert all(f['controls']==['1','1'] for f in data['frames']),'Controls flashed during star placement'
        assert data['sameHearts'],'Unchanged hearts were replaced'
        assert not data['hud'],f'Unchanged score/lives DOM was rewritten: {data["hud"][:10]}'
        assert page.request.get(BASE+'/api/me').json()['points']==0
        context.close()
        print(f'PASS {width}px: pending and confirmed stars have identical paint, stable controls, unchanged HUD nodes, 600ms queued responses')
    browser.close()
