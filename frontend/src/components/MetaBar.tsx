import type { Meta } from '../api/types'

export function MetaBar({ meta }: { meta: Meta | null }) {
  if (!meta) return <div className="meta-bar muted">连接中…</div>
  const facts = [
    meta.mode,
    meta.chat_model,
    `${meta.corpus_chunks} chunks`,
    `${meta.memory_count} memories`,
    meta.tools.length ? `tools ${meta.tools.join(',')}` : 'no tools',
    meta.skills.length ? `skills ${meta.skills.join(',')}` : 'no skills',
    meta.tracing ? 'langfuse on' : 'langfuse off',
  ]
  return (
    <div className="meta-bar" aria-label="运行时状态">
      {facts.map((text) => (
        <span key={text} className="meta-chip">
          {text}
        </span>
      ))}
    </div>
  )
}
