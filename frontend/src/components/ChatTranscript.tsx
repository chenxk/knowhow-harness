import { useEffect, useRef, useState } from 'react'
import { postScore } from '../api/client'
import type { TranscriptMessage, TurnDissection } from '../api/types'
import { ACTION_LABEL } from '../lib/format'
import { CopyButton } from './CopyButton'
import { DissectionDrawer } from './DissectionDrawer'
import { Markdown } from './Markdown'

const SAMPLE_LEARN = '教我长期记忆怎么工作'

export function ChatTranscript({
  messages,
  tracing,
  labRefreshKey,
  onFeedback,
  onError,
  onSample,
}: {
  messages: TranscriptMessage[]
  tracing: boolean
  labRefreshKey: string
  onFeedback: (id: string, value: number) => void
  onError: (message: string) => void
  onSample?: (text: string) => void
}) {
  if (!messages.length) {
    return (
      <div className="transcript empty-state">
        <p className="empty-lead">从这里开始</p>
        <p className="empty-sub">
          会话保存在本机。日常聊天照常；想学 Agent 工程可点下方样例。
        </p>
        {onSample ? (
          <button
            type="button"
            className="sample-chip"
            onClick={() => onSample(SAMPLE_LEARN)}
          >
            {SAMPLE_LEARN}
          </button>
        ) : null}
      </div>
    )
  }

  return (
    <div className="transcript">
      {messages.map((message, index) =>
        message.role === 'user' ? (
          <article key={message.id} className="turn user">
            <div className="turn-head">
              <div className="who">你</div>
            </div>
            <div className="bubble plain">{message.content}</div>
            {message.content.trim() ? (
              <div className="turn-foot turn-foot-end">
                <CopyButton text={message.content} />
              </div>
            ) : null}
          </article>
        ) : (
          <AssistantTurn
            key={message.id}
            message={message}
            question={previousQuestion(messages, index)}
            tracing={tracing}
            labRefreshKey={labRefreshKey}
            onFeedback={onFeedback}
            onError={onError}
          />
        ),
      )}
    </div>
  )
}

function AssistantTurn({
  message,
  question,
  tracing,
  labRefreshKey,
  onFeedback,
  onError,
}: {
  message: TranscriptMessage
  question: string
  tracing: boolean
  labRefreshKey: string
  onFeedback: (id: string, value: number) => void
  onError: (message: string) => void
}) {
  const action = message.action ? ACTION_LABEL[message.action] ?? message.action : ''
  const bits = [
    action,
    message.tool_name ? `tool ${message.tool_name}` : '',
    ...(message.sources ?? []).map((source) => source),
  ].filter(Boolean)

  async function score(value: number) {
    if (!message.trace_id || message.feedback === value) return
    try {
      await postScore(
        message.trace_id,
        value,
        value ? 'thumbs up' : 'thumbs down',
      )
      onFeedback(message.id, value)
    } catch (err) {
      onError(err instanceof Error ? err.message : '反馈写入失败')
    }
  }

  // Prefer answer text; include thinking when present so copy matches what's shown.
  const copyText = message.content.trim()
    ? message.thinking?.trim()
      ? `${message.thinking.trim()}\n\n${message.content}`
      : message.content
    : message.thinking?.trim() || ''

  return (
    <article className="turn assistant">
      <div className="turn-head">
        <div className="who">Knowhow</div>
      </div>
      <div className="bubble">
        {bits.length > 0 && (
          <div className={`stamp action-${message.action ?? 'answer'}`}>
            {bits.join(' · ')}
            {message.pending ? ' · …' : ''}
          </div>
        )}
        {message.thinking ? (
          <ThinkingBlock
            text={message.thinking}
            streaming={Boolean(message.pending && !message.content)}
          />
        ) : null}
        <div className="body">
          {message.content ? (
            <Markdown source={message.content} />
          ) : message.pending && !message.thinking ? (
            <span className="thinking">思考中</span>
          ) : null}
        </div>
      </div>
      {(copyText || (tracing && message.trace_id && !message.pending)) && (
        <div className="turn-foot turn-foot-start">
          {copyText ? <CopyButton text={copyText} /> : null}
          {tracing && message.trace_id && !message.pending && (
            <div className="feedback">
              <button
                type="button"
                className={message.feedback === 1 ? 'picked' : ''}
                onClick={() => score(1)}
                disabled={message.feedback !== undefined}
              >
                有用
              </button>
              <button
                type="button"
                className={message.feedback === 0 ? 'picked' : ''}
                onClick={() => score(0)}
                disabled={message.feedback !== undefined}
              >
                没用
              </button>
              {message.feedback !== undefined && <span className="hint">已记录</span>}
            </div>
          )}
        </div>
      )}
      {!message.pending ? (
        <DissectionDrawer
          dissection={message.dissection ?? fallbackDissection(message, question)}
          refreshKey={labRefreshKey}
        />
      ) : null}
    </article>
  )
}

function previousQuestion(messages: TranscriptMessage[], index: number): string {
  for (let i = index - 1; i >= 0; i -= 1) {
    const item = messages[i]
    if (item?.role === 'user') return item.content
  }
  return ''
}

function fallbackDissection(message: TranscriptMessage, question: string): TurnDissection {
  const action = message.action ?? 'answer'
  const snippet = message.content.trim().slice(0, 400)
  return {
    route: {
      action,
      tool_name: message.tool_name ?? '',
      sources: message.sources ?? [],
      query: '',
    },
    why: { reason: 'unknown', detail: '原因未记录' },
    injected: { history_turns: 0, memories: [], guidance_present: false },
    tool_output_summary: '',
    trace_id: message.trace_id ?? null,
    tracing: false,
    langfuse_hint: null,
    user_visible: { question, answer_snippet: snippet },
    model_visible: {
      system_kind: 'answer',
      guidance_present: false,
      guidance_preview: '',
      history_turns: 0,
      history: [],
      memories: [],
      context_previews: [],
      sources: message.sources ?? [],
      tool_output_preview: '',
      query: '',
    },
    lab: null,
    default_open: false,
  }
}

function ThinkingBlock({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(streaming)
  const wasStreaming = useRef(streaming)

  useEffect(() => {
    if (streaming) {
      setOpen(true)
    } else if (wasStreaming.current && !streaming) {
      setOpen(false)
    }
    wasStreaming.current = streaming
  }, [streaming])

  return (
    <details
      className={`think-block${streaming ? ' streaming' : ''}`}
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
    >
      <summary>思考{streaming ? '中…' : ''}</summary>
      <pre className="think-body">{text}</pre>
    </details>
  )
}
