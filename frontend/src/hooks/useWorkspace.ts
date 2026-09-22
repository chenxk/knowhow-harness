import { useCallback, useEffect, useRef, useState } from 'react'
import {
  consolidateMemories,
  createSession,
  deleteSession,
  getSession,
  listSessions,
  renameSession,
  streamChat,
} from '../api/client'
import type { SessionSummary, TranscriptMessage } from '../api/types'
import { uid } from '../lib/format'

/** Deduplicate StrictMode double-mount boot so we do not create two empty sessions. */
let bootOnce: Promise<string> | null = null

async function resolveInitialSessionId(): Promise<string> {
  if (!bootOnce) {
    bootOnce = (async () => {
      const rows = await listSessions()
      if (rows.length) return rows[0].id
      return (await createSession()).id
    })()
  }
  return bootOnce
}

export function useWorkspace(onMemoriesMaybeChanged?: () => void) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId
  const onMemoriesRef = useRef(onMemoriesMaybeChanged)
  onMemoriesRef.current = onMemoriesMaybeChanged

  const refreshSessions = useCallback(async () => {
    const rows = await listSessions()
    setSessions(rows)
    return rows
  }, [])

  const consolidateLeaving = useCallback(async (id: string) => {
    if (!id) return
    try {
      await consolidateMemories(id)
      onMemoriesRef.current?.()
    } catch {
      /* consolidate is best-effort on switch */
    }
  }, [])

  const loadSession = useCallback(async (id: string) => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
    setError('')
    const session = await getSession(id)
    setSessionId(session.id)
    setMessages(
      session.messages.map((item) => ({
        id: uid('hist'),
        role: item.role,
        content: item.content,
        action: item.action ?? undefined,
        sources: item.sources,
        tool_name: item.tool_name,
        trace_id: item.trace_id,
      })),
    )
  }, [])

  const selectSession = useCallback(
    async (id: string) => {
      const prev = sessionIdRef.current
      if (prev && prev !== id) {
        await consolidateLeaving(prev)
      }
      await loadSession(id)
    },
    [consolidateLeaving, loadSession],
  )

  const newSession = useCallback(async () => {
    const prev = sessionIdRef.current
    if (prev) await consolidateLeaving(prev)
    const session = await createSession()
    await refreshSessions()
    await loadSession(session.id)
  }, [consolidateLeaving, loadSession, refreshSessions])

  const rename = useCallback(
    async (id: string, title: string) => {
      await renameSession(id, title)
      await refreshSessions()
    },
    [refreshSessions],
  )

  const remove = useCallback(
    async (id: string) => {
      await deleteSession(id)
      const rows = await refreshSessions()
      if (id !== sessionIdRef.current) return
      if (rows.length) {
        await selectSession(rows[0].id)
      } else {
        await newSession()
      }
    },
    [newSession, refreshSessions, selectSession],
  )

  const send = useCallback(
    async (question: string) => {
      const text = question.trim()
      if (!text || !sessionIdRef.current || busy) return
      setError('')
      setBusy(true)
      const userId = uid('u')
      const assistantId = uid('a')
      setMessages((prev) => [
        ...prev,
        { id: userId, role: 'user', content: text },
        {
          id: assistantId,
          role: 'assistant',
          content: '',
          pending: true,
          action: 'answer',
          sources: [],
          tool_name: '',
        },
      ])

      const controller = new AbortController()
      abortRef.current = controller
      try {
        for await (const event of streamChat(sessionIdRef.current, text, controller.signal)) {
          if (event.type === 'error') {
            setError(event.text || '请求失败')
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId ? { ...item, pending: false } : item,
              ),
            )
            continue
          }
          if (event.type === 'session') {
            setSessions((prev) =>
              prev.map((row) =>
                row.id === event.id
                  ? { ...row, title: event.title, updated_at: event.updated_at }
                  : row,
              ),
            )
            continue
          }
          if (event.type === 'status' || event.type === 'done') {
            if (event.type === 'done') {
              // Answer is complete; keep the SSE open for session metadata
              // / memory extract without freezing the composer.
              setBusy(false)
            }
            setMessages((prev) =>
              prev.map((item) => {
                if (item.id !== assistantId) return item
                return {
                  ...item,
                  action: event.action ?? item.action,
                  sources: event.sources ?? item.sources,
                  tool_name: event.tool_name ?? item.tool_name,
                  pending: event.type !== 'done',
                  trace_id: event.type === 'done' ? event.trace_id : item.trace_id,
                  content:
                    event.type === 'done' && event.answer ? event.answer : item.content,
                }
              }),
            )
            continue
          }
          if (event.type === 'delta') {
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId
                  ? { ...item, content: item.content + (event.text ?? '') }
                  : item,
              ),
            )
            continue
          }
          if (event.type === 'thinking') {
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId
                  ? { ...item, thinking: (item.thinking ?? '') + (event.text ?? '') }
                  : item,
              ),
            )
          }
        }
        await refreshSessions()
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        setError(err instanceof Error ? err.message : '发送失败')
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId ? { ...item, pending: false } : item,
          ),
        )
      } finally {
        abortRef.current = null
        setBusy(false)
      }
    },
    [busy, refreshSessions],
  )

  const setFeedback = useCallback((id: string, value: number) => {
    setMessages((prev) =>
      prev.map((item) => (item.id === id ? { ...item, feedback: value } : item)),
    )
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const id = await resolveInitialSessionId()
        if (cancelled) return
        await refreshSessions()
        if (cancelled) return
        await selectSession(id)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '无法加载会话')
        }
      }
    })()
    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
  }, [refreshSessions, selectSession])

  return {
    sessions,
    sessionId,
    messages,
    busy,
    error,
    setError,
    selectSession,
    newSession,
    rename,
    remove,
    send,
    setFeedback,
  }
}
