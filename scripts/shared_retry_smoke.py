"""Local-only browser retry and authoritative zero-point result sharing."""
import os,sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
assert urlparse(BASE).hostname in {'localhost','127.0.0.1'}, 'Local servers only: this script clears boards'
PID='d0d0d0d0d0d04d0da0d0d0d0d0d0d0d0'
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in [320,390]:
        ctx=browser.new_context(viewport={'width':width,'height':950},has_touch=True,is_mobile=True)
        page=ctx.new_page();page.goto(BASE+'/?p='+PID)
        expect(page.locator('#shared-dialog')).to_be_visible()
        page.locator('#play-shared').click();page.locator('#name').fill('リトライ確認'+str(width));page.locator('#profile-form button[type=submit]').click()
        expect(page.locator('.cell')).to_have_count(81)
        state=page.request.get(BASE+'/api/games/current?difficulty=expert').json()
        cols=solutions(state['puzzle']['regions'])[0]
        page.locator('.cell').nth((cols[0]+1)%9).click(button='right')
        expect(page.locator('#overlay-retry')).to_be_visible()
        board=page.locator('#board').bounding_box();button=page.locator('#overlay-retry').bounding_box()
        assert board['x']<=button['x'] and button['x']+button['width']<=board['x']+board['width']
        assert board['y']<=button['y'] and button['y']+button['height']<=board['y']+board['height']
        page.locator('#overlay-retry').click()
        expect(page.locator('#status')).to_contain_text('リトライ1回')
        page.reload();expect(page.locator('.cell')).to_have_count(81)
        retry=page.request.get(BASE+'/api/games/current?difficulty=expert').json()
        assert retry['retries']==1 and retry['id']!=state['id'] and retry['puzzle']['id']==PID
        assert retry['mistakes']==0 and not retry['stars']
        for row,col in enumerate(cols):
            page.locator('.cell').nth(row*9+col).click(button='right')
            expect(page.locator('.cell.locked')).to_have_count(row+1)
        expect(page.locator('#share-puzzle')).to_have_text('クリア結果を共有')
        page.locator('#overlay-share').click()
        expect(page.locator('#result-share-text')).to_be_visible()
        message=page.locator('#result-share-text').input_value()
        assert '0pt・リトライ1回' in message
        url=page.locator('#share-url').input_value()
        assert page.request.get(BASE+'/api/me').json()['points']==0
        viewer=browser.new_page();viewer.goto(url+'&retries=0&points=999')
        expect(viewer.locator('#shared-result')).to_contain_text('0pt・リトライ1回')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        viewer.close();ctx.close()
    browser.close()
print('PASS: shared game over → explicit retry → reload → zero-point clear → authoritative retry-count sharing at320/390')
