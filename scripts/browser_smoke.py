"""Exercise mobile/desktop generation, remaining lives, resume, and rankings."""
import os
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions

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


def move(page, r, c, n):
    with page.expect_response(lambda response: '/stars' in response.url and response.request.method == 'POST') as pending:
        page.locator('.cell').nth(r*n+c).dblclick(delay=70)
    response = pending.value.json()
    if response['correct'] and not response['game']['game_over']:
        expect(page.locator('.cell').nth(r*n+c)).to_have_text('★')
    else:
        expect(page.locator('#lives')).to_have_attribute('aria-label', f"残機 {response['game']['lives']}、ミス {response['game']['mistakes']}回")
    return response


def terminal(page, title):
    expect(page.locator('#clear-celebration')).not_to_be_visible()
    expect(page.locator('#game-over')).to_be_visible()
    expect(page.locator('#result-title')).to_have_text(title)
    expect(page.locator('#overlay-next')).to_be_enabled()
    board=page.locator('#board').bounding_box()
    button=page.locator('#overlay-next').bounding_box()
    assert board and button
    assert board['x'] <= button['x'] and button['x']+button['width'] <= board['x']+board['width']
    assert board['y'] <= button['y'] and button['y']+button['height'] <= board['y']+board['height']


def advance(page):
    with page.expect_response(lambda response: response.url.endswith('/api/games') and response.request.method == 'POST') as pending:
        (page.locator('#overlay-next') if page.locator('#game-over').is_visible() else page.locator('#advance')).click()
    game = pending.value.json()
    expect(page.locator('#puzzle-label')).to_contain_text(game['puzzle']['id'][:8].upper())
    expect(page.locator('#lives')).to_have_attribute('aria-label','残機 3、ミス 0回')
    expect(page.locator('#game-over')).to_be_hidden()
    return game


with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height in [(390,844), (320,740), (1280,900)]:
        context = browser.new_context(viewport={'width':width,'height':height},device_scale_factor=1)
        page = context.new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE_URL)
        page.locator('#name').fill(f'ブラウザ検証 {width}')
        page.get_by_role('button',name='この名前ではじめる').click()
        page.locator('.cell').first.wait_for()
        assert page.locator('.cell').count()==36
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('.cell').first.click()
        expect(page.locator('.cell').first).to_have_text('×')
        page.get_by_role('button',name='メモを1手戻す').click()
        expect(page.locator('.cell').first).to_have_text('')
        game=page.request.get(BASE_URL+'/api/games/current').json()
        n=game['puzzle']['size']
        cols=solutions(game['puzzle']['regions'])[0]
        wrong=(cols[0]+1)%n
        move(page,0,wrong,n)
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 2、ミス 1回')
        move(page,0,cols[0],n)
        page.locator('#reset').click()
        page.reload()
        page.locator('.cell').first.wait_for()
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 2、ミス 1回')
        expect(page.locator('.cell').nth(cols[0])).to_have_text('★')
        assert page.request.get(BASE_URL+'/api/games/current').json()['id']==game['id']
        for r,c in list(enumerate(cols))[1:]:move(page,r,c,n)
        expect(page.locator('#status')).to_contain_text('残機 2 × 1 = +2 pt')
        expect(page.locator('#clear-celebration')).to_be_visible()
        expect(page.locator('#reward-lives')).to_have_text('♥♥')
        expect(page.locator('#reward-multiplier')).to_have_text('1')
        expect(page.locator('#reward-earned')).to_have_text('+2 pt')
        terminal(page,'クリア！ ✦')
        expect(page.locator('#total')).to_contain_text('2')
        page.reload()
        terminal(page,'クリア！ ✦')
        expect(page.locator('#result-message')).to_have_text('残機 2 × 1 = +2 pt')
        page.locator('[data-tab="ranking"]').click()
        expect(page.locator('#ranking-list .list-row.mine')).to_contain_text('2 pt')
        page.locator('[data-tab="history"]').click()
        expect(page.locator('#history-list .list-row')).to_contain_text('ミス1回')
        page.locator('[data-tab="play"]').click()
        second=advance(page)
        assert second['puzzle']['id']!=game['puzzle']['id']
        for r,c in enumerate(solutions(second['puzzle']['regions'])[0]):move(page,r,c,n)
        expect(page.locator('#status')).to_contain_text('残機 3 × 1 = +3 pt')
        expect(page.locator('#clear-celebration')).to_be_visible()
        page.locator('#finish-celebration').click()
        terminal(page,'クリア！ ✦')
        expect(page.locator('#total')).to_contain_text('5')
        third=advance(page)
        wrong=(solutions(third['puzzle']['regions'])[0][0]+1)%n
        for _ in range(3):move(page,0,wrong,n)
        expect(page.locator('#status')).to_contain_text('ゲームオーバー')
        terminal(page,'ゲームオーバー')
        page.reload()
        page.locator('.cell').first.wait_for()
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 0、ミス 3回')
        terminal(page,'ゲームオーバー')
        for difficulty,n in [('medium',7),('hard',8),('expert',9)]:
            page.locator(f'[data-level="{difficulty}"]').click()
            expect(page.locator('.cell')).to_have_count(n*n)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        secret=page.locator('[data-level="expert"]')
        hard=page.locator('[data-level="hard"]').bounding_box()
        hit=secret.bounding_box()
        assert hit['x'] >= hard['x']+hard['width']
        assert secret.inner_text() == ''
        assert secret.evaluate("(b)=>getComputedStyle(b).backgroundColor") == 'rgba(0, 0, 0, 0)'
        assert secret.evaluate("(b)=>getComputedStyle(b).borderTopColor") == 'rgba(0, 0, 0, 0)'
        expert=page.request.get(BASE_URL+'/api/games/current?difficulty=expert').json()
        assert expert['puzzle']['multiplier'] is None
        assert expert['lives']==1
        assert expert['puzzle']['points']==100
        for r,c in enumerate(solutions(expert['puzzle']['regions'])[0]):move(page,r,c,9)
        expect(page.locator('.fixed-reward-label')).to_be_visible()
        expect(page.locator('#reward-earned')).to_have_text('+100 pt')
        terminal(page,'クリア！ ✦')
        expect(page.locator('#total')).to_contain_text('105')
        with page.expect_response(lambda response: response.url.endswith('/api/games') and response.request.method == 'POST') as fresh_pending:
            page.locator('#overlay-next').click()
        fresh=fresh_pending.value.json()
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 1、ミス 0回')
        wrong=(solutions(fresh['puzzle']['regions'])[0][0]+1)%9
        move(page,0,wrong,9)
        terminal(page,'ゲームオーバー')
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 0、ミス 1回')
        page.reload()
        terminal(page,'ゲームオーバー')
        expect(page.locator('.cell')).to_have_count(81)
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 0、ミス 1回')
        page.locator('#expert-mode').click()
        expect(page.locator('#puzzle-label')).to_contain_text('8 × 8相当')
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 1、ミス 0回')
        relaxed=page.request.get(BASE_URL+'/api/games/current?difficulty=expert_relaxed').json()
        areas=relaxed['puzzle']['regions']
        counts=[sum(row.count(i) for row in areas) for i in range(9)]
        assert min(counts)>=2 and counts.count(2)>=2
        for r,c in enumerate(solutions(areas)[0]):move(page,r,c,9)
        terminal(page,'クリア！ ✦')
        expect(page.locator('#result-message')).to_have_text('ノーミスクリア！ +100 pt')
        expect(page.locator('#total')).to_contain_text('205')
        page.reload()
        terminal(page,'クリア！ ✦')
        expect(page.locator('#puzzle-label')).to_contain_text('8 × 8相当')
        page.locator('#expert-mode').click()
        expect(page.locator('#puzzle-label')).to_contain_text('EXPERT')
        terminal(page,'ゲームオーバー')
        assert not page.locator('.cell').evaluate_all("(cells)=>cells.some(b=>!b.style.background)")
        page.locator('[data-level="easy"]').click()
        expect(page.locator('.cell')).to_have_count(36)
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 0、ミス 3回')
        advance(page)
        ROOT.joinpath('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/f'artifacts/{width}.png'),full_page=True)
        assert not errors,errors
        context.close()
        print(f'PASS {width}px: generation, memo/undo, mistake/resume, locked stars, 2+3 scoring, ranking, game-over, all sizes')
    browser.close()
