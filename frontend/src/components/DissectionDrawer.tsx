import { useRef, useState, type ReactNode } from 'react'
import type { TurnDissection } from '../api/types'
import { ACTION_LABEL } from '../lib/format'
import { CopyButton } from './CopyButton'
import { LabPanel } from './LabPanel'

export function DissectionDrawer({
  dissection,
  refreshKey,
}: {
  dissection: TurnDissection
  refreshKey: string
}) {
  const [tab, setTab] = useState<'route' | 'contrast'>('route')
  const seeded = useRef(false)
  const route = dissection.route
  const action = ACTION_LABEL[route.action] ?? route.action
  const debug = JSON.stringify(dissection, null, 2)

  function bindDetails(node: HTMLDetailsElement | null) {
    if (!node || seeded.current) return
    seeded.current = true
    if (dissection.default_open) node.open = true
  }

  return (
    <details className="dissection" ref={bindDetails}>
      <summary>本轮如何决策</summary>
      <div className="dissection-body">
        <div className="dissection-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'route'}
            className={tab === 'route' ? 'on' : ''}
            onClick={() => setTab('route')}
          >
            决策
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'contrast'}
            className={tab === 'contrast' ? 'on' : ''}
            onClick={() => setTab('contrast')}
          >
            可见对照
          </button>
          <CopyButton text={debug} label="复制调试 JSON" />
        </div>

        {tab === 'route' ? (
          <div className="dissection-pane">
            <Field label="路由">
              {action}
              {route.tool_name ? ` · ${route.tool_name}` : ''}
              {route.sources.length ? ` · ${route.sources.join(', ')}` : ''}
            </Field>
            {route.query ? <Field label="query">{route.query}</Field> : null}
            <Field label="原因">{dissection.why.detail}</Field>
            <Field label="注入">
              历史 {dissection.injected.history_turns} 轮
              {' · '}
              记忆 {dissection.injected.memories.length} 条
              {' · '}
              skill guidance {dissection.injected.guidance_present ? '有' : '无'}
            </Field>
            {dissection.injected.memories.length > 0 ? (
              <ul className="dissection-list">
                {dissection.injected.memories.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
            {dissection.tool_output_summary ? (
              <Field label="工具输出">{dissection.tool_output_summary}</Field>
            ) : null}
            <Field label="trace">
              {dissection.trace_id ? dissection.trace_id : '无'}
              {dissection.langfuse_hint ? (
                <>
                  {' · '}
                  <a href={dissection.langfuse_hint} target="_blank" rel="noreferrer">
                    在 Langfuse 打开
                  </a>
                </>
              ) : dissection.tracing && dissection.trace_id ? (
                ' · 需配置 LANGFUSE_PROJECT_ID'
              ) : dissection.tracing ? null : (
                ' · 未开启 tracing'
              )}
            </Field>
            {dissection.lab ? (
              <LabPanel lab={dissection.lab} refreshKey={refreshKey} />
            ) : null}
          </div>
        ) : (
          <div className="contrast">
            <section>
              <h3>用户看见</h3>
              <Field label="问题">{dissection.user_visible.question || '（空）'}</Field>
              <Field label="回答">
                {dissection.user_visible.answer_snippet || '（空）'}
              </Field>
            </section>
            <section>
              <h3>模型收到</h3>
              <Field label="system">
                {dissection.model_visible.system_kind === 'coach' ? '教练' : '日常回答'}
                {' · guidance '}
                {dissection.model_visible.guidance_present ? '有' : '无'}
              </Field>
              {dissection.model_visible.guidance_preview ? (
                <Field label="guidance">{dissection.model_visible.guidance_preview}</Field>
              ) : null}
              <Field label="历史">
                {dissection.model_visible.history_turns} 条
              </Field>
              {dissection.model_visible.history.length > 0 ? (
                <ul className="dissection-list">
                  {dissection.model_visible.history.map((line, index) => (
                    <li key={`${line.role}-${index}`}>
                      {line.role === 'user' ? '用户' : '助手'} · {line.chars} 字 · {line.preview}
                    </li>
                  ))}
                </ul>
              ) : null}
              <Field label="记忆">
                {dissection.model_visible.memories.length
                  ? dissection.model_visible.memories.join(' / ')
                  : '无'}
              </Field>
              {dissection.model_visible.context_previews.length > 0 ? (
                <Field label="检索片段">
                  {dissection.model_visible.context_previews.join('\n')}
                </Field>
              ) : null}
              {dissection.model_visible.tool_output_preview ? (
                <Field label="tool_output">
                  {dissection.model_visible.tool_output_preview}
                </Field>
              ) : null}
            </section>
          </div>
        )}
      </div>
    </details>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p className="dissection-field">
      <span>{label}</span>
      {children}
    </p>
  )
}
