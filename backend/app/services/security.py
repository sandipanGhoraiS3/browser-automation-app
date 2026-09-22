import re
from app.config import settings

def redact(text: str) -> str:
    for key in (settings.openai_api_key, settings.azure_openai_api_key, settings.anthropic_api_key):
        if key:
            text = text.replace(key, '[REDACTED]')
    text = re.sub(r'(?i)\b(password|passwd|api[_ -]?key|secret|token)\s*[:=]\s*["\']?[^\s,"\']+', r'\1=[REDACTED]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
