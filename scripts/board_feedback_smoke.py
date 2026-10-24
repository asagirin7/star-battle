"""Local browser checks for region progress and gesture-only sound feedback."""
import os,sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions
BASE=os.getenv('BASE_URL','http://127.0.0.1:8000')
assert urlparse(BASE).hostname in {'localhost','127.0.0.1','::1'}
AUDIO='''window.soundStarts=0;window.soundNotes=[];window.AudioContext=class {state='running';currentTime=10;destination={};resume(){this.state='running';return Promise.resolve()}suspend(){this.state='suspended';return Promise.resolve()}createOscillator(){const item={note:0,connect(){},disconnect(){},start(){window.soundStarts++;window.soundNotes.push(item.note)},stop(){}};item.frequency={setValueAtTime(n){item.note=n},exponentialRampToValueAtTime(){}};return item}createGain(){return {gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}}}};'''
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in [320,390,1280]:
  context=browser.new_context(viewport={'width':width,'height':900})
  context.add_init_script(AUDIO)
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE);page.locator('#name').fill(f'音と色{width}');page.get_by_role('button',name='この名前ではじめる').click()
  expect(page.locator('.cell')).to_have_count(36)
  assert page.locator('#reset').count()==0
  expect(page.locator('#undo')).to_be_disabled()
  expect(page.locator('.region-chip')).to_have_count(6)
  assert page.locator('.region-chip.placed').count()==0
  page.locator('.cell').first.click();expect(page.locator('.cell').first).to_have_text('×')
  assert page.evaluate('soundStarts')==1
  assert page.locator('.region-chip.placed').count()==0
  page.locator('#sound-toggle').click();expect(page.locator('#sound-toggle')).to_have_attribute('aria-pressed','false')
  page.locator('.cell').nth(1).click();assert page.evaluate('soundStarts')==1
  page.reload();expect(page.locator('#sound-toggle')).to_have_attribute('aria-pressed','false');assert page.evaluate('soundStarts')==0
  page.locator('#sound-toggle').click()
  game=page.request.get(BASE+'/api/games/current').json();col=solutions(game['puzzle']['regions'])[0][0]
  page.locator('.cell').nth(col).dblclick(delay=60)
  expect(page.locator('.region-chip.placed')).to_have_count(1)
  assert page.evaluate('soundNotes.filter(n=>n===760).length')==1
  wrong=(solutions(game['puzzle']['regions'])[0][1]+1)%6
  page.locator('.cell').nth(6+wrong).dblclick(delay=60)
  expect(page.locator('#lives')).to_have_attribute('aria-label','残機 2、ミス 1回')
  assert page.evaluate('soundNotes.filter(n=>n===760).length')==1
  region=game['puzzle']['regions'][0][col]
  expect(page.locator('.region-chip').nth(region)).to_have_attribute('aria-label',f'エリア{region+1}、星を配置済み')
  before=page.evaluate('soundStarts');page.locator('#auto-cross').click();assert page.evaluate('soundStarts')==before
  page.evaluate('render()');assert page.evaluate('soundStarts')==before
  page.reload();expect(page.locator('.region-chip.placed')).to_have_count(1);assert page.evaluate('soundStarts')==0
  # Nine chips must fit at the smallest phone width, including the special-board palette.
  page.evaluate('''() => {puzzle={...puzzle,id:'layout-nine',size:9,regions:Array.from({length:9},(_,r)=>Array(9).fill(r))};cells=Array(81).fill(0);game={...game,stars:[[0,0]]};render();}''')
  expect(page.locator('.region-chip')).to_have_count(9)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  context.close();print(f'PASS {width}px: confirmed region status, sound gesture/on/off/reload, nine-chip layout')
 browser.close()
