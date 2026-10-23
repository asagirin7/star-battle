"""Independently solve API boards, verify judging, and recover a rejected board."""
import itertools
import os
import uuid
import sys
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logic_solver import logical_result

BASE_URL=os.getenv('BASE_URL','http://127.0.0.1:8000')


def independent_solutions(regions):
    n=len(regions)
    return [list(cols) for cols in itertools.permutations(range(n))
            if all(abs(cols[r]-cols[r-1])>1 for r in range(1,n))
            and len({regions[r][c] for r,c in enumerate(cols)})==n]


def nonce():
    return str(uuid.uuid4())


with httpx.Client(base_url=BASE_URL,timeout=30) as client:
    client.post('/api/profile',json={'name':'盤面整合性確認'}).raise_for_status()
    for level,n,points in [('easy',6,3),('medium',7,6),('hard',8,9),('expert',9,100),('expert_relaxed',9,50)]:
        for attempt in range(3):
            response=client.post('/api/games',json={'difficulty':level,'request_id':nonce()})
            response.raise_for_status()
            game=response.json()
            assert 'solution' not in game['puzzle']
            assert game['puzzle']['size']==n and game['puzzle']['points']==points
            found=independent_solutions(game['puzzle']['regions'])
            assert len(found)==1,(level,game['puzzle']['id'],len(found))
            cols=found[0]
            deduction=logical_result(game['puzzle']['regions'])
            assert deduction.solved and list(deduction.columns)==cols,(level,'deductions stalled')
            url=f"/api/games/{game['id']}/stars"
            placed=client.post(url,json={'row':n-1,'col':cols[-1],'request_id':nonce()})
            placed.raise_for_status()
            result=placed.json()
            assert result['correct'] and result['game']['stars']==[[n-1,cols[-1]]]
            bad=(cols[0]+1)%n
            move={'row':0,'col':bad,'request_id':nonce()}
            rejected=client.post(url,json=move)
            rejected.raise_for_status()
            rejected=rejected.json()
            assert not rejected['correct']
            assert rejected['game']['mistakes']==1
            assert rejected['game']['stars']==[[n-1,cols[-1]]]
            assert client.post(url,json=move).json()['game']['mistakes']==1
            assert not rejected['game']['completed']
            assert rejected['game']['game_over']==(n==9)
        print(f'PASS {level}: 3 independent exhaustive solves, correct/wrong stars, retry and no false clears',flush=True)
    assert client.get('/api/me').json()['points']==0

with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in [390,320]:
        context=browser.new_context(viewport={'width':width,'height':844})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE_URL)
        page.locator('#name').fill('盤面切り替え確認')
        page.locator('#profile-form button[type=submit]').click()
        expect(page.locator('.cell')).to_have_count(36)
        old=page.request.get(BASE_URL+'/api/games/current').json()
        page.route('**/api/games/*/stars',lambda route:route.fulfill(status=409,json={
            'detail':{'code':'invalid_puzzle','message':'盤面を再検証します。'}}),times=1)
        with page.expect_response(lambda r:r.url.endswith('/api/games') and r.request.method=='POST') as pending:
            page.locator('.cell').first.press('Enter')
        new=pending.value.json()
        assert new['id']!=old['id']
        expect(page.locator('#puzzle-label')).to_contain_text(new['puzzle']['id'][:8].upper())
        expect(page.locator('#lives')).to_have_attribute('aria-label','残機 3、ミス 0回')
        expect(page.locator('#status')).to_contain_text('ミスには数えていません')
        expect(page.locator('#advance')).to_be_enabled()
        assert page.request.get(BASE_URL+'/api/me').json()['points']==0
        assert not errors,errors
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path=f'artifacts/verified-board-{width}.png')
        context.close()
        print(f'PASS {width}px: invalid-board reply clears pending input and replaces board without penalty',flush=True)
    browser.close()
