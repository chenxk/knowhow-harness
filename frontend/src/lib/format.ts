export function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (sameDay) return time
  return (
    date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) + ' ' + time
  )
}

export function uid(prefix = 'm'): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

export const ACTION_LABEL: Record<string, string> = {
  retrieve: '检索',
  tool: '工具',
  answer: '直接回答',
}
