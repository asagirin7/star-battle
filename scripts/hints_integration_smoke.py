"""Real hint API/browser integration. Local database only; intentionally clears one game."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:8000')
assert urlparse(BASE_URL).hostname in {'127.0.0.1', 'localhost', '::1'}, 'Local verification only: this script writes a clear'

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [320, 390, 1280]:
        context = browser.new_context(viewport=dict(width=width, height=900))
        page = context.new_page()
        errors, attempts = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda req: attempts.append(req.post_data_json) if req.url.endswith('/api/hints') else None)
        page.goto(BASE_URL)
        page.locator('#name').fill(f'ヒント統合{width}')
        page.get_by_role('button', name='この名前ではじめる').click()
        expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('#hint-balance')).to_have_text('残り 10 回')
        expect(page.locator('#streak')).to_have_text('EASY 連続クリア 0 問')
        game = page.request.get(BASE_URL+'/api/games/current').json()
        page.locator('#hint').click()
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        expect(page.locator('#hint-message')).to_contain_text('難度')
        assert 'single_candidate' not in page.locator('#hint-message').inner_text()
        assert page.locator('.hint-target').count() > 0
        assert not page.request.get(BASE_URL+'/api/games/'+game['id']).json()['stars']
        assert page.locator('.cell').all_text_contents() == ['']*36
        first = attempts[-1]
        page.reload()
        expect(page.locator('.cell')).to_have_count(36)
        page.locator('#hint').click()
        expect(page.locator('#hint-message')).to_contain_text('難度')
        assert attempts[-1]['request_id'] == first['request_id']
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        assert page.request.get(BASE_URL+'/api/me').json()['hints'] == 9
        cols = solutions(game['puzzle']['regions'])[0]
        page.locator('.cell').nth(cols[0]).click()
        expect(page.locator('.cell').nth(cols[0])).to_have_text('×')
        page.locator('#hint').click()
        expect(page.locator('#hint-message')).to_contain_text('矛盾')
        expect(page.locator('#hint-message')).to_contain_text('消費なし')
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        assert page.request.get(BASE_URL+'/api/me').json()['hints'] == 9
        page.locator('.cell').nth(cols[0]).click()
        for r, c in enumerate(cols):
            response = page.request.post(BASE_URL+f"/api/games/{game['id']}/stars", data=dict(row=r,col=c,request_id=str(uuid.uuid4())))
            assert response.ok, response.text()
        # A fresh reload picks up authoritative stats and the completed game.
        page.reload()
        expect(page.locator('#streak')).to_have_text('EASY 連続クリア 1 問')
        expect(page.locator('#hint')).to_be_disabled()
        expect(page.locator('#hint-balance')).to_have_text('残り 9 回')
        assert not errors, errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        context.close()
        print(f'PASS {width}px: real 10→9, reason/target without auto move, reload idempotency, wrong memo no charge, clear streak sync')
    browser.close()
