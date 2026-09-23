import { useEffect, useState } from 'react'
import { deleteMcp, importMcp, listMcp, setMcpEnabled } from '../api/client'
import type { McpList, McpServer } from '../api/types'

const PLACEHOLDER = `{
  "mcpServers": {
    "demo": {
      "url": "https://example.invalid/mcp",
      "headers": { "Authorization": "Bearer mo_example" }
    }
  }
}`

export function SettingsPanel({
  onClose,
  onChanged,
}: {
  onClose: () => void
  onChanged: () => void
}) {
  const [data, setData] = useState<McpList | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [documentText, setDocumentText] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const next = await listMcp()
        if (!cancelled) setData(next)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '无法加载 MCP')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  async function apply(next: McpList) {
    setData(next)
    setError('')
    onChanged()
  }

  function cancelAdd() {
    setAdding(false)
    setError('')
  }

  async function handleSave() {
    if (!documentText.trim()) {
      setError('请贴入 mcpServers JSON')
      return
    }
    setBusy(true)
    setError('')
    try {
      const next = await importMcp(documentText)
      await apply(next)
      setAdding(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleToggle(server: McpServer) {
    setBusy(true)
    setError('')
    try {
      await apply(await setMcpEnabled(server.name, !server.enabled))
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(server: McpServer) {
    if (!window.confirm(`删除 MCP 服务 ${server.name}？`)) return
    setBusy(true)
    setError('')
    try {
      await apply(await deleteMcp(server.name))
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  const servers = data?.servers ?? []

  return (
    <div className="settings-backdrop" onClick={onClose}>
      <div
        className="settings-panel"
        role="dialog"
        aria-label="设置"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-head">
          <h2>设置</h2>
          <button type="button" className="ghost tiny" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="mcp-toolbar">
          <div className="panel-label">MCP</div>
          {adding ? (
            <button type="button" className="ghost tiny" disabled={busy} onClick={cancelAdd}>
              取消
            </button>
          ) : (
            <button type="button" className="ghost tiny" onClick={() => setAdding(true)}>
              添加 MCP
            </button>
          )}
        </div>
        <p className="settings-note">
          {adding
            ? '贴入 mcpServers JSON。同名服务会覆盖。disabled 为 true 表示停用。保存后下一轮对话即可调用。'
            : '保存后下一轮对话即可调用。停用的服务不会注册工具。和内置工具重名时会加上服务名前缀。'}
        </p>

        {data?.config_error ? <p className="error-line">{data.config_error}</p> : null}
        {error ? <p className="error-line">{error}</p> : null}

        {adding ? (
          <form
            className="mcp-form"
            onSubmit={(event) => {
              event.preventDefault()
              void handleSave()
            }}
          >
            <p className="mcp-path">配置文件：{data?.config_path || '…'}</p>
            <textarea
              value={documentText}
              onChange={(event) => setDocumentText(event.target.value)}
              placeholder={PLACEHOLDER}
              spellCheck={false}
              aria-label="mcpServers JSON"
            />
            <div className="mcp-actions">
              <button type="button" className="ghost" disabled={busy} onClick={cancelAdd}>
                取消
              </button>
              <button type="submit" className="primary" disabled={busy}>
                保存
              </button>
            </div>
          </form>
        ) : (
          <div className="mcp-list">
            {!data ? <p className="quiet">加载中…</p> : null}
            {data && !servers.length ? (
              <p className="quiet">还没有 MCP。点「添加 MCP」，贴入 mcpServers JSON 后保存。</p>
            ) : null}
            {servers.map((server) => (
              <div key={server.name} className="mcp-row">
                <div className="mcp-main">
                  <div className="session-title">{server.name}</div>
                  <div className="session-when">{endpoint(server)}</div>
                  <div className={`mcp-status${server.error ? ' bad' : ''}`}>{statusText(server)}</div>
                </div>
                <div className="session-ops">
                  <button
                    type="button"
                    className="ghost tiny"
                    disabled={busy}
                    aria-pressed={server.enabled}
                    onClick={() => void handleToggle(server)}
                  >
                    {server.enabled ? '已启用' : '已停用'}
                  </button>
                  <button
                    type="button"
                    className="ghost tiny"
                    disabled={busy}
                    onClick={() => void handleDelete(server)}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function endpoint(server: McpServer): string {
  const headerNote = server.has_headers ? ' · 已配置请求头' : ''
  if (server.transport === 'stdio') {
    const tail = server.args.length ? ` ${server.args.join(' ')}` : ''
    return `stdio · ${server.command}${tail}`
  }
  const label = server.transport === 'sse' ? 'SSE' : 'HTTP'
  return `${label} · ${server.url}${headerNote}`
}

function statusText(server: McpServer): string {
  if (!server.enabled) return '已停用'
  if (server.error) return `连接失败：${server.error}`
  if (server.connected) {
    const tools = server.tools.length ? `：${server.tools.join('、')}` : ''
    return `已连接 · ${server.tool_count} 个工具${tools}`
  }
  return '尚未连接'
}
