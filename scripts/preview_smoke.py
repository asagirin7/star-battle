"""Hold server requests to verify immediate auto-X, isolated rollback, and stable borders."""
import os
from pathlib import Path
import sys
from playwright.sync_api import expect, sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')


def forbidden(puzzle,index):
    n=puzzle['size'];r,c=divmod(index,n)
    return {i for i in range(n*n) if (lambda rr,cc: rr==r or cc==c or puzzle['regions'][rr][cc]==puzzle['regions'][r][c] or (abs(rr-r)<=1 and abs(cc-c)<=1))(*divmod(i,n))}


with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,touch in [(390,True),(1280,False)]:
        context=browser.new_context(viewport={'width':width,'height':900},has_touch=touch,is_mobile=touch)
        page=context.new_page();page.goto(BASE)
        page.locator('#name').fill(f'即時反映検証{width}')
        page.get_by_role('button',name='この名前ではじめる').click()
        expect(page.locator('.cell')).to_have_count(36)
        page.locator('#auto-cross').click()
        page.locator('#board').scroll_into_view_if_needed()
        game=page.request.get(BASE+'/api/games/current').json();puzzle=game['puzzle']
        cols=solutions(puzzle['regions'])[0]
        bad=(cols[0]+1)%6;bad_x=forbidden(puzzle,bad)
        good=max((r*6+c for r,c in enumerate(cols) if r>0),key=lambda i:len(bad_x-forbidden(puzzle,i)))
        good_x=forbidden(puzzle,good)
        wrong_only=bad_x-good_x-{bad,good}
        assert len(wrong_only)>=2
        manual_bad=min(wrong_only)
        manual_other=next(i for i in range(36) if i not in bad_x|good_x) if set(range(36))-(bad_x|good_x) else next(i for i in good_x if i not in {bad,good,manual_bad})
        manual={manual_bad,manual_other}
        def tap(i):
            b=page.locator('.cell').nth(i).bounding_box();x,y=b['x']+b['width']/2,b['y']+b['height']/2
            if touch:page.touchscreen.tap(x,y)
            else:page.mouse.click(x,y)
        def double(i):tap(i);page.wait_for_timeout(60);tap(i)
        for i in manual:tap(i)
        if not touch:page.mouse.move(0,0)
        border=page.locator('.cell').evaluate_all('(els)=>els.map(e=>{const s=getComputedStyle(e);return [s.borderRightColor,s.borderBottomColor,s.borderRightWidth,s.borderBottomWidth]})')
        held=[]
        page.route('**/api/games/*/stars',lambda route:held.append(route))
        double(bad);double(good)
        expect(page.locator('.cell.pending')).to_have_count(2)
        page.wait_for_timeout(30)
        assert len(held)==1
        assert not page.request.get(BASE+'/api/games/current').json()['stars']
        # Both sets of auto-X must already be visible although neither request completed.
        for i in (bad_x|good_x)-{bad,good}:expect(page.locator('.cell').nth(i)).to_have_text('×')
        after=page.locator('.cell').evaluate_all('(els)=>els.map(e=>{const s=getComputedStyle(e);return [s.borderRightColor,s.borderBottomColor,s.borderRightWidth,s.borderBottomWidth]})')
        assert after==border,'Pointer changed a grid border'
        held[0].continue_()
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 2、ミス 1回')
        expect(page.locator('.cell.pending')).to_have_count(1)
        page.wait_for_timeout(30)
        assert len(held)==2
        for i in wrong_only-manual:expect(page.locator('.cell').nth(i)).to_have_text('')
        for i in good_x-{good,bad}:expect(page.locator('.cell').nth(i)).to_have_text('×')
        for i in manual:expect(page.locator('.cell').nth(i)).to_have_text('×')
        erased=next(i for i in good_x if i not in manual|{good,bad})
        tap(erased);expect(page.locator('.cell').nth(erased)).to_have_text('')
        page.keyboard.press('Control+z');expect(page.locator('.cell').nth(erased)).to_have_text('×')
        tap(erased);expect(page.locator('.cell').nth(erased)).to_have_text('')
        held[1].continue_()
        expect(page.locator('.cell').nth(good)).to_have_class('cell locked')
        expect(page.locator('.cell').nth(erased)).to_have_text('')
        for i in manual:expect(page.locator('.cell').nth(i)).to_have_text('×')
        page.unroute('**/api/games/*/stars')
        page.reload();expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('.cell').nth(erased)).to_have_text('')
        for i in manual:expect(page.locator('.cell').nth(i)).to_have_text('×')
        assert page.request.get(BASE+'/api/me').json()['points']==0
        print(f'PASS {width}px: auto-X before any server reply, wrong-star-only rollback, queued projection, manual notes/erase/undo/resume preserved, unchanged touch borders')
        context.close()
    browser.close()
