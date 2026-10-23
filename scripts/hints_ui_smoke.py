"""Hint UI contract: marks are advisory, retries are idempotent, mobile layout stays usable.

API calls are mocked; safe for production smoke (no game or points are written).
"""
import os
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

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [320, 390, 1280]:
        context = browser.new_context(viewport=dict(width=width, height=900))
        page = context.new_page()
        errors, attempts, held = [], [], []
        state = dict(mode='hold', balance=10)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            path = route.request.url.split('/api/')[1]
            if path == 'me':
                route.fulfill(json={**PLAYER, 'hints': state['balance']})
            elif path.startswith('games/current'):
                route.fulfill(json=GAME)
            elif path == 'hints':
                attempts.append(route.request.post_data_json)
                if state['mode'] == 'hold':
                    held.append(route)
                elif state['mode'] == 'offline':
                    route.abort()
                elif state['mode'] == 'empty':
                    route.fulfill(status=409, json=dict(detail='ヒントの残り回数がありません。'))
                elif state['mode'] == 'invalid':
                    route.fulfill(status=422, json=dict(detail='×メモに矛盾があります。ヒントは消費しません。'))
                else:
                    route.fulfill(json=dict(hint=HINT, balance=state['balance']))
            else:
                raise AssertionError(f'Unexpected API write: {path}')

        page.route('**/api/**', api)
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
        assert not errors, errors
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=f'artifacts/hints-ui-{width}.png', full_page=True)
        context.close()
        print(f'PASS {width}px: hints, advisory marks, locked pending input, retry ID after reload, invalid memo, zero balance, streak, next button')
    browser.close()
