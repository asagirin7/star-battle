"""Exercise real touch-sized UI against a running app (SQLite or PostgreSQL)."""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generate_puzzles import solutions

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:8000')
for attempt in range(50):
    try:
        urllib.request.urlopen(BASE_URL + '/health', timeout=2)
        break
    except OSError:
        time.sleep(.2)
else:
    raise RuntimeError('App did not start')

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height in [(390,844), (320,740), (1280,900)]:
        context = browser.new_context(viewport={'width':width, 'height':height}, device_scale_factor=1)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE_URL)
        page.locator('#name').fill(f'ブラウザ検証 {width}')
        page.get_by_role('button', name='この名前ではじめる').click()
        page.locator('.cell').first.wait_for()
        assert page.locator('.cell').count() == 36
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('.cell').first.click()
        page.get_by_role('button', name='1手戻す').click()
        assert page.locator('.cell').first.inner_text() == ''
        puzzle = json.loads((ROOT/'puzzles.json').read_text())[0]
        for r,c in enumerate(solutions(puzzle['regions'])[0]):
            page.locator('.cell').nth(r*6+c).click()
        page.locator('#check').click()
        page.get_by_text('クリア！ ✦ +100 pt を獲得しました。', exact=True).wait_for()
        page.locator('[data-tab="ranking"]').click()
        page.locator('#ranking-list .list-row.mine').wait_for()
        assert '100 pt' in page.locator('#ranking-list .list-row.mine').inner_text()
        page.locator('[data-tab="history"]').click()
        page.locator('#history-list .list-row').wait_for()
        page.reload()
        page.locator('.cell').first.wait_for()
        assert page.locator('#clear-count').inner_text() == '1 問クリア'
        for difficulty,n in [('medium',7),('hard',8)]:
            page.locator(f'[data-level="{difficulty}"]').click()
            page.wait_for_function(f'() => document.querySelectorAll(".cell").length === {n*n}')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('[data-level="easy"]').click()
        page.wait_for_function('() => document.querySelectorAll(".cell").length === 36')
        ROOT.joinpath('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/f'artifacts/{width}.png'), full_page=True)
        assert not errors, errors
        context.close()
        print(f'PASS: {width}px registration, board, clear, ranking, history, persistence, all sizes')
    browser.close()
