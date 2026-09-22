import base64
import re
import time
import asyncio
from app.browser.downloads import detect_downloads

def result_text(result):
    return '\n'.join(block.text for block in result.content if block.type == 'text')

async def capture(session, mode='viewport'):
    if mode not in ('viewport', 'full_page'):
        raise ValueError('Invalid screenshot mode.')
    async with session.capture_lock:
        schema = next(t.inputSchema for t in session.mcp.tools if t.name == 'browser_take_screenshot')
        args = {'type': 'png', 'fullPage': mode == 'full_page'}
        if 'scale' in schema.get('properties', {}):
            args['scale'] = 'css'
        shot = await session.mcp.call('browser_take_screenshot', args)
        if shot.isError:
            raise ValueError('Unable to capture screenshot. Check that the browser has an open page and try again.')
        for block in shot.content:
            if block.type == 'image':
                image = base64.b64decode(block.data)
                if len(image) > 60_000_000:
                    raise ValueError('Screenshot is too large. Use a viewport capture for this page.')
                path = session.mcp.directory / 'screenshots' / ('latest.png' if mode == 'viewport' else 'full_page.png')
                path.parent.mkdir(exist_ok=True)
                temporary = path.with_suffix('.tmp')
                await asyncio.to_thread(temporary.write_bytes, image)
                temporary.replace(path)
                version = time.time()
                session.screenshots[mode] = version
                if mode == 'viewport':
                    session.screenshot = version
                return {'mode': mode, 'version': version, 'path': path}
        raise ValueError('The browser did not return an image. Try capturing again.')

async def observe(session, screenshot=True):
    result = await session.mcp.call('browser_snapshot', {})
    text = result_text(result)
    if result.isError:
        raise RuntimeError(text)
    session.snapshot = text
    await detect_downloads(session, text)
    url = re.search(r'Page URL: (.+)', text)
    session.url = url.group(1).strip() if url else session.url
    tabs = await session.mcp.call('browser_tabs', {'action': 'list'})
    session.tabs = result_text(tabs)
    if screenshot:
        try:
            await capture(session, 'viewport')
        except asyncio.CancelledError:
            raise
        except Exception:
            # Preview capture is auxiliary; a page snapshot remains valid if the image fails.
            pass
    await session.emit({'type': 'browser', **session.browser_state()})
    return text

