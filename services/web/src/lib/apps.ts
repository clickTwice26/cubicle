import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { activeCluster } from './cluster'
import { useActiveCluster } from './cluster'

const ROOT = '/api/apps'

export type AppStatus = 'created' | 'deploying' | 'running' | 'stopped' | 'failed'
export type DeployStatus = 'pending' | 'building' | 'releasing' | 'live' | 'failed'

export interface AppDomain {
  id: string
  hostname: string
  primary: boolean
}

export interface Deployment {
  id: string
  number: number
  status: DeployStatus
  trigger: 'manual' | 'webhook' | 'cli'
  triggered_by: string
  commit_sha: string
  commit_message: string
  build_ms: number
  error: string | null
  created_at: string | null
  finished_at: string | null
  build_log?: string
}

export interface AppContainer {
  name: string
  status: string
  deployment: string
  started_at: string
}

export interface Application {
  id: string
  name: string
  source_kind: 'git' | 'image'
  repo_url: string
  branch: string
  credential_id: string | null
  credential_name: string | null
  image_ref: string
  port: number
  replicas: number
  memory_mb: number
  cpus: number
  health_path: string
  node_pool: string
  links: string[]
  volumes: { path: string }[]
  status: AppStatus
  last_error: string | null
  auto_deploy: boolean
  webhook_path: string
  definition: Record<string, unknown>
  url: string
  /** Works with no DNS at all, from the moment the app is live. */
  instant_url: string
  path_token: string
  domains: AppDomain[]
  deployment: Deployment | null
  deployment_count: number
  containers: AppContainer[]
  created_at: string | null
}

export interface GitCredential {
  id: string
  name: string
  provider: string
  username: string
  token_hint: string
  last_used_at: string | null
}

export interface LogLine {
  time: string
  replica: string
  text: string
}

const keys = {
  all: ['apps'] as const,
  one: (id: string) => ['apps', id] as const,
  deployments: (id: string) => ['apps', id, 'deployments'] as const,
  deployment: (id: string, deployment: string) => ['apps', id, 'deployments', deployment] as const,
  env: (id: string) => ['apps', id, 'env'] as const,
  credentials: ['apps', 'credentials'] as const,
}

export function useApps() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.all, scope],
    queryFn: () => api.get<Application[]>(ROOT),
    // A deploy finishes in the background, so the list keeps an eye on it.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((app) => app.status === 'deploying') ? 3000 : false,
  })
}

export function useApp(id: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.one(id), scope],
    enabled: Boolean(id),
    queryFn: () => api.get<Application>(`${ROOT}/${id}`),
    refetchInterval: (query) => (query.state.data?.status === 'deploying' ? 3000 : false),
  })
}

export function useDeployments(id: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.deployments(id), scope],
    enabled: Boolean(id),
    queryFn: () => api.get<Deployment[]>(`${ROOT}/${id}/deployments`),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((d) => ['pending', 'building', 'releasing'].includes(d.status))
        ? 3000
        : false,
  })
}

export function useDeployment(appId: string, deploymentId: string | null) {
  return useQuery({
    queryKey: keys.deployment(appId, deploymentId ?? ''),
    enabled: Boolean(appId && deploymentId),
    queryFn: () => api.get<Deployment>(`${ROOT}/${appId}/deployments/${deploymentId}`),
  })
}

export function useAppEnv(id: string) {
  return useQuery({
    queryKey: keys.env(id),
    enabled: Boolean(id),
    queryFn: () => api.get<{ env: Record<string, string> }>(`${ROOT}/${id}/env`),
  })
}

export interface Hosting {
  base_domain: string
  instance_url: string
  tls: boolean
  /** Detected on the machine itself, not looked up from outside. */
  server_ip: string
  server_ip_private: boolean
  wildcard_record: { type: string; name: string; value: string }
  example_hostname: string
  configured: boolean
}

export function useHosting() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: ['apps', 'hosting', scope],
    queryFn: () => api.get<Hosting>(`${ROOT}/hosting`),
    staleTime: 300_000,
  })
}

export function useGitCredentials() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.credentials, scope],
    queryFn: () => api.get<GitCredential[]>(`${ROOT}/credentials`),
  })
}

function useAppMutation<T, V>(fn: (vars: V) => Promise<T>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.all }),
  })
}

export interface CreateAppArgs {
  name: string
  source_kind: 'git' | 'image'
  repo_url?: string
  branch?: string
  credential_id?: string | null
  image_ref?: string
  port?: number
  replicas?: number
  memory_mb?: number
  cpus?: number
  env?: Record<string, string>
  deploy_now?: boolean
}

export const useCreateApp = () =>
  useAppMutation<Application, CreateAppArgs>((args) => api.post(ROOT, args))

export const useUpdateApp = (id: string) =>
  useAppMutation<Application, Partial<Application>>((args) => api.patch(`${ROOT}/${id}`, args))

export const useDeleteApp = () =>
  useAppMutation<void, { id: string; keepVolumes?: boolean }>((args) =>
    api.delete(`${ROOT}/${args.id}?keep_volumes=${args.keepVolumes ? 'true' : 'false'}`),
  )

export const useDeployApp = (id: string) =>
  useAppMutation<Deployment, void>(() => api.post(`${ROOT}/${id}/deploy`))

export const useStopApp = (id: string) =>
  useAppMutation<Application, void>(() => api.post(`${ROOT}/${id}/stop`))

export const useRestartApp = (id: string) =>
  useAppMutation<{ status: string }, void>(() => api.post(`${ROOT}/${id}/restart`))

export const useSetAppEnv = (id: string) => {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (env: Record<string, string>) => api.put(`${ROOT}/${id}/env`, { env }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.env(id) })
      void client.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export const useAddDomain = (id: string) =>
  useAppMutation<Application, { hostname: string; primary?: boolean }>((args) =>
    api.post(`${ROOT}/${id}/domains`, args),
  )

export const useRemoveDomain = (id: string) =>
  useAppMutation<void, string>((domainId) => api.delete(`${ROOT}/${id}/domains/${domainId}`))

export const useCreateCredential = () =>
  useAppMutation<GitCredential, { name: string; provider: string; username: string; token: string }>(
    (args) => api.post(`${ROOT}/credentials`, args),
  )

export const useDeleteCredential = () =>
  useAppMutation<void, string>((id) => api.delete(`${ROOT}/credentials/${id}`))

/**
 * Named server-sent events, which the shared helper does not do.
 *
 * Build transcripts and log tails both arrive as `event: log`, and a build
 * ends with `event: done` — the connection closes itself rather than the page
 * having to poll to find out it is over.
 */
export function subscribeEvents(
  path: string,
  handlers: { log?: (lines: unknown[]) => void; done?: (payload: unknown) => void },
): () => void {
  const cluster = activeCluster()
  const url = cluster
    ? `${path}${path.includes('?') ? '&' : '?'}cluster=${encodeURIComponent(cluster)}`
    : path
  const source = new EventSource(url, { withCredentials: true })
  const parse = (event: MessageEvent) => {
    try {
      return JSON.parse(event.data)
    } catch {
      return null
    }
  }
  source.addEventListener('log', (event) => {
    const payload = parse(event as MessageEvent)
    if (payload?.lines) handlers.log?.(payload.lines)
  })
  source.addEventListener('done', (event) => {
    handlers.done?.(parse(event as MessageEvent))
    source.close()
  })
  return () => source.close()
}
