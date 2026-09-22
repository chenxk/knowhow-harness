export type Action = 'retrieve' | 'tool' | 'answer'

export type ChatRole = 'user' | 'assistant'

export interface SessionMessage {
  role: ChatRole
  content: string
  action?: Action | null
  sources?: string[]
  tool_name?: string
  trace_id?: string | null
}

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: SessionMessage[]
}

export interface Meta {
  mode: string
  chat_model: string
  corpus_chunks: number
  tools: string[]
  skills: string[]
  tracing: boolean
  memory_count: number
}

export interface MemoryItem {
  id: string
  user_id: string
  content: string
  category: string
  source_session_id?: string | null
  created_at: string
  updated_at: string
  active: boolean
}

export interface EvalRow {
  case_id: string
  passed: boolean
  action: Action
  failures: string[]
}

export interface EvalResult {
  passed: number
  failed: number
  rows: EvalRow[]
  scored: boolean
}

export type StreamEvent =
  | {
      type: 'status' | 'delta' | 'done'
      text?: string
      action?: Action
      sources?: string[]
      tool_name?: string
      trace_id?: string | null
      answer?: string
    }
  | {
      type: 'session'
      id: string
      title: string
      updated_at: string
    }
  | { type: 'error'; text: string }

export interface TranscriptMessage {
  id: string
  role: ChatRole
  content: string
  action?: Action
  sources?: string[]
  tool_name?: string
  trace_id?: string | null
  pending?: boolean
  feedback?: number
}
