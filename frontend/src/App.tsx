import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteMemory, fetchMeta, listMemories, runEval } from './api/client'
import type { MemoryItem, Meta } from './api/types'
import { ChatTranscript } from './components/ChatTranscript'
import { Composer } from './components/Composer'
import { MetaBar } from './components/MetaBar'
import { Sidebar } from './components/Sidebar'
import { useWorkspace } from './hooks/useWorkspace'

export default function App() {
  const workspace = useWorkspace()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [memories, setMemories] = useState<MemoryItem[]>([])
  const [evalText, setEvalText] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const refreshMemories = useCallback(async () => {
    setMemories(await listMemories())
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        setMeta(await fetchMeta())
        await refreshMemories()
      } catch (err) {
        workspace.setError(err instanceof Error ? err.message : '无法加载元信息')
      }
    })()
  }, [refreshMemories, workspace.setError])

  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [workspace.messages])

  async function handleEval() {
    workspace.setError('')
    setEvalText('评测进行中…')
    try {
      const data = await runEval()
      const lines = [
        `${data.passed} 通过，${data.failed} 失败${data.scored ? ' · 已写 Langfuse score' : ''}`,
        ...data.rows.map((row) => {
          const note = row.failures.length ? ` ${row.failures.join(', ')}` : ''
          return `${row.passed ? 'pass' : 'fail'} ${row.case_id} ${row.action}${note}`
        }),
      ]
      setEvalText(lines.join('\n'))
    } catch (err) {
      setEvalText('')
      workspace.setError(err instanceof Error ? err.message : '评测失败')
    }
  }

  async function handleDeleteMemory(id: string) {
    try {
      await deleteMemory(id)
      await refreshMemories()
      if (meta) setMeta({ ...meta, memory_count: Math.max(0, meta.memory_count - 1) })
    } catch (err) {
      workspace.setError(err instanceof Error ? err.message : '删除记忆失败')
    }
  }

  async function handleSend(text: string) {
    await workspace.send(text)
    await refreshMemories()
    try {
      setMeta(await fetchMeta())
    } catch {
      /* meta refresh is best-effort */
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden>
            K
          </span>
          <div>
            <h1>Knowhow</h1>
            <p className="tagline">本机个人助手</p>
          </div>
        </div>
        <MetaBar meta={meta} />
      </header>

      <div className="workspace">
        <Sidebar
          sessions={workspace.sessions}
          sessionId={workspace.sessionId}
          memories={memories}
          evalText={evalText}
          onNew={() => void workspace.newSession()}
          onSelect={(id) => void workspace.selectSession(id)}
          onRename={(id, title) => void workspace.rename(id, title)}
          onDelete={(id) => void workspace.remove(id)}
          onDeleteMemory={(id) => void handleDeleteMemory(id)}
          onEval={() => void handleEval()}
        />

        <section className="desk">
          <div className="transcript-scroll" ref={scrollRef}>
            <ChatTranscript
              messages={workspace.messages}
              tracing={Boolean(meta?.tracing)}
              onFeedback={workspace.setFeedback}
              onError={workspace.setError}
            />
          </div>
          {workspace.error ? <p className="error-line">{workspace.error}</p> : null}
          <Composer busy={workspace.busy} onSend={(text) => void handleSend(text)} />
        </section>
      </div>
    </div>
  )
}
