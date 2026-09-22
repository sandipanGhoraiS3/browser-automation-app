import hashlib
import re
import threading
from pathlib import Path
import yaml
from app.config import ROOT, settings
from app.file_agent.security import WorkspacePolicy
from app.skills.models import SkillMetadata, SkillDocument, CreateSkill, SkillName
from app.services.security import redact

class SkillRegistry:
    def __init__(self, root=None):
        self.policy = WorkspacePolicy(Path(root) if root else ROOT / settings.skills_root)
        self.lock = threading.RLock()

    def parse(self, markdown: str, expected_name=None):
        if len(markdown) > 60000:
            raise ValueError('Skill is too large (maximum 60,000 characters).')
        match = re.fullmatch(r'---\s*\n(.*?)\n---\s*\n(.*)', markdown.strip(), re.S)
        if not match:
            raise ValueError('Skill must begin with YAML front matter enclosed by --- lines.')
        try:
            raw = yaml.safe_load(match[1])
            if isinstance(raw, dict) and 'version' in raw:
                raw['version'] = str(raw['version'])
            metadata = SkillMetadata.model_validate(raw)
        except Exception as exc:
            raise ValueError('Invalid skill metadata. Check name, display_name, description, version and capability fields.') from exc
        if expected_name and metadata.name != expected_name:
            raise ValueError('Skill name must match its folder name.')
        instructions = match[2].strip()
        required = ('preconditions', 'steps', 'output', 'browser rules', 'recovery')
        headings = {h.strip().lower() for h in re.findall(r'^##\s+(.+)$', instructions, re.M)}
        missing = [h for h in required if h not in headings]
        if missing:
            raise ValueError('Missing required sections: ' + ', '.join(missing))
        if re.search(r'\bref\s*[=:]?\s*[a-z]*\d+\b|\b(?:click|tap)\s*\(\s*\d+\s*,\s*\d+', instructions, re.I):
            raise ValueError('Skills must use semantic actions, not saved element references or coordinates.')
        if redact(markdown) != markdown:
            raise ValueError('Skill contains a credential pattern. Remove secrets before saving.')
        return SkillDocument(metadata=metadata, instructions=instructions, markdown=markdown, revision=hashlib.sha256(markdown.encode()).hexdigest())

    def path(self, name):
        SkillName(name=name)
        return self.policy.resolve(f'{name}/skill.md')

    def load(self, name):
        path = self.path(name)
        if not path.exists():
            raise ValueError(f'Skill "{name}" was not found.')
        if path.stat().st_size > 120000:
            raise ValueError('Skill file exceeds the size limit.')
        return self.parse(path.read_text(encoding='utf-8'), name)

    def discover(self):
        skills, errors = [], []
        for folder in sorted(self.policy.root.iterdir()):
            if not folder.is_dir():
                continue
            try:
                skills.append(self.load(folder.name).model_dump())
            except Exception as exc:
                errors.append({'name': folder.name, 'error': str(exc)[:300]})
        return {'skills': skills, 'errors': errors}

    def create(self, request: CreateSkill):
        markdown = '---\n' + yaml.safe_dump(request.metadata.model_dump(), sort_keys=False, allow_unicode=True) + '---\n\n' + request.instructions.strip() + '\n'
        document = self.parse(markdown, request.metadata.name)
        with self.lock:
            path = self.path(request.metadata.name)
            path.parent.mkdir(exist_ok=True)
            try:
                with path.open('x', encoding='utf-8') as target:
                    target.write(markdown)
            except FileExistsError as exc:
                raise ValueError('A skill with this name already exists. Choose a new name or edit it explicitly.') from exc
        return document

    def edit(self, name, markdown, revision):
        document = self.parse(markdown, name)
        with self.lock:
            if self.load(name).revision != revision:
                raise ValueError('This skill changed since you opened it. Reload before saving.')
            path = self.path(name)
            temporary = self.policy.resolve(f'{name}/skill.tmp')
            with temporary.open('x', encoding='utf-8') as target:
                target.write(markdown)
            temporary.replace(path)
        return document

    def delete(self, name):
        with self.lock:
            path = self.path(name)
            if not path.exists():
                raise ValueError('Skill was not found.')
            path.unlink()
            if not any(path.parent.iterdir()):
                path.parent.rmdir()

    def resolve_command(self, message):
        match = re.match(r'^\s*(?:/run\s+|run skill:\s*)([a-z][a-z0-9_]{0,63})(?:\s+([\s\S]*))?$', message, re.I)
        return self.load(match[1].lower()) if match else None

registry = SkillRegistry()
