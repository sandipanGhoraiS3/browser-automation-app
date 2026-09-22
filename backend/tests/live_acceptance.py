"""Real Azure + MCP acceptance test using a harmless local dashboard."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from app.agent.providers import configured
from app.config import DATA

class Dashboard(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        if self.path.startswith('/report.csv'):
            self.send_header('Content-Type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="daily-report.csv"')
            self.end_headers()
            self.wfile.write(b'customer,sales\nAlpha,125\nBeta,250\n')
        else:
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''<!doctype html><title>Daily Sales Dashboard</title><style>body{font:18px system-ui;padding:45px;color:#234}table{border-collapse:collapse}td,th{padding:20px;border:1px solid #abc}section{height:2600px;background:linear-gradient(#eef6ef,#b5d5bc);padding:30px;margin-top:40px}</style><h1>Daily Sales Report</h1><p>Date: 2026-09-16. Timezone: Asia/Kolkata. All records for today.</p><table><tr><th>Customer</th><th>Sales</th></tr><tr><td>Alpha</td><td>125</td></tr><tr><td>Beta</td><td>250</td></tr></table><p>Total records: 2. Total sales: 375.</p><a href="/report.csv" download>Download Report CSV</a><section><h2>Report notes</h2><p>Local acceptance test. No authentication or external account.</p></section><footer>End of full-page report</footer>''')
    def log_message(self, *args):
        pass

async def main():
    if not configured('azure'):
        raise RuntimeError('Configure Azure credentials locally before running this real provider test.')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Dashboard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', trust_env=False, timeout=120) as client:
            response = await client.post('/api/conversations', json={'title': 'Acceptance - daily report'})
            response.raise_for_status()
            cid = response.json()['id']
            response = await client.post('/api/sessions', json={'conversation_id': cid})
            response.raise_for_status()
            message = f'Run skill: daily_report\nUse dashboard http://127.0.0.1:{server.server_port}/. Today is 2026-09-16 in Asia/Kolkata. Collect customer and sales for the two records. Download the CSV and save it through the File Agent in reports with a unique filename. Save a full-page screenshot alongside it. No external accounts are involved.'
            response = await client.post('/api/chat', json={'session_id': cid, 'message': message, 'provider': 'azure'})
            response.raise_for_status()
            seen = set()
            for _ in range(240):
                await asyncio.sleep(1)
                state = (await client.get('/api/sessions/' + cid)).json()
                for action in state['activity']:
                    key = (action['id'], action['status'])
                    if key not in seen:
                        print(action.get('category'), action['name'], action['status'], action['description'], flush=True)
                        seen.add(key)
                if state.get('confirmation'):
                    raise RuntimeError('Unexpected confirmation requested: ' + state['confirmation']['description'])
                if state['status'] == 'idle':
                    break
            else:
                await client.post('/api/chat/stop', json={'session_id': cid})
                raise RuntimeError('Acceptance run timed out')
            history = (await client.get('/api/conversations/' + cid)).json()
            print('FINAL:', history['messages'][-1]['content'], flush=True)
            assert history['messages'][-1]['role'] != 'error', history['messages'][-1]['content']
            assert any(a['name'] in ('Download completed', 'Save Download') and a['status'] == 'success' for a in state['activity']), 'No successful file download save'
            assert any(a['name'] == 'Save Screenshot' and a['status'] == 'success' for a in state['activity']), 'No successful screenshot save'
            assert state['browser']['status'] == 'connected'
            response = await client.post('/api/browser/screenshot', json={'session_id': cid, 'mode': 'full_page'})
            response.raise_for_status()
            artifact = {'session_id': cid, 'screenshot_version': response.json()['version'], 'completed_at': time.time()}
            (DATA / 'test-artifacts').mkdir(exist_ok=True)
            (DATA / 'test-artifacts/acceptance.json').write_text(json.dumps(artifact))
            print('PASS: real Azure to skill to MCP to PC Downloads and full-page screenshot; browser remains open', flush=True)
    finally:
        server.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
