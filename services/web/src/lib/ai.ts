import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

const ROOT = '/api/ai'

export interface AiStatus {
  enabled: boolean
  model: string
  base_url: string
  provider: string
  /** A masked shape of the stored key — never the key. */
  key_hint: string | null
  key_source: 'console' | 'environment' | null
  max_prompt_chars: number
}

/** Exactly what left the machine, so the panel can show it rather than promise it. */
export interface ContextSent {
  function: {
    namespace: string
    name: string
    method: string
    runtime: string
    context_access: string
    timeout_seconds: number
    memory_mb: number
    max_instances: number
    auth_required: boolean
  }
  env_keys: { key: string; secret: boolean }[]
  secret_keys: string[]
  context: { key: string; type: string; preview: string }[]
  services: { kind: string; available: boolean; version: string | null }[]
  siblings: { name: string; method: string; path: string }[]
}

export interface Generation {
  code: string
  requirements: string[]
  /** The README the assistant thinks the function should now have. */
  readme: string
  notes: string
  model: string
  usage: { prompt_tokens: number; completion_tokens: number }
  duration_ms: number
  context_sent: ContextSent
}

export interface GenerateArgs {
  function_id: string
  prompt: string
  mode: 'write' | 'edit'
  code?: string
  requirements?: string
  readme?: string
  session_id?: string
  /** Earlier turns, oldest first. Only what was said, never the code. */
  history?: { role: 'user' | 'assistant'; content: string }[]
}

export function useAiStatus() {
  return useQuery({
    queryKey: ['ai', 'status'],
    queryFn: () => api.get<AiStatus>(`${ROOT}/status`),
    staleTime: 60_000,
  })
}

export function useGenerate() {
  return useMutation({
    mutationFn: (args: GenerateArgs) => api.post<Generation>(`${ROOT}/generate`, args),
  })
}

export interface AiSettingsUpdate {
  /** Omit to leave the stored key alone; '' clears it. */
  api_key?: string
  base_url?: string
  model?: string
}

export function useUpdateAiSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (update: AiSettingsUpdate) => api.put<AiStatus>(`${ROOT}/settings`, update),
    onSuccess: (status) => client.setQueryData(['ai', 'status'], status),
  })
}

export interface AiCheck {
  ok: boolean
  model: string
  provider: string
  duration_ms: number
}

export function useTestAi() {
  return useMutation({ mutationFn: () => api.post<AiCheck>(`${ROOT}/test`) })
}
