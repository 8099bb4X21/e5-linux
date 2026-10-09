"""Loading/error feedback with delayed responses; fixtures only, no device I/O."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fixtures', type=Path, required=True)
    ap.add_argument('--webroot', type=Path, required=True)
    args = ap.parse_args()
    fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
    fixtures['/api/status']['screen'].update(idle=0, lock_enabled=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            path = urlsplit(self.path).path
            if not path.startswith('/api/'): return super().do_GET()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(fixtures.get(path, {})).encode())
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser = p.chromium.launch(**({'executable_path': str(chrome)} if chrome.exists() else {}))
        page = browser.new_page(viewport={'width': 320, 'height': 480})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.wait_for_function("typeof last !== 'undefined' && last !== null")
        page.wait_for_timeout(400)
        # Gate selected GETs without slowing the status loop or invoking AT.
        page.evaluate('''() => {
            const realFetch = window.fetch;
            window.gates = {}; window.readCounts = {};
            window.fetch = (path, options) => {
                readCounts[path] = (readCounts[path] || 0) + 1;
                if (!gates[path]) return realFetch(path, options);
                return new Promise(resolve => gates[path].resolve = (body, code=200) =>
                    resolve(new Response(JSON.stringify(body), {status:code})));
            };
        }''')
        page.evaluate("gates['/api/sms']={};showPage(P.sms);loadSms();void loadSms()")
        page.wait_for_function("!!gates['/api/sms'].resolve")
        page.wait_for_timeout(200)
        loader = page.locator('.page.is-current > .screen-loading')
        assert loader.is_visible()
        assert page.evaluate("readCounts['/api/sms']") == 1, 'Repeated opens must share the request'
        assert loader.locator('i').evaluate("e=>getComputedStyle(e).animationPlayState") == 'running'
        page.evaluate("gates['/api/sms'].resolve({messages:[{id:10,number:'TEST',text:'Keep this message'}]})")
        page.wait_for_function("smsList.length === 1")
        assert loader.is_hidden()
        page.evaluate("void loadSms()")
        page.wait_for_timeout(200)
        assert loader.is_visible()
        assert 'Keep this message' in page.locator('#sms-list').inner_text()
        # An offscreen/blank spinner pauses, and a late reply stays on its page.
        page.evaluate('showPage(P.overview)')
        assert page.evaluate("getComputedStyle(pages[P.sms].querySelector('.screen-loading i')).animationPlayState") == 'paused'
        page.evaluate("gates['/api/sms'].resolve({},503)")
        page.wait_for_function("loadState(P.sms).error")
        assert 'Keep this message' in page.locator('#sms-list').inner_text()
        assert page.evaluate('page') == 0
        page.evaluate('showPage(P.sms)')
        page.wait_for_timeout(200)
        assert loader.is_visible()
        page.evaluate("gates['/api/sms'].resolve({messages:[]})")
        page.wait_for_function('smsList.length === 0')
        assert loader.is_hidden()
        # Details continue spinning between HTTP replies while radio data is
        # pending, then stop on completion; a later refresh starts normally.
        page.evaluate("gates['/api/advanced']={};showPage(P.adv_info)")
        page.wait_for_function("!!gates['/api/advanced'].resolve")
        page.evaluate("gates['/api/advanced'].resolve({radio_pending:true,device:{}})")
        page.wait_for_function('loadState(P.adv_info).pending')
        assert loader.is_visible()
        page.wait_for_timeout(900)
        page.evaluate("gates['/api/advanced'].resolve({radio_pending:false,device:{}})")
        page.wait_for_function('!loadState(P.adv_info).pending')
        assert loader.is_hidden()
        page.evaluate('void loadAdvanced()'); page.wait_for_timeout(200)
        assert loader.is_visible()
        page.evaluate("gates['/api/advanced'].resolve({},503)")
        page.wait_for_function('loadState(P.adv_info).error')
        assert loader.locator('i').is_hidden()
        assert '加载失败' in loader.inner_text()
        # Settings entry has the same progress feedback, with no duplicate
        # static loading label taking up a second row.
        page.evaluate("gates['/api/settings']={};stCats=null;showPage(P.settings)")
        page.wait_for_timeout(200)
        assert loader.is_visible()
        assert page.locator('#st-view').inner_text() == ''
        assert not errors, errors
        print('PASS: loading, retained SMS, errors, retry, request deduplication, hidden-page pause and staged details')
        browser.close()
    server.shutdown()


if __name__ == '__main__': main()
