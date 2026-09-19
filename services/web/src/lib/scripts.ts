/**
 * Host scripts: a program that runs on the machine, reached by URL.
 *
 * Ordinary REST all the way down, unlike the terminal beside it — a run is a
 * request that takes a while and then answers, which is exactly the shape
 * React Query is for. The only thing worth noting is that a run is a mutation
 * that can legitimately take minutes, so nothing here retries it: pressing the
 * button twice because the first press seemed slow is how a "delete the old
 * backups" script deletes the new ones too.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useActiveCluster } from './cluster'

const ROOT = '/api/scripts'

export interface ScriptSummary {
  id: string
  name: string
  description: string
  interpreter: string
  interpreter_label: string
  working_dir: string
  timeout_s: number
  method: string
  output_mode: 'auto' | 'json' | 'text'
  max_output_kb: number
  auth_required: boolean
  status: 'active' | 'paused'
  node_id: string | null
  node_name: string
  run_count: number
  last_run_at: string | null
  last_exit_code: number | null
  cluster: string
  path: string
  url: string
  created_at: string
  updated_at: string
}

export interface ScriptDetail extends ScriptSummary {
  source: string
  env: Record<string, string>
}

export interface ScriptRun {
  id: string
  ts: string
  trigger: string
  exit_code: number
  duration_ms: number
  stdout: string
  stderr: string
  truncated: boolean
  status_code: number
  request_id: string
  node_name: string
}

export interface RunResult {
  run_id: string
  node_name: string
  exit_code: number
  status_code: number
  duration_ms: number
  stdout: string
  stderr: string
  truncated: boolean
  timed_out: boolean
  limit_bytes: number
}

export interface ScriptsStatus {
  enabled: boolean
  interpreters: { value: string; label: string }[]
  max_timeout_s: number
  max_output_kb: number
  default_output_kb: number
}

export interface ScriptInput {
  name?: string
  description?: string
  interpreter?: string
  source?: string
  working_dir?: string
  timeout_s?: number
  method?: string
  output_mode?: string
  max_output_kb?: number
  node_id?: string | null
  auth_required?: boolean
  status?: string
  env?: Record<string, string>
}

export function useScriptsStatus(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['scripts', 'status'],
    queryFn: () => api.get<ScriptsStatus>(`${ROOT}/status`),
    ...options,
  })
}

export function useSetScriptsEnabled() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<{ enabled: boolean }>(`${ROOT}/settings`, { enabled }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['scripts'] })
    },
  })
}

export function useScripts(options: { enabled?: boolean } = {}) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: ['scripts', 'list', scope],
    queryFn: () => api.get<{ enabled: boolean; scripts: ScriptSummary[] }>(ROOT),
    ...options,
  })
}

export function useScript(id: string | null) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: ['scripts', 'detail', id, scope],
    queryFn: () => api.get<ScriptDetail>(`${ROOT}/${id}`),
    enabled: Boolean(id),
  })
}

export function useCreateScript() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ScriptInput) => api.post<ScriptSummary>(ROOT, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['scripts', 'list'] }),
  })
}

export function useUpdateScript() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: ScriptInput & { id: string }) =>
      api.patch<ScriptSummary>(`${ROOT}/${id}`, body),
    onSuccess: (_data, variables) => {
      client.invalidateQueries({ queryKey: ['scripts', 'list'] })
      client.invalidateQueries({ queryKey: ['scripts', 'detail', variables.id] })
    },
  })
}

export function useDeleteScript() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ROOT}/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['scripts', 'list'] }),
  })
}

export function useRunScript() {
  const client = useQueryClient()
  return useMutation({
    // No retry, at any cost: a run has already changed the machine by the time
    // anything here could decide it went wrong.
    retry: false,
    mutationFn: ({
      id,
      body,
      query,
    }: {
      id: string
      body?: string
      query?: Record<string, string>
    }) => api.post<RunResult>(`${ROOT}/${id}/run`, { body: body ?? '', query: query ?? {} }),
    onSuccess: (_data, variables) => {
      client.invalidateQueries({ queryKey: ['scripts', 'runs', variables.id] })
      client.invalidateQueries({ queryKey: ['scripts', 'list'] })
    },
  })
}

export function useScriptRuns(id: string | null) {
  return useQuery({
    queryKey: ['scripts', 'runs', id],
    queryFn: () => api.get<ScriptRun[]>(`${ROOT}/${id}/runs`),
    enabled: Boolean(id),
  })
}
