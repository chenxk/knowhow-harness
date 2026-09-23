import { useState } from 'react'
import type { MemoryItem, SessionSummary } from '../api/types'
import { formatWhen } from '../lib/format'

const SESSION_PREVIEW = 5

function visibleSessions(
  sessions: SessionSummary[],
  sessionId: string,
  showAll: boolean,
): SessionSummary[] {
  if (showAll || sessions.length <= SESSION_PREVIEW) return sessions
  const head = sessions.slice(0, SESSION_PREVIEW)
  if (head.some((session) => session.id === sessionId)) return head
  const current = sessions.find((session) => session.id === sessionId)
  return current ? [...head, current] : head
}

export function Sidebar({
  sessions,
  sessionId,
  memories,
  evalText,
  onNew,
  onSelect,
  onRename,
  onDelete,
  onDeleteMemory,
  onPromoteMemory,
  onEval,
  onOpenSettings,
}: {
  sessions: SessionSummary[]
  sessionId: string
  memories: MemoryItem[]
  evalText: string
  onNew: () => void
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onDeleteMemory: (id: string) => void
  onPromoteMemory: (id: string) => void
  onEval: () => void
  onOpenSettings: () => void
}) {
  const [showAllSessions, setShowAllSessions] = useState(false)
  const rows = visibleSessions(sessions, sessionId, showAllSessions)
  const hasMore = rows.length < sessions.length
  const active = memories.filter((item) => item.status === 'active')
  const pending = memories.filter((item) => item.status === 'pending')

  return (
    <aside className="sidebar">
      <div className="sidebar-scroll">
      <div className="sidebar-head">
        <button type="button" className="primary" onClick={onNew}>
          新对话
        </button>
        <button type="button" className="ghost" onClick={onEval}>
          评测
        </button>
      </div>

      <div className="panel-label">会话</div>
      <div className="session-list">
        {!sessions.length && <p className="quiet">还没有会话</p>}
        {rows.map((session) => (
          <div
            key={session.id}
            className={`session-row${session.id === sessionId ? ' active' : ''}`}
          >
            <button
              type="button"
              className="session-main"
              onClick={() => onSelect(session.id)}
            >
              <span className="session-title">{session.title || '新对话'}</span>
              <span className="session-when">{formatWhen(session.updated_at)}</span>
            </button>
            <div className="session-ops">
              <button
                type="button"
                className="ghost tiny"
                onClick={() => {
                  const next = window.prompt('会话标题', session.title)
                  if (next && next.trim()) onRename(session.id, next.trim())
                }}
              >
                改名
              </button>
              <button
                type="button"
                className="ghost tiny"
                onClick={() => {
                  if (window.confirm('删除这个会话？')) onDelete(session.id)
                }}
              >
                删除
              </button>
            </div>
          </div>
        ))}
        {hasMore ? (
          <button
            type="button"
            className="ghost session-more"
            onClick={() => setShowAllSessions(true)}
          >
            更多
          </button>
        ) : null}
      </div>

      <div className="panel-label">长期记忆</div>
      <div className="memory-list">
        {!memories.length && <p className="quiet">还没有记忆</p>}
        {active.map((memory) => (
          <MemoryRow
            key={memory.id}
            memory={memory}
            onDelete={onDeleteMemory}
          />
        ))}
        {pending.length > 0 && (
          <>
            <div className="panel-label subtle">待确认</div>
            {pending.map((memory) => (
              <MemoryRow
                key={memory.id}
                memory={memory}
                onDelete={onDeleteMemory}
                onPromote={onPromoteMemory}
              />
            ))}
          </>
        )}
      </div>

      {evalText ? <pre className="eval-box">{evalText}</pre> : null}
      </div>
      <div className="sidebar-foot">
        <button type="button" className="ghost settings-entry" onClick={onOpenSettings}>
          设置
        </button>
      </div>
    </aside>
  )
}

function MemoryRow({
  memory,
  onDelete,
  onPromote,
}: {
  memory: MemoryItem
  onDelete: (id: string) => void
  onPromote?: (id: string) => void
}) {
  const pending = memory.status === 'pending'
  return (
    <div className={`memory-row${pending ? ' pending' : ''}`}>
      <div>
        <div className="memory-text">{memory.content}</div>
        <div className="session-when">
          {pending ? '候选' : memory.category} · {formatWhen(memory.updated_at)}
        </div>
      </div>
      <div className="memory-ops">
        {onPromote ? (
          <button
            type="button"
            className="ghost tiny"
            onClick={() => onPromote(memory.id)}
          >
            确认记住
          </button>
        ) : null}
        <button
          type="button"
          className="ghost tiny"
          onClick={() => {
            if (window.confirm('删除这条记忆？')) onDelete(memory.id)
          }}
        >
          删除
        </button>
      </div>
    </div>
  )
}
