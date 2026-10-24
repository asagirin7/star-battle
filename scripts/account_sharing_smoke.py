"""Two isolated devices retain identity and memos; shared links keep play private.
Safe on production: never completes a puzzle or adds ranking points.
"""
import os
import uuid
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
username='share_'+uuid.uuid4().hex[:18]
password=uuid.uuid4().hex

with sync_playwright() as p:
    browser=p.chromium.launch()
    first=browser.new_context(viewport={'width':320,'height':900},has_touch=True,is_mobile=True)
    second=browser.new_context(viewport={'width':390,'height':900},has_touch=True,is_mobile=True)
    friend=browser.new_context(viewport={'width':1280,'height':900})
    pages=[ctx.new_page() for ctx in [first,second,friend]]
    a,b,c=pages
    errors=[]
    for page in pages:page.on('pageerror',lambda e:errors.append(str(e)))
    a.goto(BASE)
    a.locator('#name').fill('端末引き継ぎ確認')
    a.locator('#profile-form button[type=submit]').click()
    expect(a.locator('.cell')).to_have_count(36)
    original=a.request.get(BASE+'/api/games/current').json()
    identity=a.request.get(BASE+'/api/me').json()['id']
    def flag(page,i):
        page.locator('.cell').nth(i).scroll_into_view_if_needed()
        box=page.locator('.cell').nth(i).bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.mouse.down();page.wait_for_timeout(650);page.mouse.up()
    # Guest notes from another difficulty are migrated at registration too.
    a.locator('[data-level="medium"]').click()
    expect(a.locator('.cell')).to_have_count(49)
    medium=a.request.get(BASE+'/api/games/current?difficulty=medium').json()
    flag(a,48)
    a.locator('[data-level="easy"]').click()
    expect(a.locator('.cell')).to_have_count(36)
    with a.expect_response(lambda r:r.url.endswith('/api/games') and r.request.method=='POST') as next_game:
        a.locator('#advance').click()
    original=next_game.value.json()
    expect(a.locator('#puzzle-label')).to_contain_text(original['puzzle']['id'][:8].upper())
    flag(a,0)
    a.locator('.cell').nth(1).tap()
    a.locator('#account-button').click()
    a.locator('#login-id').fill(username)
    a.locator('#account-password').fill(password)
    a.locator('#password-confirm').fill(password)
    a.locator('#account-submit').click()
    expect(a.locator('#account-dialog')).not_to_be_visible()
    expect(a.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
    # wait_for_function polls with eval, which this app's CSP blocks.
    for _ in range(200):
        if a.evaluate("game.memo_revision>0"):
            break
        a.wait_for_timeout(50)
    else:
        raise AssertionError('memo revision was not saved')
    assert a.request.get(BASE+'/api/me').json()['id']==identity
    assert a.request.get(BASE+'/api/me').json()['points']==0
    assert a.request.get(BASE+'/api/games/'+medium['id']).json()['memos'][48]==3
    b.goto(BASE)
    b.locator('#profile-login').click()
    b.locator('#login-id').fill(username)
    b.locator('#account-password').fill(password)
    b.locator('#account-submit').click()
    expect(b.locator('.cell')).to_have_count(36)
    expect(b.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
    expect(b.locator('.cell').nth(1)).to_have_text('×')
    assert b.request.get(BASE+'/api/me').json()['id']==identity
    assert b.request.get(BASE+'/api/games/current').json()['id']==original['id']
    # Edits from a different device survive refresh on the first.
    flag(b,2);b.wait_for_timeout(650)
    a.reload()
    expect(a.locator('.cell').nth(2).locator('.flag')).to_have_count(1)
    expect(a.locator('.cell').nth(0).locator('.flag')).to_have_count(1)
    # Offline local changes are merged with unrelated changes on the other device.
    first.set_offline(True)
    flag(a,3)
    b.locator('.cell').nth(4).tap();b.wait_for_timeout(700)
    first.set_offline(False)
    a.evaluate("window.dispatchEvent(new Event('online'))")
    a.wait_for_timeout(1000)
    b.reload()
    expect(b.locator('.cell').nth(3).locator('.flag')).to_have_count(1)
    expect(b.locator('.cell').nth(4)).to_have_text('×')
    # Get the same share URL that the UI displays and open it anonymously.
    # A native share implementation must not hide the URL dialog.
    a.evaluate("Object.defineProperty(navigator,'share',{value:async()=>{window.nativeShares=(window.nativeShares||0)+1},configurable:true})")
    a.locator('#share-puzzle').click()
    expect(a.locator('#share-dialog')).to_be_visible()
    url=a.locator('#share-url').input_value()
    assert parse_qs(urlparse(url).query)['p']==[original['puzzle']['id']]
    expect(a.locator('#share-link')).to_have_attribute('href',url)
    expect(a.locator('#share-link')).to_have_text(url)
    assert a.evaluate('window.nativeShares||0')==0
    a.locator('#native-share').click()
    assert a.evaluate('window.nativeShares')==1
    # Verify an actual browser clipboard before testing denied/unsupported paths.
    first.grant_permissions(['clipboard-read','clipboard-write'],origin=BASE)
    a.bring_to_front()
    a.locator('#copy-share').click()
    expect(a.locator('#share-status')).to_contain_text('コピーしました')
    assert a.evaluate('navigator.clipboard.readText()')==url
    # Clipboard success, denial with legacy fallback, and total failure are distinct.
    a.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedUrl=text}},configurable:true})")
    a.locator('#copy-share').click()
    expect(a.locator('#share-status')).to_contain_text('コピーしました')
    assert a.evaluate('window.copiedUrl')==url
    a.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw new DOMException('denied','NotAllowedError')}},configurable:true});document.execCommand=command=>{window.copyFallback=command;return true}")
    a.locator('#copy-share').click()
    expect(a.locator('#share-status')).to_contain_text('コピーしました')
    assert a.evaluate('window.copyFallback')=='copy'
    a.evaluate("Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});document.execCommand=()=>false")
    a.locator('#copy-share').click()
    expect(a.locator('#share-status')).to_contain_text('自動コピーできませんでした')
    assert a.locator('#share-url').evaluate('(el)=>el.selectionStart===0 && el.selectionEnd===el.value.length')
    a.locator('#close-share').click()
    a.evaluate("Object.defineProperty(navigator,'share',{value:undefined,configurable:true})")
    a.locator('#share-puzzle').click()
    expect(a.locator('#native-share')).to_be_hidden()
    expect(a.locator('#share-link')).to_have_attribute('href',url)
    a.locator('#close-share').click()
    # An embedded page with clipboard blocked still exposes a usable URL.
    embedded=first.new_page()
    # Production deliberately disallows framing. Remove only that response header
    # in this test to exercise clipboard restrictions in an embedded browser.
    def allow_test_frame(route):
        response=route.fetch()
        headers=dict(response.headers)
        headers.pop('content-security-policy',None)
        route.fulfill(response=response,headers=headers)
    embedded.route(BASE+'/',allow_test_frame)
    embedded.goto(BASE)
    embedded.set_content('<iframe title="embedded game" src="'+BASE+'" style="width:300px;height:800px"></iframe>')
    frame=embedded.frame_locator('iframe')
    expect(frame.locator('.cell')).to_have_count(36)
    frame.locator('#share-puzzle').click()
    expect(frame.locator('#share-dialog')).to_be_visible()
    frame.locator('#share-url').evaluate("()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw new DOMException('blocked','NotAllowedError')}},configurable:true});document.execCommand=()=>false}")
    frame.locator('#copy-share').click()
    expect(frame.locator('#share-status')).to_contain_text('自動コピーできませんでした')
    expect(frame.locator('#share-link')).to_have_attribute('href',url)
    assert frame.locator('#share-url').input_value()==url
    embedded.close()
    c.goto(url)
    expect(c.locator('#shared-dialog')).to_be_visible()
    c.locator('#play-shared').click()
    c.locator('#name').fill('共有盤面確認')
    c.locator('#profile-form button[type=submit]').click()
    expect(c.locator('.cell')).to_have_count(36)
    state=c.request.get(BASE+'/api/games/current').json()
    assert state['puzzle']==original['puzzle'] and state['id']!=original['id']
    assert state['stars']==[] and state['mistakes']==0
    for i in [0,1,2,3,4]:expect(c.locator('.cell').nth(i)).to_have_text('')
    # A recipient cannot access the sender's saved game.
    assert c.request.get(BASE+'/api/games/'+original['id']).status==404
    assert a.request.get(BASE+'/api/me').json()['points']==0
    assert b.request.get(BASE+'/api/me').json()['points']==0
    assert c.request.get(BASE+'/api/me').json()['points']==0
    for page in pages:
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    print('PASS: guest upgrade, two-device login/resume, flags/X, offline merge, shared URL, private attempts, zero points')
    for ctx in [first,second,friend]:ctx.close()
    browser.close()
