import { postScore } from '../api/client'
import type { TranscriptMessage } from '../api/types'
import { ACTION_LABEL } from '../lib/format'
import { Markdown } from './Markdown'

export function ChatTranscript({
  messages,
  tracing,
  onFeedback,
  onError,
}: {
  messages: TranscriptMessage[]
  tracing: boolean
  onFeedback: (id: string, value: number) => void
  onError: (message: string) => void
}) {
  if (!messages.length) {
    return (
      <div className="transcript empty-state">
        <p className="empty-lead">从这里开始</p>
        <p className="empty-sub">会话保存在本机。试试「如何重置密码」或「请记住：我喜欢绿茶」。</p>
      </div>
    )
  }

  return (
    <div className="transcript">
      {messages.map((message) =>
        message.role === 'user' ? (
          <article key={message.id} className="turn user">
            <div className="who">你</div>
            <div className="bubble plain">{message.content}</div>
          </article>
        ) : (
          <AssistantTurn
            key={message.id}
            message={message}
            tracing={tracing}
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
  tracing,
  onFeedback,
  onError,
}: {
  message: TranscriptMessage
  tracing: boolean
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

  return (
    <article className="turn assistant">
      <div className="who">Knowhow</div>
      <div className="bubble">
        {bits.length > 0 && (
          <div className={`stamp action-${message.action ?? 'answer'}`}>
            {bits.join(' · ')}
            {message.pending ? ' · …' : ''}
          </div>
        )}
        <div className="body">
          {message.content ? (
            <Markdown source={message.content} />
          ) : message.pending ? (
            <span className="thinking">思考中</span>
          ) : null}
        </div>
      </div>
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
    </article>
  )
}
