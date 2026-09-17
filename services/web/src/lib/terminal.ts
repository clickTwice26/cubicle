/**
 * A live shell on a node's host.
 *
 * The session list and the settings toggle are ordinary REST — React Query
 * owns them the same way every other page's data is owned. The shell itself
 * is not: a terminal is a raw byte stream in both directions, so it is one
 * WebSocket per open tab, wrapped in `TerminalSocket` rather than forced
 * through a request/response hook that has no shape for it.
 *
 * `TerminalSocket` reconnects on its own. The session it is attached to lives
 * in a tmux server on the node, not in this browser tab, so a dropped
 * connection — a laptop closing, a phone switching networks — is exactly the
 * situation tmux exists for: reconnecting resumes the same shell, scrollback
 * included, rather than losing it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { activeCluster, useActiveCluster } from './cluster'

const ROOT = '/api/terminal'

export interface TerminalSession {
  name: string
  created_at: string
  attached: boolean
  cols: number
  rows: number
  activity_at: string
}

export interface TerminalSessions {
  enabled: boolean
  node_id: string | null
  node_name: string | null
  sessions: TerminalSession[]
}

const nodeQuery = (nodeId?: string) => (nodeId ? `?node=${encodeURIComponent(nodeId)}` : '')

export function useTerminalStatus(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['terminal', 'status'],
    queryFn: () => api.get<{ enabled: boolean }>(`${ROOT}/status`),
    ...options,
  })
}

export function useSetTerminalEnabled() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<{ enabled: boolean }>(`${ROOT}/settings`, { enabled }),
    onSuccess: (data) => {
      client.setQueryData(['terminal', 'status'], data)
      client.invalidateQueries({ queryKey: ['terminal', 'sessions'] })
    },
  })
}

export function useTerminalSessions(
  nodeId: string | undefined,
  options: { enabled?: boolean } = {},
) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: ['terminal', 'sessions', nodeId ?? 'default', scope],
    queryFn: () => api.get<TerminalSessions>(`${ROOT}/sessions${nodeQuery(nodeId)}`),
    // Fast enough that a session opened from another tab shows up here
    // without a manual refresh, slow enough not to matter while idle.
    refetchInterval: 10_000,
    ...options,
  })
}

export function useCreateTerminalSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name?: string; node_id?: string }) =>
      api.post<{ name: string; node_id: string; node_name: string }>(`${ROOT}/sessions`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['terminal', 'sessions'] }),
  })
}

export function useEndTerminalSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ name, nodeId }: { name: string; nodeId?: string }) =>
      api.delete<void>(`${ROOT}/sessions/${encodeURIComponent(name)}${nodeQuery(nodeId)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['terminal', 'sessions'] }),
  })
}

export function useRenameTerminalSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      newName,
      nodeId,
    }: {
      name: string
      newName: string
      nodeId?: string
    }) =>
      api.patch<{ name: string }>(
        `${ROOT}/sessions/${encodeURIComponent(name)}${nodeQuery(nodeId)}`,
        {
          name: newName,
        },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['terminal', 'sessions'] }),
  })
}

// ── the live attach ──────────────────────────────────────────────────────────

export type ShellStatus = 'connecting' | 'open' | 'closed'

function socketUrl(
  name: string,
  nodeId: string | undefined,
  cols: number,
  rows: number,
): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const params = new URLSearchParams({ cols: String(cols), rows: String(rows) })
  const cluster = activeCluster()
  if (cluster) params.set('cluster', cluster)
  if (nodeId) params.set('node', nodeId)
  const path = `${ROOT}/sessions/${encodeURIComponent(name)}/ws`
  return `${scheme}://${window.location.host}${path}?${params.toString()}`
}

/**
 * One shell, attached over one reconnecting WebSocket.
 *
 * Binary frames are raw terminal bytes both ways — handed to `onData`
 * exactly as received, and sent exactly as xterm.js hands them over, so
 * neither side has to reason about where a UTF-8 character was split across
 * two chunks. A resize is the one thing sent as JSON text instead, since it
 * is a control message rather than a byte the shell should see.
 */
export class TerminalSocket {
  onData: (chunk: Uint8Array) => void = () => {}
  onStatus: (status: ShellStatus, detail?: string) => void = () => {}

  private ws: WebSocket | null = null
  private closedByUser = false
  private retryMs = 500
  private retryTimer: number | undefined
  private cols: number
  private rows: number

  constructor(
    private readonly name: string,
    private readonly nodeId: string | undefined,
    cols: number,
    rows: number,
  ) {
    this.cols = cols
    this.rows = rows
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    this.onStatus('connecting')
    let ws: WebSocket
    try {
      ws = new WebSocket(socketUrl(this.name, this.nodeId, this.cols, this.rows))
    } catch {
      this.scheduleRetry()
      return
    }
    ws.binaryType = 'arraybuffer'
    this.ws = ws

    ws.onopen = () => {
      this.retryMs = 500
      this.onStatus('open')
    }
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) this.onData(new Uint8Array(event.data))
    }
    ws.onclose = (event) => {
      this.ws = null
      if (this.closedByUser) {
        this.onStatus('closed')
        return
      }
      this.onStatus('closed', event.reason || undefined)
      // 1008 is the server refusing the connection outright (off, no access,
      // no such node) — reconnecting would only refuse again.
      if (event.code === 1008) return
      this.scheduleRetry()
    }
  }

  private scheduleRetry(): void {
    window.clearTimeout(this.retryTimer)
    this.retryTimer = window.setTimeout(() => this.open(), this.retryMs)
    this.retryMs = Math.min(this.retryMs * 2, 8000)
  }

  write(data: Uint8Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(data)
  }

  resize(cols: number, rows: number): void {
    this.cols = cols
    this.rows = rows
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    }
  }

  close(): void {
    this.closedByUser = true
    window.clearTimeout(this.retryTimer)
    this.ws?.close()
  }
}
