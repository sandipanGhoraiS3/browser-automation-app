from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    openai_api_key: str = ''
    openai_model: str = 'gpt-4.1'
    azure_openai_api_key: str = ''
    azure_openai_endpoint: str = ''
    azure_openai_deployment: str = ''
    azure_openai_api_version: str = '2024-10-21'
    anthropic_api_key: str = ''
    anthropic_model: str = 'claude-sonnet-4-5'
    temperature: float = 0
    max_agent_steps: int = 50
    max_tool_retries: int = 2
    session_idle_timeout: int = 3600
    playwright_mcp_command: str = 'npx'
    playwright_mcp_package: str = '@playwright/mcp'
    headless: bool = False
    browser_executable_path: str = ''
    file_workspace_root: str = './data/workspace'
    file_max_bytes: int = 20_000_000
    skills_root: str = './skills'
    azure_cosmos_endpoint: str = ''
    azure_cosmos_key: str = ''
    azure_cosmos_database: str = 'orbit-rag'
    azure_cosmos_container: str = 'knowledge'
    azure_blob_account_url: str = ''
    azure_blob_account_name: str = ''
    azure_blob_container: str = 'knowledge'
    azure_blob_connection_string: str = ''
    azure_blob_sas_token: str = ''
    azure_storage_account_name: str = ''
    azure_storage_account_key: str = ''
    azure_storage_connection_string: str = ''
    azure_storage_container_name: str = ''
    rag_embedding_provider: str = 'azure'
    rag_embedding_model: str = 'text-embedding-3-small'
    rag_embedding_dimensions: int = 1536
    rag_azure_openai_api_key: str = ''
    rag_azure_openai_endpoint: str = ''
    rag_azure_openai_api_version: str = ''
    rag_top_k: int = 8
    rag_candidate_k: int = 24
    rag_min_score: float = 0.15
    rag_chunk_size: int = 750
    rag_chunk_overlap: int = 100
    rag_max_context_tokens: int = 6000
    rag_embedding_batch_size: int = 16
    rag_max_upload_bytes: int = 50_000_000
    rag_max_queries: int = 3
    rag_background_concurrency: int = 2
    debug_rag: bool = False

settings = Settings()
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
