export function formatBytes(bytes: number | undefined | null): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return index === 0 ? `${value} B` : `${value.toFixed(1)} ${units[index]}`
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value === 0) return '$0.00'
  if (Math.abs(value) < 0.01) return '<$0.01'
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`
  return formatDate(value)
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function newSessionId(): string {
  const bytes = new Uint8Array(6)
  crypto.getRandomValues(bytes)
  return `sess_${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

export const RUNTIME_LABEL: Record<string, string> = {
  python312: 'Python 3.12',
  python311: 'Python 3.11',
}

export const CTX_LABEL: Record<string, string> = {
  rw: 'read+write',
  r: 'read only',
  w: 'write only',
  none: 'no access',
}

export function statusTone(status: string): 'ok' | 'warn' | 'err' | 'idle' {
  if (status === 'active' || status === 'ready' || status === 'running') return 'ok'
  if (status === 'degraded' || status === 'draining' || status === 'building') return 'warn'
  if (status === 'failed' || status === 'down') return 'err'
  return 'idle'
}

export function levelColour(level: string): string {
  if (level === 'ERROR') return 'var(--err)'
  if (level === 'WARN') return 'var(--warn)'
  if (level === 'DEBUG') return 'var(--text-3)'
  return 'var(--info)'
}
