"""Real pointer/touch regression checks for the Trameria-style board controls."""
import os
from pathlib import Path
import sys
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')


def geometry(page):
    return page.locator('.cell').evaluate_all('(els)=>els.map(el=>{const r=el.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})')


def stable(page,before):
    after=geometry(page)
    assert len(after)==len(before)
    assert all(abs(a-b)<.1 for old,new in zip(before,after) for a,b in zip(old,new)), 'Cell geometry changed'
    assert max(r[2] for r in after)-min(r[2] for r in after)<.1
    assert max(r[3] for r in after)-min(r[3] for r in after)<.1
    assert all(abs(r[2]-r[3])<.1 for r in after), 'Cells are not square'
    assert page.evaluate('window.originalCell === document.querySelector(".cell")'), 'Cell DOM was replaced'


with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,touch in [(320,True),(390,True),(1280,False)]:
        context=browser.new_context(viewport={'width':width,'height':900},has_touch=touch,is_mobile=touch)
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE)
        page.locator('#name').fill(f'操作検証{width}')
        page.get_by_role('button',name='この名前ではじめる').click()
        expect(page.locator('.cell')).to_have_count(36)
        page.locator('#board').scroll_into_view_if_needed()
        game=page.request.get(BASE+'/api/games/current').json()
        cols=solutions(game['puzzle']['regions'])[0]
        def point(i):
            box=page.locator('.cell').nth(i).bounding_box()
            return box['x']+box['width']/2,box['y']+box['height']/2
        def tap(i):
            x,y=point(i)
            if touch:page.touchscreen.tap(x,y)
            else:page.mouse.click(x,y)
        def double(i):
            tap(i);page.wait_for_timeout(60);tap(i)
        cdp=context.new_cdp_session(page)
        def stroke(start,end,cancel=False):
            a,b=point(start),point(end)
            if touch:
                cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':a[0],'y':a[1],'id':0}]})
                cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':b[0],'y':b[1],'id':0}]})
                cdp.send('Input.dispatchTouchEvent',{'type':'touchCancel' if cancel else 'touchEnd','touchPoints':[]})
            else:
                page.mouse.move(*a);page.mouse.down();page.mouse.move(*b,steps=1)
                if cancel:page.dispatch_event('#board','pointercancel',{'pointerId':1})
                page.mouse.up()
        page.evaluate('window.originalCell = document.querySelector(".cell")')
        before=geometry(page);scroll=page.evaluate('scrollY')
        def hold(i,cancel=False):
            x,y=point(i)
            if touch:
                cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':0}]})
                page.wait_for_timeout(650)
                cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            else:
                page.mouse.move(x,y);page.mouse.down();page.wait_for_timeout(650);page.mouse.up()
        hold(0);expect(page.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
        stable(page,before)
        hold(0);expect(page.locator('.cell').nth(0)).to_have_text('');expect(page.locator('.cell').nth(0).locator('.flag')).to_have_count(0)
        page.keyboard.press('Control+z')
        expect(page.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
        page.reload();expect(page.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
        page.locator('#board').scroll_into_view_if_needed()
        page.evaluate('window.originalCell = document.querySelector(".cell")')
        before=geometry(page);scroll=page.evaluate('scrollY')
        hold(0);expect(page.locator('.cell').nth(0)).to_have_text('');expect(page.locator('.cell').nth(0).locator('.flag')).to_have_count(0)
        tap(0);expect(page.locator('.cell').nth(0)).to_have_text('×')
        stable(page,before)
        # Fast strokes must paint skipped cells and form one undo step.
        stroke(6,11)
        for i in range(6,12):expect(page.locator('.cell').nth(i)).to_have_text('×')
        stable(page,before)
        assert page.evaluate('scrollY')==scroll
        page.keyboard.press('Control+z')
        for i in range(6,12):expect(page.locator('.cell').nth(i)).to_have_text('')
        # Keyboard undo can scroll only by user focus; return to the board before comparing.
        stable(page,before)
        # The on-screen undo button works on phones without a keyboard.
        tap(13);expect(page.locator('.cell').nth(13)).to_have_text('×')
        page.wait_for_timeout(400)
        page.locator('#undo').click();expect(page.locator('.cell').nth(13)).to_have_text('')
        stroke(6,11);stroke(6,11)
        for i in range(6,12):expect(page.locator('.cell').nth(i)).to_have_text('')
        stroke(12,17,cancel=True)
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 3、ミス 0回')
        page.evaluate('''() => {const prev=memoSnapshot();for(let i=0;i<cells.length;i++)paintMemo(i,0);commit(prev);}''');page.locator('#board').scroll_into_view_if_needed()
        before=geometry(page)
        # Confirmed star response must preserve the same cell nodes and dimensions.
        double(cols[0])
        expect(page.locator('.cell').nth(cols[0])).to_have_class('cell locked')
        stable(page,before)
        page.locator('#auto-cross').click()
        expect(page.locator('#auto-cross')).to_have_attribute('aria-pressed','true')
        for i in range(36):
            r,c=divmod(i,6)
            if i==cols[0]:continue
            forbidden=r==0 or c==cols[0] or game['puzzle']['regions'][r][c]==game['puzzle']['regions'][0][cols[0]] or (r<=1 and abs(c-cols[0])<=1)
            if forbidden:expect(page.locator('.cell').nth(i)).to_have_text('×')
        page.locator('#auto-cross').click();page.evaluate('''() => {const prev=memoSnapshot();for(let i=0;i<cells.length;i++)paintMemo(i,0);commit(prev);}''')
        page.locator('#board').scroll_into_view_if_needed();before=geometry(page)
        # Slow responses cannot block local notes or lose later star gestures.
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':650,'downloadThroughput':-1,'uploadThroughput':-1})
        double(6+cols[1])
        memo=next(i for i in range(24,36) if i%6!=cols[i//6])
        tap(memo)
        expect(page.locator('.cell').nth(memo)).to_have_text('×')
        expect(page.locator('.cell').nth(6+cols[1])).to_have_class('cell locked',timeout=10000)
        expect(page.locator('.cell').nth(memo)).to_have_text('×')
        double(12+cols[2]);double(18+cols[3])
        expect(page.locator('.cell').nth(12+cols[2])).to_have_class('cell locked',timeout=10000)
        expect(page.locator('.cell').nth(18+cols[3])).to_have_class('cell locked',timeout=10000)
        stable(page,before)
        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
        page.locator('#auto-cross').click()
        page.reload()
        expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('#auto-cross')).to_have_attribute('aria-pressed','true')
        expect(page.locator('.cell').nth(cols[0])).to_have_class('cell locked')
        page.locator('#board').scroll_into_view_if_needed()
        page.evaluate('window.originalCell = document.querySelector(".cell")')
        before=geometry(page)
        wrong=(cols[0]+1)%6
        for mistakes in range(1,4):
            double(wrong)
            expect(page.locator('#lives')).to_have_attribute('aria-label',f'残機 {3-mistakes}、ミス {mistakes}回')
        expect(page.locator('#game-over')).to_be_visible()
        stable(page,before)
        board=page.locator('#board').bounding_box();button=page.locator('#overlay-next').bounding_box()
        assert board['y']<=button['y'] and button['y']+button['height']<=board['y']+board['height']
        ended_id=page.request.get(BASE+'/api/games/current').json()['id']
        marks=page.locator('.cell').all_text_contents()
        page.locator('#dismiss-result').click()
        expect(page.locator('#game-over')).to_be_hidden()
        assert page.request.get(BASE+'/api/games/current').json()['id']==ended_id
        assert page.locator('.cell').all_text_contents()==marks
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 0、ミス 3回')
        page.reload()
        expect(page.locator('#game-over')).to_be_hidden()
        expect(page.locator('.cell')).to_have_count(36)
        assert page.request.get(BASE+'/api/games/current').json()['id']==ended_id
        page.evaluate('window.originalCell = document.querySelector(".cell")')
        before=geometry(page)
        with page.expect_response(lambda r:r.url.endswith('/api/games') and r.request.method=='POST') as pending:
            page.locator('#advance').click()
        next_game=pending.value.json()
        expect(page.locator('#puzzle-label')).to_contain_text(next_game['puzzle']['id'][:8].upper())
        expect(page.locator('#game-over')).to_be_hidden()
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 3、ミス 0回')
        for level,n in [('medium',7),('hard',8)]:
            page.locator(f'[data-level="{level}"]').click()
            expect(page.locator('.cell')).to_have_count(n*n,timeout=15000)
            page.locator('#board').scroll_into_view_if_needed()
            page.evaluate('window.originalCell = document.querySelector(".cell")')
            before=geometry(page)
            tap(0);tap(n*n-1)
            stable(page,before)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        print(f'PASS {width}px {"native touch" if touch else "mouse"}: square stable cells/DOM, taps, paint/erase/undo/cancel, queued stars with latency, auto-cross, persisted setting, NEXT overlay')
        context.close()
    browser.close()
