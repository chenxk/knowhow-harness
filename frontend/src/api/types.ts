export type Action = 'retrieve' | 'tool' | 'answer'

export type ChatRole = 'user' | 'assistant'

export interface SessionMessage {
  role: ChatRole
  content: string
  action?: Action | null
  sources?: string[]
  tool_name?: string
  trace_id?: string | null
  dissection?: TurnDissection | null
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
  status: 'pending' | 'active'
  hit_count: number
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
      type: 'status' | 'thinking' | 'delta' | 'done'
      text?: string
      action?: Action
      sources?: string[]
      tool_name?: string
      trace_id?: string | null
      answer?: string
      dissection?: TurnDissection | null
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
  thinking?: string
  action?: Action
  sources?: string[]
  tool_name?: string
  trace_id?: string | null
  pending?: boolean
  feedback?: number
  dissection?: TurnDissection | null
}

export interface LabPredicate {
  type: 'memory_active_contains' | 'memory_pending_contains' | 'memory_any_contains'
  needle: string
}

export interface LabStep {
  id: string
  label: string
  hint: string
  predicate: LabPredicate
}

export interface LabSpec {
  id: string
  title: string
  steps: LabStep[]
}

export interface HistoryLine {
  role: string
  chars: number
  preview: string
}

export interface TurnDissection {
  route: {
    action: Action
    tool_name: string
    sources: string[]
    query: string
  }
  why: { reason: string; detail: string }
  injected: {
    history_turns: number
    memories: string[]
    guidance_present: boolean
  }
  tool_output_summary: string
  trace_id: string | null
  tracing: boolean
  langfuse_hint: string | null
  user_visible: { question: string; answer_snippet: string }
  model_visible: {
    system_kind: 'answer' | 'coach'
    guidance_present: boolean
    guidance_preview: string
    history_turns: number
    history: HistoryLine[]
    memories: string[]
    context_previews: string[]
    sources: string[]
    tool_output_preview: string
    query: string
  }
  lab: LabSpec | null
  default_open: boolean
}

export interface LabStatus {
  lab: LabSpec
  checks: Record<string, boolean>
}
