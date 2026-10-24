"""Board creation shows a loading animation over the board until the reply.

API calls are mocked; safe for production smoke (no game or points are written).
"""
import os
import time
from playwright.sync_api import sync_playwright, expect

BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:8000')
PLAYER = dict(id='ui-loading-player', name='読み込み表示テスト', points=0, clears=0, hints=0,
              streaks=dict(easy=0, medium=0, hard=0, expert=0, expert_relaxed=0))
GAME = dict(id='00000000-0000-4000-8000-000000000002', stars=[], lives=3, mistakes=0, completed=False,
            game_over=False, started_at=int(time.time()), memos=[0]*36,
            puzzle=dict(id='c'*32, size=6, difficulty='easy', multiplier=1, regions=[[r]*6 for r in range(6)]))

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [320, 1280]:
        page = browser.new_page(viewport=dict(width=width, height=900))
        held, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            path = route.request.url.split('/api/')[1].split('?')[0]
            if path == 'me':
                route.fulfill(json=PLAYER)
            elif path == 'games/current':
                route.fulfill(status=200, content_type='application/json', body='null')
            elif path == 'games':
                held.append(route)
            elif path.endswith('/memos'):
                route.fulfill(json=dict(memos=[0]*36, memo_revision=1))
            else:
                route.fulfill(json={})

        page.route('**/api/**', api)
        page.goto(BASE_URL)
        expect(page.locator('#board-loading')).to_be_visible()
        expect(page.locator('#board-loading')).to_contain_text('盤面を作成中')
        page.wait_for_timeout(300)
        expect(page.locator('#board-loading')).to_be_visible()
        held.pop().fulfill(json=GAME)
        expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('#board-loading')).to_be_hidden()
        assert not errors, errors
        page.close()
        print(f'PASS {width}px: loading animation while a board is created, hidden after reply')
    browser.close()
