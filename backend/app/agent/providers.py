import json
from dataclasses import dataclass
from openai import AsyncOpenAI, AsyncAzureOpenAI
from anthropic import AsyncAnthropic
from app.config import settings

_NO_TEMPERATURE_MODELS = set()


def _temperature_unsupported(exc: Exception) -> bool:
    status = getattr(exc, 'status_code', None)
    response = getattr(exc, 'response', None)
    status = status or getattr(response, 'status_code', None)
    text = str(exc).lower()
    return status == 400 and 'temperature' in text and (
        'unsupported' in text or 'does not support' in text
    )


async def _create_chat_stream(client, request: dict, model_key: tuple[str, str]):
    prepared = dict(request)
    if model_key in _NO_TEMPERATURE_MODELS:
        prepared.pop('temperature', None)
    try:
        return await client.chat.completions.create(**prepared)
    except Exception as exc:
        if 'temperature' not in prepared or not _temperature_unsupported(exc):
            raise
        _NO_TEMPERATURE_MODELS.add(model_key)
        prepared.pop('temperature')
        return await client.chat.completions.create(**prepared)


def compact_messages(messages, max_chars=70000):
    """Keep the current user request and newest complete tool exchanges within budget."""
    if len(json.dumps(messages, ensure_ascii=False)) <= max_chars:
        return messages

    anchor = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') == 'user' and isinstance(message.get('content'), str):
            anchor = index
            break

    start = (anchor + 1) if anchor is not None else 0
    units = []
    index = start
    while index < len(messages):
        unit = [messages[index]]
        if messages[index].get('role') == 'assistant' and index + 1 < len(messages):
            following = messages[index + 1]
            if following.get('role') == 'tool' or (
                following.get('role') == 'user' and isinstance(following.get('content'), list)
            ):
                unit.append(following)
                index += 1
        units.append(unit)
        index += 1

    prefix = [messages[anchor]] if anchor is not None else []
    used = len(json.dumps(prefix, ensure_ascii=False))
    selected = []
    for unit in reversed(units):
        size = len(json.dumps(unit, ensure_ascii=False))
        if selected and used + size > max_chars:
            break
        if used + size <= max_chars:
            selected.append(unit)
            used += size
    return prefix + [message for unit in reversed(selected) for message in unit]
@dataclass
class Decision:
    text: str
    calls: list

def configured(provider):
    return bool({'openai': settings.openai_api_key, 'azure': settings.azure_openai_api_key and settings.azure_openai_endpoint and settings.azure_openai_deployment, 'anthropic': settings.anthropic_api_key}.get(provider))

async def decide(provider, system, messages, tools, emit):
    if not configured(provider):
        raise RuntimeError(f'Configure {provider} credentials in browser-agent/.env and restart the backend.')
    if provider == 'anthropic':
        async with AsyncAnthropic(api_key=settings.anthropic_api_key) as client:
            request = dict(model=settings.anthropic_model, max_tokens=4096, temperature=settings.temperature, system=system, messages=messages)
            if tools:
                request.update(tools=[{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools], tool_choice={'type': 'auto', 'disable_parallel_tool_use': True})
            async with client.messages.stream(**request) as stream:
                async for part in stream.text_stream:
                    await emit({'type': 'delta', 'text': part})
                message = await stream.get_final_message()
            text = ''.join(b.text for b in message.content if b.type == 'text')
            calls = [{'id': b.id, 'name': b.name, 'arguments': b.input} for b in message.content if b.type == 'tool_use']
            return Decision(text, calls)
    client = AsyncAzureOpenAI(api_key=settings.azure_openai_api_key, azure_endpoint=settings.azure_openai_endpoint, api_version=settings.azure_openai_api_version) if provider == 'azure' else AsyncOpenAI(api_key=settings.openai_api_key)
    async with client:
        request = dict(model=settings.azure_openai_deployment if provider == 'azure' else settings.openai_model, messages=[{'role': 'system', 'content': system}, *messages], temperature=settings.temperature, stream=True)
        if tools:
            request.update(tools=[{'type': 'function', 'function': t} for t in tools], parallel_tool_calls=False)
        model_key = (provider, request['model'])
        stream = await _create_chat_stream(client, request, model_key)
        content, calls = '', {}
        async with stream:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    await emit({'type': 'delta', 'text': delta.content})
                for tool in delta.tool_calls or []:
                    entry = calls.setdefault(tool.index, {'id': '', 'name': '', 'raw': ''})
                    if tool.id:
                        entry['id'] = tool.id
                    if tool.function:
                        entry['name'] += tool.function.name or ''
                        entry['raw'] += tool.function.arguments or ''
        return Decision(content, [{'id': c['id'], 'name': c['name'], 'arguments': json.loads(c['raw'])} for c in calls.values()])

def append_result(messages, decision, result, provider):
    call = decision.calls[0]
    if provider == 'anthropic':
        blocks = ([{'type': 'text', 'text': decision.text}] if decision.text else []) + [{'type': 'tool_use', 'id': call['id'], 'name': call['name'], 'input': call['arguments']}]
        messages.extend([{'role': 'assistant', 'content': blocks}, {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': call['id'], 'content': result}]}])
    else:
        messages.extend([{'role': 'assistant', 'content': decision.text or None, 'tool_calls': [{'id': call['id'], 'type': 'function', 'function': {'name': call['name'], 'arguments': json.dumps(call['arguments'])}}]}, {'role': 'tool', 'tool_call_id': call['id'], 'content': result}])

