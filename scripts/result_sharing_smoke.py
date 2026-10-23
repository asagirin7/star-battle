"""Local-only result sharing chain with authoritative times and private games."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
assert urlparse(BASE).hostname in {'localhost','127.0.0.1'}, 'This smoke clears boards; local servers only'

def register(page,name):
    page.locator('#name').fill(name)
    page.locator('#profile-form button[type=submit]').click()
    expect(page.locator('.cell')).to_have_count(36)

def complete(page):
    state=page.request.get(BASE+'/api/games/current').json()
    for row,col in enumerate(solutions(state['puzzle']['regions'])[0]):
        response=page.request.post(BASE+'/api/games/'+state['id']+'/stars',data={'row':row,'col':col,'request_id':str(uuid.uuid4())})
        assert response.status==200,response.text()
        state=response.json()['game']
    assert state['completed'] and state['clear_id']
    page.reload();expect(page.locator('#share-puzzle')).to_have_text('クリア結果を共有')
    page.evaluate("Object.defineProperty(navigator,'share',{value:async payload=>{window.nativeResult=payload},configurable:true})")
    # Slow verification must still expose a result URL immediately, while native
    # sharing waits for the official seconds/text rather than sharing a bare board.
    waiting=[]
    def delayed_result(route):
        waiting.append(route)
    page.route('**/api/clears/'+state['clear_id'],delayed_result)
    expect(page.locator('#overlay-share')).to_be_visible()
    board=page.locator('#board').bounding_box()
    button=page.locator('#overlay-share').bounding_box()
    assert board['x']<=button['x'] and button['x']+button['width']<=board['x']+board['width']
    assert board['y']<=button['y'] and button['y']+button['height']<=board['y']+board['height']
    page.locator('#overlay-share').click()
    expect(page.locator('#native-share')).to_be_disabled()
    pending_url=page.locator('#share-url').input_value()
    assert parse_qs(urlparse(pending_url).query)['c']==[state['clear_id']]
    page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.earlyCopy=text}},configurable:true})")
    page.locator('#copy-share').click()
    expect(page.locator('#share-status')).to_contain_text('コピーしました')
    assert page.evaluate('window.earlyCopy')==pending_url
    expect(page.locator('#native-share')).to_be_disabled()
    assert len(waiting)==1
    waiting[0].fulfill(response=waiting[0].fetch())
    expect(page.locator('#share-title')).to_have_text('クリア結果をシェア')
    page.unroute('**/api/clears/'+state['clear_id'],delayed_result)
    official=page.request.get(BASE+'/api/clears/'+state['clear_id']).json()
    url=page.locator('#share-url').input_value()
    assert parse_qs(urlparse(url).query)=={'p':[state['puzzle']['id']],'c':[state['clear_id']]}
    message=f"Star Battle 6×6を{official['seconds']}秒でクリア！ {official['points']}pt"
    assert page.locator('#result-share-text').input_value()==message+'\n'+url
    page.locator('#native-share').click()
    assert page.evaluate('window.nativeResult')=={'title':'Star Battle','text':message,'url':url}
    page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}},configurable:true})")
    page.locator('#copy-result').click();expect(page.locator('#share-status')).to_contain_text('コピーしました')
    assert page.evaluate('window.copied')==message+'\n'+url
    page.evaluate("Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});document.execCommand=()=>false")
    page.locator('#copy-result').click();expect(page.locator('#share-status')).to_contain_text('自動コピーできませんでした')
    assert page.locator('#result-share-text').evaluate('(el)=>el.selectionStart===0&&el.selectionEnd===el.value.length')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#close-share').click()
    page.route('**/api/clears/'+state['clear_id'],lambda route:route.fulfill(status=404,json={'detail':'not found'}))
    page.locator('#share-puzzle').click()
    expect(page.locator('#share-status')).to_contain_text('盤面のURLは共有できます')
    assert 'c' not in parse_qs(urlparse(page.locator('#share-url').input_value()).query)
    expect(page.locator('#copy-result')).to_be_hidden()
    expect(page.locator('#native-share')).to_be_enabled()
    return state,official,url

with sync_playwright() as p:
    browser=p.chromium.launch()
    contexts=[browser.new_context(viewport={'width':w,'height':900},has_touch=True,is_mobile=w<500) for w in [1280,390,320]]
    a,b,c=[ctx.new_page() for ctx in contexts]
    errors=[]
    for page in [a,b,c]:page.on('pageerror',lambda e:errors.append(str(e)))
    a.goto(BASE);register(a,'<b>結果の送信者</b>')
    a.locator('#share-puzzle').click();expect(a.locator('#copy-result')).to_be_hidden()
    bare=a.locator('#share-url').input_value()
    b.goto(bare);expect(b.locator('#shared-dialog')).to_be_visible();b.locator('#play-shared').click();register(b,'二人目')
    first,official,result=complete(b)
    c.goto(result+'&seconds=1&points=9999');expect(c.locator('#shared-title')).to_have_text('共有されたクリア結果')
    expect(c.locator('#shared-result')).to_have_text(f"二人目：{official['seconds']}秒でクリア！ {official['points']}pt")
    c.locator('#play-shared').click();register(c,'<img src=x>')
    second,other,next_result=complete(c)
    assert first['id']!=second['id'] and first['puzzle']==second['puzzle']
    assert first['clear_id']!=second['clear_id']
    a.goto(next_result);expect(a.locator('#shared-result')).to_have_text(f"<img src=x>：{other['seconds']}秒でクリア！ {other['points']}pt")
    assert a.locator('#shared-result img').count()==0
    a.locator('#play-shared').click();expect(a.locator('.cell')).to_have_count(36)
    assert a.request.get(BASE+'/api/games/current').json()['completed'] is False
    # Nonexistent results and mismatched result/puzzle pairs never appear as clears.
    a.goto(bare+'&c=00000000-0000-0000-0000-000000000000')
    expect(a.locator('#shared-result')).to_contain_text('確認できません')
    fake=dict(official);fake['puzzle']=dict(fake['puzzle'],id='0'*32)
    a.route('**/api/clears/'+first['clear_id'],lambda route:route.fulfill(json=fake))
    a.goto(result);expect(a.locator('#shared-result')).to_contain_text('確認できません')
    expect(a.locator('#shared-title')).to_have_text('共有された盤面')
    assert not errors,errors
    print('PASS: local shared board → clear → official seconds/text/URL → another player clear → reshare; copy fallback, safe names, invalid/mismatched results')
    for context in contexts:context.close()
    browser.close()
