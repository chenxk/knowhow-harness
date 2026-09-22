import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

export function Composer({
  busy,
  onSend,
}: {
  busy: boolean
  onSend: (text: string) => void
}) {
  const [value, setValue] = useState('')

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const text = value.trim()
    if (!text || busy) return
    setValue('')
    onSend(text)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="写下问题。Enter 发送，Shift+Enter 换行"
        rows={2}
        disabled={busy}
        aria-label="消息输入"
      />
      <button type="submit" disabled={busy || !value.trim()}>
        {busy ? '…' : '发送'}
      </button>
    </form>
  )
}
