"""Daily/cumulative switching, stale responses, empty days and JST midnight."""
import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE_URL=os.getenv('BASE_URL','http://127.0.0.1:8000')
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in [390,320,1280]:
        context=browser.new_context(viewport={'width':width,'height':844})
        page=context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.clock.set_fixed_time(datetime(2026,10,22,14,59,59,tzinfo=timezone.utc))
        state={'hold':True,'next_day':False}
        pending=[]
        daily=[{'id':'today','name':'今日のプレイヤー','points':50,'clears':1}]
        cumulative=[{'id':'all','name':'累計のプレイヤー','points':100,'clears':2}]
        def ranking(route):
            if 'period=all' in route.request.url:
                if state['hold']:
                    pending.append(route)
                else:
                    route.fulfill(json=cumulative)
            else:
                route.fulfill(json=[] if state['next_day'] else daily)
        page.route('**/api/ranking?*',ranking)
        page.goto(BASE_URL)
        expect(page.locator('#profile-dialog')).to_be_visible()
        page.locator('#close-profile').click()
        page.locator('[data-tab="ranking"]').click()
        expect(page.locator('#ranking-list')).to_contain_text('今日のプレイヤー')
        expect(page.locator('#ranking-description')).to_contain_text('日本時間0時')
        with page.expect_request('**/api/ranking?period=all'):
            page.locator('[data-ranking="all"]').click()
        page.locator('[data-ranking="daily"]').click()
        expect(page.locator('#ranking-list')).to_contain_text('今日のプレイヤー')
        assert len(pending)==1
        with page.expect_response('**/api/ranking?period=all'):
            pending.pop().fulfill(json=cumulative)
        expect(page.locator('#ranking-list')).not_to_contain_text('累計のプレイヤー')
        expect(page.locator('[data-ranking="daily"]')).to_have_attribute('aria-pressed','true')
        state['next_day']=True
        page.clock.set_fixed_time(datetime(2026,10,22,15,0,0,tzinfo=timezone.utc))
        expect(page.locator('#ranking-list')).to_contain_text('今日のクリアはまだありません')
        expect(page.locator('#ranking-list')).to_have_attribute('aria-busy','false')
        state['hold']=False
        page.locator('[data-ranking="all"]').click()
        expect(page.locator('#ranking-list')).to_contain_text('累計のプレイヤー')
        expect(page.locator('#ranking-list')).to_contain_text('100 pt')
        expect(page.locator('#ranking-description')).to_contain_text('累計ポイント順')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('[data-ranking="daily"]').click()
        expect(page.locator('#ranking-list')).to_contain_text('今日のクリアはまだありません')
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=f'artifacts/daily-ranking-{width}.png',full_page=True)
        assert not errors,errors
        context.close()
        print(f'PASS {width}px: daily/all, stale reply, JST rollover, empty day, layout',flush=True)
    browser.close()
