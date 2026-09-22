export const API = 'http://localhost:8000'
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(API + path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || `Request failed (${response.status})`) }
  return response.json()
}

export async function apiForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(API + path, { method: 'POST', body })
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || `Request failed (${response.status})`) }
  return response.json()
}
