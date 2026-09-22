"""Real MCP/Chromium smoke test. Run manually: python -m tests.smoke_browser."""
import asyncio
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.sessions.manager import BrowserSession
from app.browser.state import observe, result_text

class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<title>Orbit browser test</title><h1>Real browser smoke test</h1><label>Name <input aria-label="Name"></label><button onclick="document.querySelector(\'h1\').textContent=\'Hello \'+document.querySelector(\'input\').value">Greet</button>')
    def log_message(self, *args):
        pass

async def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    session = BrowserSession(str(uuid.uuid4()))
    second = BrowserSession(str(uuid.uuid4()))
    try:
        await session.mcp.start()
        print('MCP connected; discovered', len(session.mcp.tools), 'tools')
        result = await session.mcp.call('browser_navigate', {'url': f'http://127.0.0.1:{server.server_port}'})
        assert not result.isError, result_text(result)
        snapshot = await observe(session)
        field = re.search(r'textbox "Name" \[ref=([^\]]+)\]', snapshot).group(1)
        type_schema = next(t.inputSchema for t in session.mcp.tools if t.name == 'browser_type')
        ref_key = 'target' if 'target' in type_schema['properties'] else 'ref'
        result = await session.mcp.call('browser_type', {'element': 'Name', ref_key: field, 'text': 'Orbit'})
        assert not result.isError, result_text(result)
        snapshot = await observe(session, screenshot=False)
        button = re.search(r'button "Greet" \[ref=([^\]]+)\]', snapshot).group(1)
        click_schema = next(t.inputSchema for t in session.mcp.tools if t.name == 'browser_click')
        ref_key = 'target' if 'target' in click_schema['properties'] else 'ref'
        result = await session.mcp.call('browser_click', {'element': 'Greet', ref_key: button})
        assert not result.isError, result_text(result)
        snapshot = await observe(session)
        assert 'Hello Orbit' in snapshot
        assert session.screenshot, 'Screenshot missing'
        # Cancel a real in-flight MCP wait, then prove the same page survives.
        session.task = asyncio.create_task(session.mcp.call('browser_wait_for', {'time': 20}))
        await asyncio.sleep(.5)
        await session.cancel()
        assert session.mcp.status == 'connected'
        assert 'Hello Orbit' in await observe(session, screenshot=False)
        await second.mcp.start()
        assert second.mcp.process.pid != session.mcp.process.pid
        other = await observe(second, screenshot=False)
        assert 'Hello Orbit' not in other
        print('PASS: navigate, fresh snapshot, type, click, screenshot, cancellation preserving browser, isolated sessions')
    finally:
        await session.close()
        await second.close()
        server.shutdown()
        print('All test browser processes cleaned up')

if __name__ == '__main__':
    asyncio.run(main())
