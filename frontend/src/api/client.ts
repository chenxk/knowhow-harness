import type {
  EvalResult,
  MemoryItem,
  Meta,
  Session,
  SessionSummary,
  StreamEvent,
} from './types'

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T | { detail?: string }
  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string'
        ? data.detail
        : `请求失败 (${response.status})`
    throw new Error(detail)
  }
  return data as T
}

export async function fetchMeta(): Promise<Meta> {
  return readJson(await fetch('/api/meta'))
}

export async function listSessions(): Promise<SessionSummary[]> {
  return readJson(await fetch('/api/sessions'))
}

export async function createSession(title = '新对话'): Promise<Session> {
  return readJson(
    await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  )
}

export async function getSession(sessionId: string): Promise<Session> {
  return readJson(await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`))
}

export async function renameSession(sessionId: string, title: string): Promise<Session> {
  return readJson(
    await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  )
}

export async function deleteSession(sessionId: string): Promise<void> {
  await readJson(await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }))
}

export async function listMemories(): Promise<MemoryItem[]> {
  return readJson(await fetch('/api/memories'))
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await readJson(
    await fetch(`/api/memories/${encodeURIComponent(memoryId)}`, { method: 'DELETE' }),
  )
}

export async function postScore(traceId: string, value: number, comment: string): Promise<void> {
  await readJson(
    await fetch('/api/scores', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trace_id: traceId, value, comment }),
    }),
  )
}

export async function runEval(): Promise<EvalResult> {
  return readJson(await fetch('/api/eval', { method: 'POST' }))
}

export async function* streamChat(
  sessionId: string,
  question: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, question }),
    signal,
  })
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(data?.detail ?? `请求失败 (${response.status})`)
  }
  if (!response.body) {
    throw new Error('浏览器不支持流式响应')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const line = block.split('\n').find((item) => item.startsWith('data: '))
      if (!line) continue
      yield JSON.parse(line.slice(6)) as StreamEvent
    }
  }
}
