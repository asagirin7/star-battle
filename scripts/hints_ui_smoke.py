"""Hint UI contract: marks are advisory, retries are idempotent, mobile layout stays usable.

API calls are mocked; safe for production smoke (no game or points are written).
"""
import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:8000')
PLAYER = dict(id='ui-hint-player', name='ヒント表示テスト', points=0, clears=0,
              hints=10, streaks=dict(easy=4, medium=2, hard=0, expert=0, expert_relaxed=0))
GAME = dict(id='00000000-0000-4000-8000-000000000001', stars=[], lives=3,
            mistakes=0, completed=False, game_over=False, started_at=int(time.time()), memos=[0]*36,
            puzzle=dict(id='a'*32, size=6, difficulty='easy', multiplier=1,
                        regions=[[r]*6 for r in range(6)]))
HINT = dict(technique='残り1マス', points=1, explanation='この行で星を置ける候補は1マスです。',
            source_cells=[[0, 0], [0, 1]], target_cells=[[0, 2]], action='star')
CROSS_HINT = dict(technique='shape_exclusion', points=10, explanation='どの候補に星を置いても対象マスには置けません。',
                  source_cells=[[4, 0], [4, 1]], target_cells=[[3, 0], [3, 1]], action='cross')
OTHER_CROSS_HINT = {**CROSS_HINT, 'source_cells': [[2, 4], [2, 5]], 'target_cells': [[1, 4], [1, 5]]}

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [320, 390, 1280]:
        context = browser.new_context(viewport=dict(width=width, height=900))
        page = context.new_page()
        errors, attempts, held, me_requests = [], [], [], []
        state = dict(mode='hold', balance=10)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            path = route.request.url.split('/api/')[1]
            if path.split('?')[0] == 'me':
                me_requests.append(path)
                route.fulfill(json={**PLAYER, 'hints': state['balance'], 'username': 'ui' if state.get('registered') else None})
            elif path.startswith('games/current') or path == 'games/'+GAME['id']:
                route.fulfill(json=GAME)
            elif path.endswith('/memos'):
                route.fulfill(json=dict(memos=[0]*36, memo_revision=1))
            elif path == 'hints':
                attempts.append(route.request.post_data_json)
                if state['mode'] == 'hold':
                    held.append(route)
                elif state['mode'] == 'offline':
                    route.abort()
                elif state['mode'] == 'empty':
                    route.fulfill(status=409, json=dict(detail='ヒントの残り回数がありません。'))
                elif state['mode'] in ('cross', 'other_cross'):
                    hint = CROSS_HINT if state['mode'] == 'cross' else OTHER_CROSS_HINT
                    route.fulfill(json=dict(hint=hint, balance=state['balance']))
                elif state['mode'] == 'invalid':
                    route.fulfill(status=422, json=dict(detail='×メモに矛盾があります。ヒントは消費しません。'))
                else:
                    route.fulfill(json=dict(hint=HINT, balance=state['balance']))
            else:
                raise AssertionError(f'Unexpected API write: {path}')

        page.route('**/api/**', api)
        page.clock.install()
        page.goto(BASE_URL)
        expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('#next')).to_have_count(0)
        expect(page.locator('#advance')).to_be_visible()
        expect(page.locator('#overlay-next')).to_have_count(1)
        expect(page.locator('#streak')).to_have_text('EASY 連続クリア 4 問')
        expect(page.locator('#hint-balance')).to_have_text('残り 10 回')
        page.locator('#hint').click()
        expect(page.locator('#hint')).to_be_disabled()
        expect(page.locator('#advance')).to_be_disabled()
        page.locator('.cell').nth(10).click()
        expect(page.locator('.cell').nth(10)).to_have_text('')
        state['balance'] = 9
        held.pop().fulfill(json=dict(hint=HINT, balance=9))
        expect(page.locator('#hint-message')).to_contain_text('残り1マス（難易度点 1）')
        expect(page.locator('#hint-message')).to_contain_text('1行3列に星を置けます')
        expect(page.locator('.hint-source')).to_have_count(2)
        expect(page.locator('.hint-target')).to_have_count(1)
        # Each preview looks like the entry it suggests: a pale star here,
        # dotted stars for the supporting candidates.
        expect(page.locator('.cell').nth(2)).to_have_class(re.compile(r'\bhint-star\b'))
        expect(page.locator('.hint-candidate')).to_have_count(2)
        expect(page.locator('.hint-cross')).to_have_count(0)
        expect(page.locator('#hint-legend')).to_be_visible()
        expect(page.locator('.cell').nth(2)).to_have_text('')
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        assert attempts[0]['crosses'] == []
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # A changed memo clears the advisory highlight and gets a fresh request ID.
        page.locator('.cell').nth(12).click()
        expect(page.locator('.cell').nth(12)).to_have_text('×')
        expect(page.locator('.hint-target')).to_have_count(0)
        state['mode'] = 'offline'
        page.locator('#hint').click()
        expect(page.locator('#hint')).to_be_enabled()
        failed = attempts[-1]
        assert failed['crosses'] == [12]
        assert failed['request_id'] != attempts[0]['request_id']
        # Reload keeps the failed operation ID, preventing a second charge.
        page.reload()
        expect(page.locator('.cell').nth(12)).to_have_text('×')
        state['mode'] = 'invalid'
        page.locator('#hint').click()
        expect(page.locator('#hint-message')).to_contain_text('×メモに矛盾')
        assert attempts[-1]['request_id'] == failed['request_id']
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        state['mode'] = 'empty'
        state['balance'] = 0
        page.locator('#hint').click()
        expect(page.locator('#hint-balance')).to_have_text('残り 0 回')
        expect(page.locator('#hint')).to_be_disabled()
        # A periodic account sync reads stats without granting a launch bonus.
        state['registered'] = True
        page.evaluate("me.username='ui'")
        launch_count = me_requests.count('me')
        with page.expect_request('**/api/me?launch=false'):
            page.clock.fast_forward(10000)
        assert me_requests.count('me') == launch_count
        # Returning to a visible page is a launch, including for guest players.
        state['registered'] = False
        page.evaluate('me.username=null')
        state['balance'] = 3
        with page.expect_request('**/api/me'):
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#hint-balance')).to_have_text('残り 3 回')
        expect(page.locator('#hint')).to_be_enabled()
        assert me_requests.count('me') == launch_count+1
        # Cross previews stay until each target is entered, then become real marks.
        state['mode'] = 'cross'
        page.locator('#hint').click()
        expect(page.locator('.hint-cross')).to_have_count(2)
        expect(page.locator('.hint-candidate')).to_have_count(2)
        expect(page.locator('.hint-star')).to_have_count(0)
        page.locator('.cell').nth(18).click()
        expect(page.locator('.cell').nth(18)).to_have_text('×')
        expect(page.locator('.cell').nth(18)).not_to_have_class(re.compile(r'\bhint-cross\b'))
        expect(page.locator('.hint-cross')).to_have_count(1)
        expect(page.locator('#hint-message')).to_contain_text('4行1列、4行2列に×を付けられます')
        page.locator('.cell').nth(19).click()
        expect(page.locator('.cell').nth(19)).to_have_text('×')
        expect(page.locator('.hint-cross')).to_have_count(0)
        expect(page.locator('.hint-candidate')).to_have_count(0)
        expect(page.locator('#hint-message')).to_have_text('ヒントの一手を入力しました。')
        page.clock.fast_forward(1000)
        page.locator('.cell').nth(30).click()
        expect(page.locator('#hint-message')).to_contain_text('根拠と次の一手を示します')
        # An unrelated memo while a cross hint is shown clears every preview.
        state['mode'] = 'other_cross'
        page.locator('#hint').click()
        expect(page.locator('.hint-cross')).to_have_count(2)
        page.clock.fast_forward(1000)
        page.locator('.cell').nth(35).click()
        expect(page.locator('.hint-cross')).to_have_count(0)
        expect(page.locator('.hint-candidate')).to_have_count(0)
        assert not errors, errors
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=f'artifacts/hints-ui-{width}.png', full_page=True)
        context.close()
        print(f'PASS {width}px: hints, advisory marks, locked pending input, retry ID after reload, invalid memo, zero balance, streak, next button')
    browser.close()
