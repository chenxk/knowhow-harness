import { useEffect, useRef, useState } from 'react'

/** Copies `text` via the Clipboard API and briefly shows 「已复制」. */
export function CopyButton({
  text,
  className = '',
  label = '复制',
}: {
  text: string
  className?: string
  label?: string
}) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  async function copy() {
    const payload = text.trimEnd()
    if (!payload) return
    try {
      await navigator.clipboard.writeText(payload)
      setCopied(true)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <button
      type="button"
      className={`copy-btn ${copied ? 'copied' : ''} ${className}`.trim()}
      onClick={copy}
      disabled={!text.trim()}
      aria-label={copied ? '已复制' : label}
      title={copied ? '已复制' : label}
    >
      {copied ? '已复制' : label}
    </button>
  )
}
