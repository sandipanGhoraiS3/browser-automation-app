"""Real Azure follow-up tests: archive a report, save a workflow, run test_skill."""
import asyncio
import json
import time
import httpx
from app.config import DATA
from app.file_agent.service import downloads

async def wait_run(client, cid):
    for _ in range(180):
        await asyncio.sleep(1)
        state = (await client.get('/api/sessions/' + cid)).json()
        if state.get('confirmation'):
            raise RuntimeError('Unexpected confirmation: ' + state['confirmation']['description'])
        if state['status'] == 'idle':
            history = (await client.get('/api/conversations/' + cid)).json()
            print(history['messages'][-1]['content'], flush=True)
            assert history['messages'][-1]['role'] != 'error'
            return state
    raise RuntimeError('Run timed out')

async def main():
    artifact = json.loads((DATA / 'test-artifacts/acceptance.json').read_text())
    cid = artifact['session_id']
    skill_name = 'acceptance_workflow_' + str(int(time.time()))
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', trust_env=False, timeout=120) as client:
        response = await client.post('/api/chat', json={'session_id': cid, 'provider': 'azure', 'message': 'Create a folder called archive and move the CSV report you just downloaded there, keeping its filename. Leave the screenshot in reports. Confirm the saved path.'})
        response.raise_for_status()
        state = await wait_run(client, cid)
        assert any(a['name'] == 'Move File' and a['status'] == 'success' for a in state['activity'])
        assert list((downloads.policy.root / 'archive').glob('*.csv'))
        response = await client.post('/api/chat', json={'session_id': cid, 'provider': 'azure', 'message': 'Save the report workflow we completed as a reusable skill called ' + skill_name + '. Ask for the dashboard URL each run rather than storing this test localhost URL. Include Preconditions, Steps, Output, Browser Rules, Recovery. Do not run the workflow again.'})
        response.raise_for_status()
        state = await wait_run(client, cid)
        skill = await client.get('/api/skills/' + skill_name)
        skill.raise_for_status()
        assert skill.json()['metadata']['name'] == skill_name
        print('PASS: natural-language file archive and AI-generated reusable Markdown skill', flush=True)
        response = await client.post('/api/chat', json={'session_id': cid, 'provider': 'azure', 'message': 'Run skill: test_skill'})
        response.raise_for_status()
        state = await wait_run(client, cid)
        assert any(a['name'] == 'Create File' and a['status'] == 'success' for a in state['activity'])
        assert any(a['name'] == 'Read File' and a['status'] == 'success' for a in state['activity'])
        assert state['browser']['status'] == 'connected'
        print('PASS: explicit test_skill loaded and executed with real Azure, filesystem creation and readback', flush=True)
        await client.delete('/api/skills/' + skill_name)

if __name__ == '__main__':
    asyncio.run(main())
