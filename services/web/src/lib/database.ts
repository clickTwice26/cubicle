import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useActiveCluster } from './cluster'

const ROOT = '/api/services/postgres/db'

export interface TableRef {
  schema: string
  name: string
  kind: 'table' | 'view'
  estimated_rows: number
  size_bytes: number
  editable: boolean
}

export interface ColumnRef {
  name: string
  data_type: string
  nullable: boolean
  is_primary_key: boolean
  default?: string | null
}

export type Cell = string | number | boolean | null
export type Row = Record<string, Cell>

export interface Page {
  schema: string
  table: string
  columns: ColumnRef[]
  primary_key: string[]
  editable: boolean
  rows: Row[]
  total: number
  limit: number
  offset: number
  order_by: string
  descending: boolean
}

export interface Structure {
  schema: string
  table: string
  columns: ColumnRef[]
  primary_key: string[]
  indexes: { name: string; definition: string; primary: boolean; unique: boolean }[]
}

export interface QueryResult {
  kind: 'rows' | 'command'
  command?: string
  columns: string[]
  rows: Row[]
  row_count: number
  truncated: boolean
  duration_ms: number
}

export interface DbOverview {
  size_bytes: number
  tables: number
  connections: number
  server: string
  database: string
}

export interface BrowseArgs {
  schema: string
  table: string
  limit: number
  offset: number
  orderBy?: string
  descending?: boolean
  search?: string
}

const keys = {
  overview: ['db', 'overview'] as const,
  tables: ['db', 'tables'] as const,
  page: (a: BrowseArgs) => ['db', 'page', a] as const,
  structure: (s: string, t: string) => ['db', 'structure', s, t] as const,
}

export function useDbOverview() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.overview, scope],
    queryFn: () => api.get<DbOverview>(`${ROOT}/overview`),
  })
}

export function useDbTables() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.tables, scope],
    queryFn: () => api.get<TableRef[]>(`${ROOT}/tables`),
  })
}

export function useDbPage(args: BrowseArgs | null) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.page(args ?? ({} as BrowseArgs)), scope],
    enabled: Boolean(args),
    queryFn: () => {
      const a = args!
      const params = new URLSearchParams({
        limit: String(a.limit),
        offset: String(a.offset),
        descending: String(Boolean(a.descending)),
      })
      if (a.orderBy) params.set('order_by', a.orderBy)
      if (a.search) params.set('search', a.search)
      return api.get<Page>(
        `${ROOT}/tables/${encodeURIComponent(a.schema)}/${encodeURIComponent(a.table)}?${params}`,
      )
    },
    placeholderData: (previous) => previous,
  })
}

export function useDbStructure(schema?: string, table?: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.structure(schema ?? '', table ?? ''), scope],
    enabled: Boolean(schema && table),
    queryFn: () =>
      api.get<Structure>(
        `${ROOT}/tables/${encodeURIComponent(schema!)}/${encodeURIComponent(table!)}/structure`,
      ),
  })
}

/** Any write invalidates the browse cache — the grid must not show stale rows. */
function useWriter<T, V>(fn: (vars: V) => Promise<T>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['db', 'page'] })
      void client.invalidateQueries({ queryKey: keys.tables })
      void client.invalidateQueries({ queryKey: keys.overview })
    },
  })
}

export const useInsertRow = (schema: string, table: string) =>
  useWriter<Row, { values: Row }>((vars) =>
    api.post(
      `${ROOT}/tables/${encodeURIComponent(schema)}/${encodeURIComponent(table)}/rows`,
      vars,
    ),
  )

export const useUpdateRow = (schema: string, table: string) =>
  useWriter<Row, { key: Row; values: Row }>((vars) =>
    api.patch(
      `${ROOT}/tables/${encodeURIComponent(schema)}/${encodeURIComponent(table)}/rows`,
      vars,
    ),
  )

export const useDeleteRow = (schema: string, table: string) =>
  useWriter<{ deleted: number }, { key: Row }>((vars) =>
    api.post(
      `${ROOT}/tables/${encodeURIComponent(schema)}/${encodeURIComponent(table)}/rows/delete`,
      vars,
    ),
  )

export function useRunQuery() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sql: string) => api.post<QueryResult>(`${ROOT}/query`, { sql }),
    onSuccess: (result) => {
      // A statement that changed something may have changed what the grid shows.
      if (result.kind === 'command') {
        void client.invalidateQueries({ queryKey: ['db'] })
      }
    },
  })
}
