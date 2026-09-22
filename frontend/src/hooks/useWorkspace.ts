import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createSession,
  deleteSession,
  getSession,
  listSessions,
  renameSession,
  streamChat,
} from '../api/client'
import type { SessionSummary, TranscriptMessage } from '../api/types'
import { uid } from '../lib/format'

export function useWorkspace() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId

  const refreshSessions = useCallback(async () => {
    const rows = await listSessions()
    setSessions(rows)
    return rows
  }, [])

  const selectSession = useCallback(async (id: string) => {
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

  const newSession = useCallback(async () => {
    const session = await createSession()
    const rows = await refreshSessions()
    setSessions(rows)
    await selectSession(session.id)
  }, [refreshSessions, selectSession])

  const rename = useCallback(
    async (id: string, title: string) => {
      await renameSession(id, title)
      await refreshSessions()
      if (id === sessionIdRef.current) {
        // title lives in sidebar list; transcript stays
      }
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

  const booted = useRef(false)

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    let cancelled = false
    ;(async () => {
      try {
        const rows = await refreshSessions()
        if (cancelled) return
        if (!rows.length) {
          const session = await createSession()
          if (cancelled) return
          await refreshSessions()
          await selectSession(session.id)
          return
        }
        await selectSession(rows[0].id)
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
