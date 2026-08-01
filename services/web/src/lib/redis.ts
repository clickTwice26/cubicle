import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useActiveCluster } from './cluster'

const ROOT = '/api/services/redis/db'

export type RedisType = 'string' | 'hash' | 'list' | 'set' | 'zset' | 'stream'

export interface KeyRef {
  key: string
  type: RedisType
  /** Seconds until it expires; -1 when it never does. */
  ttl: number
  /** Elements for a collection, characters for a string. */
  length: number | null
  size_bytes: number | null
}

export interface KeyPage {
  cursor: number
  /** Where the next SCAN continues, or null when the keyspace is exhausted. */
  next_cursor: number | null
  match: string
  type: RedisType | null
  total: number
  keys: KeyRef[]
}

export interface Entry {
  /** Hash field, list index, zset member or stream id. Null for a set member. */
  field: string | null
  value: string | Record<string, string> | null
  score?: number
}

export interface KeyValue {
  key: string
  type: RedisType
  ttl: number
  cursor: number
  next_cursor: number | null
  editable: boolean
  total: number
  truncated: boolean
  value: string | null
  entries: Entry[]
}

export interface RedisOverview {
  keys: number
  used_memory: number
  max_memory: number
  eviction: string
  server: string
  clients: number
  uptime_seconds: number
  hit_rate: number | null
  expires: number
  evicted: number
}

export interface CommandResult {
  command: string
  kind: 'value' | 'list'
  value: unknown
  truncated: boolean
  duration_ms: number
}

export interface ScanArgs {
  cursor: number
  match?: string
  type?: RedisType | null
  limit: number
}

const keys = {
  overview: ['redis', 'overview'] as const,
  scan: (a: ScanArgs) => ['redis', 'scan', a] as const,
  value: (key: string, cursor: number, limit: number) =>
    ['redis', 'value', key, cursor, limit] as const,
}

export function useRedisOverview() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.overview, scope],
    queryFn: () => api.get<RedisOverview>(`${ROOT}/overview`),
  })
}

export function useRedisKeys(args: ScanArgs) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.scan(args), scope],
    queryFn: () => {
      const params = new URLSearchParams({
        cursor: String(args.cursor),
        limit: String(args.limit),
      })
      if (args.match) params.set('match', args.match)
      if (args.type) params.set('type', args.type)
      return api.get<KeyPage>(`${ROOT}/keys?${params}`)
    },
    placeholderData: (previous) => previous,
  })
}

export function useRedisValue(key: string | null, cursor = 0, limit = 50) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.value(key ?? '', cursor, limit), scope],
    enabled: Boolean(key),
    queryFn: () => {
      const params = new URLSearchParams({
        key: key!,
        cursor: String(cursor),
        limit: String(limit),
      })
      return api.get<KeyValue>(`${ROOT}/value?${params}`)
    },
    placeholderData: (previous) => previous,
  })
}

/** Any write invalidates the browser — the key list and the open value both. */
function useWriter<T, V>(fn: (vars: V) => Promise<T>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['redis'] }),
  })
}

export const useWriteRedisKey = () =>
  useWriter<
    { key: string; type: RedisType },
    {
      key: string
      value: string
      field?: string | null
      score?: number | null
      ttl?: number
      /** Only used when the key does not exist yet. */
      type?: RedisType
    }
  >((vars) => api.post(`${ROOT}/value`, vars))

export const useSetRedisTtl = () =>
  useWriter<{ key: string; ttl: number }, { key: string; ttl: number }>((vars) =>
    api.post(`${ROOT}/ttl`, vars),
  )

export const useDeleteRedisEntry = () =>
  useWriter<{ deleted: number }, { key: string; field: string }>((vars) =>
    api.post(`${ROOT}/entries/delete`, vars),
  )

export const useDeleteRedisKey = () =>
  useWriter<{ deleted: number }, { key: string }>((vars) =>
    api.post(`${ROOT}/keys/delete`, vars),
  )

export function useRunRedisCommand() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (command: string) => api.post<CommandResult>(`${ROOT}/command`, { command }),
    // A command box can write as easily as it can read, so anything it runs
    // invalidates what the browser is showing.
    onSuccess: () => void client.invalidateQueries({ queryKey: ['redis'] }),
  })
}

/** `-1` means no expiry; anything else is a countdown worth spelling out. */
export function formatTtl(ttl: number): string {
  if (ttl < 0) return 'no expiry'
  if (ttl < 60) return `${ttl}s`
  if (ttl < 3600) return `${Math.floor(ttl / 60)}m ${ttl % 60}s`
  if (ttl < 86400) return `${Math.floor(ttl / 3600)}h ${Math.floor((ttl % 3600) / 60)}m`
  return `${Math.floor(ttl / 86400)}d ${Math.floor((ttl % 86400) / 3600)}h`
}
