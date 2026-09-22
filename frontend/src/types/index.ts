export type Provider = 'openai' | 'azure' | 'anthropic'
export interface Conversation { id: string; title: string; updated_at: string }
export interface Workspace { id: string; name: string; created_at: string }
export interface KnowledgeSource { chunk_id: string; document_id: string; file_name: string; page_number?: number | null; section?: string | null; score: number }
export interface Message { id: string; role: string; content: string; created_at: string; sources?: KnowledgeSource[]; retrieval?: { source_count: number; chunk_count: number; domain_id?: string | null }; rag_debug?: unknown }
export interface Activity { id: string; category?: 'browser' | 'file' | 'skill' | 'agent' | 'knowledge'; name: string; description: string; status: string; duration?: number; details?: string }
export interface BrowserState { status: string; url: string; tabs: string; screenshot: number }
export interface Confirmation { id: string; description: string }
export interface Health { status: string; mcp: string; providers: Record<Provider, boolean>; models: Record<Provider, string>; max_steps: number; idle_timeout: number }
export type ScreenshotMode = 'viewport' | 'full_page'
export interface ScreenshotState { imageUrl: string; mode: ScreenshotMode; zoom: number }
export interface SkillMetadata { name: string; display_name: string; description: string; version: string; category: string; requires_browser: boolean; requires_files: boolean; knowledge_domain?: string | null }
export interface Skill { metadata: SkillMetadata; instructions: string; markdown: string; revision: string }
export interface KnowledgeDomain { id: string; workspace_id: string; name: string; description: string; document_count: number; ready_count: number; storage_bytes: number; last_indexed?: string | null }
export interface KnowledgeDocument { id: string; workspace_id: string; domain_id: string; file_name: string; content_type: string; file_size: number; status: string; progress: number; chunk_count: number; page_count?: number | null; created_at: string; updated_at: string; indexed_at?: string | null; error?: string | null }
export interface RagHealth { configured: boolean; services: Record<'cosmos' | 'blob' | 'embedding', { status: string; reason?: string; latency_ms?: number }> }
export interface SourcePreview { id: string; document_id: string; domain_id: string; source_file: string; page_number?: number | null; section?: string | null; text: string; chunk_index: number }
