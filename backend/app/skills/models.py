from pydantic import BaseModel, ConfigDict, Field

class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    version: str = '1.0'
    category: str = Field(default='workflow', max_length=50)
    requires_browser: bool = True
    requires_files: bool = True
    knowledge_domain: str | None = Field(default=None, max_length=80)

class SkillDocument(BaseModel):
    metadata: SkillMetadata
    instructions: str
    markdown: str
    revision: str

class SkillName(BaseModel):
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')

class CreateSkill(BaseModel):
    metadata: SkillMetadata
    instructions: str = Field(min_length=30, max_length=50000, description='Reusable semantic Markdown steps with prerequisites, outputs, browser rules and recovery guidance. Never include element refs, coordinates or secrets.')

class EditSkill(BaseModel):
    markdown: str = Field(min_length=30, max_length=60000)
    revision: str = Field(description='Current revision from skill loading, to prevent overwriting concurrent edits.')

class NoArgs(BaseModel):
    pass
