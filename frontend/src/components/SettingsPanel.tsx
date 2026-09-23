import { useEffect, useState } from 'react'
import { deleteMcp, listMcp, saveMcp, setMcpEnabled } from '../api/client'
import type { McpList, McpServer, McpTransport } from '../api/types'

const TRANSPORTS: { value: McpTransport; label: string }[] = [
  { value: 'stdio', label: '本地命令 (stdio)' },
  { value: 'http', label: 'HTTP（streamable）' },
  { value: 'sse', label: 'SSE' },
]

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
  const [name, setName] = useState('')
  const [transport, setTransport] = useState<McpTransport>('stdio')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [url, setUrl] = useState('')

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

  async function handleAdd() {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('请填写名称')
      return
    }
    if (transport === 'stdio' && !command.trim()) {
      setError('stdio 需要填写命令')
      return
    }
    if (transport !== 'stdio' && !url.trim()) {
      setError('请填写 URL')
      return
    }
    setBusy(true)
    setError('')
    try {
      const next = await saveMcp({
        name: trimmed,
        enabled: true,
        transport,
        command: transport === 'stdio' ? command.trim() : '',
        args: transport === 'stdio' ? args.split(/\s+/).filter(Boolean) : [],
        url: transport === 'stdio' ? '' : url.trim(),
      })
      await apply(next)
      setName('')
      setCommand('')
      setArgs('')
      setUrl('')
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

        <div className="panel-label">MCP</div>
        <p className="settings-note">
          本地命令走 stdio；远程填 URL，选 streamable HTTP 或
          SSE。保存后下一轮对话即可调用。停用的服务不会注册工具。和内置工具重名时会加上服务名前缀。
        </p>

        {data?.config_error ? <p className="error-line">{data.config_error}</p> : null}
        {error ? <p className="error-line">{error}</p> : null}

        <div className="mcp-list">
          {!data ? <p className="quiet">加载中…</p> : null}
          {data && !servers.length ? (
            <p className="quiet">
              还没有 MCP 服务。在下面填写名称，以及本地命令或 URL，添加后下一轮对话就能用它的工具。
            </p>
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

        <form
          className="mcp-form"
          onSubmit={(event) => {
            event.preventDefault()
            void handleAdd()
          }}
        >
          <label>
            名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="notes"
              autoComplete="off"
            />
          </label>
          <label>
            传输
            <select
              value={transport}
              onChange={(event) => setTransport(event.target.value as McpTransport)}
            >
              {TRANSPORTS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {transport === 'stdio' ? (
            <>
              <label>
                命令
                <input
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  placeholder="uv"
                  autoComplete="off"
                />
              </label>
              <label>
                参数
                <input
                  value={args}
                  onChange={(event) => setArgs(event.target.value)}
                  placeholder="run python servers/notes_mcp.py"
                  autoComplete="off"
                />
              </label>
            </>
          ) : (
            <label>
              URL
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="http://127.0.0.1:8000/mcp"
                autoComplete="off"
              />
            </label>
          )}
          <button type="submit" className="primary" disabled={busy}>
            添加
          </button>
        </form>
      </div>
    </div>
  )
}

function endpoint(server: McpServer): string {
  if (server.transport === 'stdio') {
    const tail = server.args.length ? ` ${server.args.join(' ')}` : ''
    return `stdio · ${server.command}${tail}`
  }
  const label = server.transport === 'sse' ? 'SSE' : 'HTTP'
  return `${label} · ${server.url}`
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
