"""Real phone UI + shell, fake call service; never places a real call."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--webroot',type=Path,required=True)
    a=ap.parse_args()
    fixtures=json.loads(a.fixtures.read_text(encoding='utf-8'))
    fixtures['/api/status']['screen'].update(idle=0,lock_enabled=False,touch=True)
    model={'calls':[],'contacts':[],'sim':{'card':0},'wake':True,
           'audio':{'available':True,'active':True,'speaker':False,'muted':False}}
    posts=[];fail_tone=[False]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,code=200):
            self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(value).encode())
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ['/api/plugins/phone/live','/api/plugins/phone/status']:return self.reply(model)
            if path.startswith('/api/'):return self.reply(fixtures.get(path,{}))
            return super().do_GET()
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            posts.append((self.path,body))
            if self.path=='/api/backlight':fixtures['/api/status']['screen']['awake']=body['level']>0
            if self.path.endswith('/dtmf'):
                if fail_tone[0]:return self.reply({'ok':False,'error':'simulated failure'},502)
                time.sleep(.06)
            if self.path.endswith('/answer'):model['calls']=[{**model['calls'][0],'state':'active'}]
            if self.path.endswith('/hangup'):model['calls']=[]
            return self.reply({'ok':True})
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(a.webroot)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with sync_playwright() as pw:
        exe=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser=pw.chromium.launch(executable_path=str(exe) if exe.exists() else None,headless=True)
        page=browser.new_page(viewport={'width':320,'height':480},has_touch=True,is_mobile=True)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.wait_for_function('last && !T551M.isLocked()')
        call={'id':'8','state':'active','number':'10010','sim':'SIM1','card':0,'direction':'outgoing'}
        model['calls']=[call]
        page.evaluate("openApp({id:'phone',name:'Phone',entry:'index.html'})")
        frame=page.frame_locator('#app-frame')
        frame.locator('#dtmf-toggle').wait_for(state='visible')
        frame.locator('#dtmf-toggle').tap()
        for digit in '1*#0':frame.locator(f'[data-tone="{digit}"]').tap()
        page.wait_for_function("document.querySelector('#app-frame').contentDocument.querySelector('#dtmf-digits').textContent==='1*#0'")
        assert [b for p,b in posts if p.endswith('/dtmf')]==[{'id':'8','tone':c} for c in '1*#0']
        bounds=frame.locator('#hangup').evaluate('e=>({bottom:e.getBoundingClientRect().bottom,height:innerHeight,width:document.body.scrollWidth})')
        assert bounds['bottom']<=bounds['height']+1 and bounds['width']<=320,bounds
        page.screenshot(path='logs/t551m/phone-dtmf.png')
        fail_tone[0]=True
        frame.locator('[data-tone="5"]').tap();page.wait_for_timeout(900)
        assert len([b for p,b in posts if p.endswith('/dtmf') and b['tone']=='5'])==1
        assert frame.locator('#feedback').is_visible()
        fail_tone[0]=False
        # A failed status read is not proof that the remote party hung up.
        model.update(error='temporary read error',calls=[]);page.wait_for_timeout(500)
        assert frame.locator('#call-card').is_visible()
        model.pop('error');model['calls']=[];page.wait_for_timeout(500)
        assert frame.locator('#dtmf-panel').is_hidden()
        page.evaluate('closeApp()')
        fixtures['/api/status']['screen']['lock_enabled']=True
        page.evaluate('last.screen.lock_enabled=true;T551M.status(last);setBlank(true)')
        page.wait_for_timeout(400)
        model['calls']=[{**call,'id':'9','state':'ringing-in','direction':'incoming'}]
        page.wait_for_function('T551MCalls.active() && !blank')
        frame.locator('#accept').wait_for(state='visible')
        frame.locator('#accept').evaluate('e=>e.click()')
        assert not [p for p,b in posts if p.endswith('/answer')], 'wake guard accepted a stray tap'
        assert page.evaluate('T551M.isLocked()'), 'incoming call unlocked the device'
        assert frame.locator('#dialer').is_hidden() and frame.locator('#contacts-panel').is_hidden()
        full=page.locator('#app-frame').bounding_box()
        assert full['height']>=440 and full['y']<35,full
        page.wait_for_timeout(650)
        page.screenshot(path='logs/t551m/phone-incoming.png')
        frame.locator('#accept').tap()
        frame.locator('#dtmf-toggle').wait_for(state='visible')
        frame.locator('#dtmf-toggle').tap();frame.locator('[data-tone="9"]').tap()
        page.wait_for_timeout(200)
        assert any(b=={'id':'9','tone':'9'} for p,b in posts if p.endswith('/dtmf'))
        started=time.monotonic();model['calls']=[]
        page.wait_for_function('!T551MCalls.active()',timeout=1500)
        delay=time.monotonic()-started
        assert delay<1,delay
        assert page.evaluate('T551M.isLocked()') and page.locator('#app-frame').is_hidden()
        # Respect an explicitly disabled wake preference and touch setting.
        model['wake']=False;page.evaluate('setBlank(true)')
        model['calls']=[{**call,'id':'10','state':'ringing-in'}];page.wait_for_timeout(700)
        assert page.evaluate('blank && !T551MCalls.active()')
        model['calls']=[];page.wait_for_timeout(400);model['wake']=True
        fixtures['/api/status']['screen']['touch']=False
        page.evaluate('last.screen.touch=false;T551M.status(last);applyTouch()')
        model['calls']=[{**call,'id':'11','state':'ringing-in'}]
        page.wait_for_function('T551MCalls.active() && !blank')
        frame.locator('#accept').wait_for(state='visible');page.wait_for_timeout(650)
        count=len([p for p,b in posts if p.endswith('/answer')])
        frame.locator('#accept').evaluate('e=>e.click()');page.wait_for_timeout(100)
        assert len([p for p,b in posts if p.endswith('/answer')])==count
        frame.locator('body').evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'F13',bubbles:true,cancelable:true}))")
        page.wait_for_timeout(500)
        assert len([p for p,b in posts if p.endswith('/answer')])==count+1
        assert not errors,errors
        print(json.dumps({'dtmf_order':'PASS','dtmf_no_retry':'PASS','incoming_wake':'PASS',
                          'lock_preserved':'PASS','touch_preference':'PASS','remote_end_ui_seconds':round(delay,3),'js_errors':errors}))
        browser.close()
    server.shutdown()


if __name__=='__main__':main()
