import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'
import { api } from './api'
import { setActiveCluster, useActiveCluster } from './cluster'
import type {
  ApiKey,
  Cluster,
  ClusterResources,
  ContextState,
  Dashboard,
  EnvVar,
  FunctionDetail,
  FunctionMetrics,
  FunctionSummary,
  Group,
  Instance,
  JoinableNode,
  LogLine,
  ManagedService,
  MarketplaceIndex,
  MarketplacePackage,
  Metering,
  NodeInfo,
  ReconcileReport,
  ReconcileResult,
  RuntimeInfo,
  SchedulePreview,
  Secret,
  SetupStatus,
  TestResult,
  Trigger,
  UpdateProgress,
  UpdateStatus,
  User,
  Version,
} from './types'

export const keys = {
  setup: ['setup'] as const,
  clusters: ['clusters'] as const,
  me: ['me'] as const,
  dashboard: (hours: number) => ['dashboard', hours] as const,
  groups: ['groups'] as const,
  functions: ['functions'] as const,
  fn: (id: string) => ['function', id] as const,
  fnMetrics: (id: string) => ['function', id, 'metrics'] as const,
  fnLogs: (id: string) => ['function', id, 'logs'] as const,
  fnSecrets: (id: string) => ['function', id, 'secrets'] as const,
  versions: (id: string) => ['function', id, 'versions'] as const,
  env: ['env'] as const,
  logs: (level: string) => ['logs', level] as const,
  nodes: ['nodes'] as const,
  metering: ['metering'] as const,
  services: ['services'] as const,
  instance: ['instance'] as const,
  apiKeys: ['api-keys'] as const,
  users: ['users'] as const,
  update: ['update'] as const,
  resources: ['cluster', 'resources'] as const,
  market: (registry: string) => ['marketplace', registry] as const,
  marketPackage: (url: string) => ['marketplace', 'package', url] as const,
  runtimes: ['runtimes'] as const,
  triggers: (id: string) => ['function', id, 'triggers'] as const,
  updateProgress: ['update', 'progress'] as const,
  context: (groupId: string, session: string) => ['context', groupId, session] as const,
}

type Q<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, 'queryKey' | 'queryFn'>

// ── setup & session ──────────────────────────────────────────────────────────

export const useSetupStatus = () =>
  useQuery({
    queryKey: keys.setup,
    queryFn: () => api.get<SetupStatus>('/api/setup/status'),
    staleTime: 30_000,
    retry: 1,
  })

export const useJoinableNodes = (enabled = true) =>
  useQuery({
    queryKey: ['setup', 'nodes'],
    queryFn: () => api.get<JoinableNode[]>('/api/setup/nodes'),
    enabled,
    retry: false,
  })

export const useMe = (options: Q<User> = {}) =>
  useQuery({
    queryKey: keys.me,
    queryFn: () => api.get<User>('/api/auth/me'),
    retry: false,
    staleTime: 60_000,
    ...options,
  })

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api.post<User>('/api/auth/login', body),
    onSuccess: (user) => {
      client.setQueryData(keys.me, user)
      void client.invalidateQueries()
    },
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/api/auth/logout'),
    onSuccess: () => client.clear(),
  })
}

// ── clusters ─────────────────────────────────────────────────────────────────

export const useClusters = () =>
  useQuery({ queryKey: keys.clusters, queryFn: () => api.get<Cluster[]>('/api/clusters') })

/**
 * Point the console at another cluster.
 *
 * Every cluster-scoped query key ends with the cluster, so this only has to
 * change the cluster: the keys change with it and React Query fetches the new
 * ones. Nothing has to be evicted, which means a switch can never render one
 * cluster's data under another's name, and switching back is instant because
 * the previous cluster's pages are still cached.
 */
export function useSwitchCluster() {
  const client = useQueryClient()
  return (slug: string | null) => {
    setActiveCluster(slug)
    // The cluster list itself is instance-wide, but its per-cluster counts
    // change as soon as you act inside one.
    void client.invalidateQueries({ queryKey: keys.clusters })
  }
}

export function useCreateCluster() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Cluster>('/api/clusters', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clusters }),
  })
}

/** Ceilings are owner-only on the server; the UI mirrors that, not enforces it. */
export function useSetClusterQuota(slug: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      max_memory_mb?: number
      max_cpu_cores?: number
      max_storage_gb?: number
    }) => api.put<Cluster>(`/api/clusters/${slug}/quota`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.clusters })
      void client.invalidateQueries({ queryKey: keys.instance })
    },
  })
}

/**
 * Every runtime, and whether its image is on this node.
 *
 * Needed wherever a runtime is chosen, so it is cached rather than refetched:
 * the set changes only when someone installs one.
 */
export function useRuntimes() {
  return useQuery({
    queryKey: keys.runtimes,
    queryFn: () => api.get<RuntimeInfo[]>('/api/runtimes'),
    staleTime: 60_000,
  })
}

export function useInstallRuntime() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => api.post<Record<string, string>>(`/api/runtimes/${key}/install`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runtimes }),
  })
}

export function useUninstallRuntime() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => api.delete<Record<string, unknown>>(`/api/runtimes/${key}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runtimes }),
  })
}

// ── triggers ─────────────────────────────────────────────────────────────────

export function useTriggers(functionId: string) {
  return useQuery({
    queryKey: keys.triggers(functionId),
    queryFn: () => api.get<Trigger[]>(`/api/functions/${functionId}/triggers`),
    enabled: Boolean(functionId),
    // A schedule that just fired should show its outcome without a reload.
    refetchInterval: 30_000,
  })
}

/** Validates as it is typed, and says when it would next fire. */
export function useSchedulePreview(functionId: string, cron: string, timezone: string) {
  return useQuery({
    queryKey: ['schedule-preview', cron, timezone],
    queryFn: () =>
      api.get<SchedulePreview>(
        `/api/functions/${functionId}/triggers/-/preview` +
          `?cron=${encodeURIComponent(cron)}&timezone=${encodeURIComponent(timezone)}`,
      ),
    enabled: Boolean(functionId && cron.trim()),
    retry: false,
  })
}

export function useCreateTrigger(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { cron: string; timezone: string; enabled?: boolean }) =>
      api.post<Trigger>(`/api/functions/${functionId}/triggers`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.triggers(functionId) }),
  })
}

export function useUpdateTrigger(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      api.patch<Trigger>(`/api/functions/${functionId}/triggers/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.triggers(functionId) }),
  })
}

export function useRunTrigger(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api.post<Trigger>(`/api/functions/${functionId}/triggers/${id}/run`, {}),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.triggers(functionId) }),
  })
}

export function useDeleteTrigger(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/functions/${functionId}/triggers/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.triggers(functionId) }),
  })
}

// ── marketplace ──────────────────────────────────────────────────────────────

export function useMarketplace(registry: string) {
  return useQuery({
    queryKey: keys.market(registry),
    queryFn: () =>
      api.get<MarketplaceIndex>(
        registry ? `/api/marketplace?url=${encodeURIComponent(registry)}` : '/api/marketplace',
      ),
    retry: false,
    staleTime: 60_000,
  })
}

/** The whole package including its source, so it can be read before installing. */
export function useMarketplacePackage(url: string | null) {
  return useQuery({
    queryKey: keys.marketPackage(url ?? ''),
    queryFn: () =>
      api.get<MarketplacePackage>(`/api/marketplace/package?url=${encodeURIComponent(url ?? '')}`),
    enabled: Boolean(url),
    retry: false,
  })
}

export function useInstallFromMarketplace() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { url: string; group_id: string; name?: string }) =>
      api.post<FunctionDetail & { declared_env: MarketplacePackage['env'] }>(
        '/api/marketplace/install',
        body,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.functions })
      void client.invalidateQueries({ queryKey: keys.groups })
    },
  })
}

/**
 * Headroom against the cluster's ceilings, refreshed on a timer.
 *
 * Polled rather than streamed: this sits in the header of every page, and a
 * second SSE connection per tab would compete with the activity stream for the
 * browser's per-origin limit.
 */
export function useClusterResources() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.resources, scope],
    queryFn: () => api.get<ClusterResources>('/api/cluster/resources'),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    retry: false,
  })
}

/**
 * Whether the checkout is behind the branch. Cached hard on the server, so
 * asking on every visit to Settings costs nothing.
 */
export function useUpdateStatus(enabled: boolean) {
  return useQuery({
    queryKey: keys.update,
    queryFn: () => api.get<UpdateStatus>('/api/update'),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useCheckForUpdate() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.get<UpdateStatus>('/api/update?refresh=true'),
    onSuccess: (next) => client.setQueryData(keys.update, next),
  })
}

export function useStartUpdate() {
  return useMutation({ mutationFn: () => api.post<UpdateProgress>('/api/update/apply', {}) })
}

/**
 * Polls the updater while it runs.
 *
 * The API is one of the things being replaced, so requests will fail partway
 * through. A failure here means "still restarting", not "finished" — hence no
 * retry limit and no error surfaced while an update is in flight.
 */
export function useUpdateProgress(active: boolean) {
  return useQuery({
    queryKey: keys.updateProgress,
    queryFn: () => api.get<UpdateProgress>('/api/update/progress'),
    enabled: active,
    refetchInterval: active ? 2000 : false,
    retry: true,
    retryDelay: 2000,
    gcTime: 0,
  })
}

/**
 * Scanning is a mutation rather than a query on purpose: it walks every Docker
 * engine, so it happens when the operator asks and never on a refetch.
 */
export function useReconcileScan() {
  return useMutation({ mutationFn: () => api.get<ReconcileReport>('/api/reconcile') })
}

export function useReconcileApply() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => api.post<ReconcileResult>('/api/reconcile/apply', { ids }),
    onSuccess: () => {
      // Services may have been marked stopped and isolates dropped.
      void client.invalidateQueries({ queryKey: keys.clusters })
      void client.invalidateQueries({ queryKey: keys.instance })
    },
  })
}

export function useUpdateCluster() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ ref, ...body }: { ref: string } & Record<string, unknown>) =>
      api.patch<Cluster>(`/api/clusters/${ref}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.clusters })
      void client.invalidateQueries({ queryKey: keys.instance })
    },
  })
}

export function useSetDefaultCluster() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (ref: string) => api.post<Cluster>(`/api/clusters/${ref}/default`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clusters }),
  })
}

export function useDeleteCluster() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (ref: string) => api.delete<void>(`/api/clusters/${ref}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clusters }),
  })
}

// ── dashboard ────────────────────────────────────────────────────────────────

export function useDashboard(hours = 24) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.dashboard(hours), scope],
    queryFn: () => api.get<Dashboard>(`/api/dashboard?hours=${hours}`),
    refetchInterval: 15_000,
  })
}

// ── namespaces & functions ───────────────────────────────────────────────────

export function useGroups() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.groups, scope],
    queryFn: () => api.get<Group[]>('/api/groups'),
  })
}

export function useCreateGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string }) => api.post<Group>('/api/groups', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.groups }),
  })
}

export function useDeleteGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/groups/${id}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.groups })
      void client.invalidateQueries({ queryKey: keys.functions })
    },
  })
}

export function useFunctions(groupId?: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: groupId ? [...keys.functions, groupId, scope] : [...keys.functions, scope],
    queryFn: () =>
      api.get<FunctionSummary[]>(
        groupId ? `/api/functions?group_id=${groupId}` : '/api/functions',
      ),
  })
}

export function useFunction(id: string | undefined, options: Q<FunctionDetail> = {}) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.fn(id ?? ''), scope],
    queryFn: () => api.get<FunctionDetail>(`/api/functions/${id}`),
    enabled: Boolean(id),
    ...options,
  })
}

export function useFunctionMetrics(id: string | undefined) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.fnMetrics(id ?? ''), scope],
    queryFn: () => api.get<FunctionMetrics>(`/api/functions/${id}/metrics`),
    enabled: Boolean(id),
  })
}

export function useFunctionLogs(id: string | undefined) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.fnLogs(id ?? ''), scope],
    queryFn: () => api.get<LogLine[]>(`/api/functions/${id}/logs`),
    enabled: Boolean(id),
    refetchInterval: 10_000,
  })
}

export function useVersions(id: string | undefined) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.versions(id ?? ''), scope],
    queryFn: () => api.get<Version[]>(`/api/functions/${id}/versions`),
    enabled: Boolean(id),
  })
}

export function useCreateFunction(groupId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<FunctionDetail>(`/api/groups/${groupId}/functions`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.functions })
      void client.invalidateQueries({ queryKey: keys.groups })
    },
  })
}

export function useUpdateFunction(id: string) {
  const client = useQueryClient()
  const scope = useActiveCluster()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch<FunctionDetail>(`/api/functions/${id}`, body),
    onSuccess: (data) => {
      client.setQueryData([...keys.fn(id), scope], data)
      void client.invalidateQueries({ queryKey: keys.functions })
    },
  })
}

export function useDeployFunction(id: string) {
  const client = useQueryClient()
  const scope = useActiveCluster()
  return useMutation({
    mutationFn: (files: Record<string, string>) =>
      api.post<FunctionDetail>(`/api/functions/${id}/deploy`, { files }),
    onSuccess: (data) => {
      client.setQueryData([...keys.fn(id), scope], data)
      void client.invalidateQueries({ queryKey: keys.versions(id) })
      void client.invalidateQueries({ queryKey: keys.functions })
    },
  })
}

export function useDeleteFunction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/functions/${id}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.functions })
      void client.invalidateQueries({ queryKey: keys.groups })
    },
  })
}

export interface FunctionIsolate {
  id: string
  node: string
  busy: boolean
  invocations: number
  memory_mb: number
  cpus: number
  age_s: number
  idle_s: number
}

export interface IsolateList {
  isolates: FunctionIsolate[]
  min_instances: number
  max_instances: number
  memory_mb: number
  version: number
}

/** What is running for this function right now. Polled, because isolates are
 *  runtime state and the pool is the only thing that knows. */
export function useFunctionIsolates(id: string, enabled = true) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: ['fn-isolates', id, scope],
    queryFn: () => api.get<IsolateList>(`/api/functions/${id}/isolates`),
    enabled: Boolean(id) && enabled,
    refetchInterval: enabled ? 3000 : false,
  })
}

export function useDestroyIsolate(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (isolateId: string) => api.delete(`/api/functions/${id}/isolates/${isolateId}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['fn-isolates', id] })
    },
  })
}

export function useTestInvoke(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { body?: unknown; session_id?: string }) =>
      api.post<TestResult>(`/api/functions/${id}/test`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['context'] })
      void client.invalidateQueries({ queryKey: keys.fnLogs(id) })
    },
  })
}

// ── session context ──────────────────────────────────────────────────────────

export function useContextState(groupId: string | undefined, session: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.context(groupId ?? '', session), scope],
    queryFn: () =>
      api.get<ContextState>(
        `/api/groups/${groupId}/context?session=${encodeURIComponent(session)}`,
      ),
    enabled: Boolean(groupId && session),
  })
}

export function useClearContext(groupId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (session: string) =>
      api.delete<void>(`/api/groups/${groupId}/context?session=${encodeURIComponent(session)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['context'] }),
  })
}

// ── configuration ────────────────────────────────────────────────────────────

export function useEnvVars() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.env, scope],
    queryFn: () => api.get<EnvVar[]>('/api/env'),
  })
}

export function useSaveEnvVar() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { key: string; value: string; is_secret: boolean }) =>
      api.post<EnvVar>('/api/env', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.env }),
  })
}

export function useDeleteEnvVar() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => api.delete<void>(`/api/env/${encodeURIComponent(key)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.env }),
  })
}

export const revealEnvVar = (key: string) =>
  api.get<EnvVar>(`/api/env/${encodeURIComponent(key)}/reveal`)

export function useSecrets(functionId: string | undefined) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.fnSecrets(functionId ?? ''), scope],
    queryFn: () => api.get<Secret[]>(`/api/functions/${functionId}/secrets`),
    enabled: Boolean(functionId),
  })
}

export function useSaveSecret(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { key: string; value: string }) =>
      api.post<Secret>(`/api/functions/${functionId}/secrets`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.fnSecrets(functionId) }),
  })
}

export function useDeleteSecret(functionId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (key: string) =>
      api.delete<void>(`/api/functions/${functionId}/secrets/${encodeURIComponent(key)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.fnSecrets(functionId) }),
  })
}

// ── observability ────────────────────────────────────────────────────────────

export function useLogs(level: string) {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.logs(level), scope],
    queryFn: () => api.get<LogLine[]>(`/api/logs?level=${level}&limit=150`),
  })
}

// ── cluster ──────────────────────────────────────────────────────────────────

export function useNodes() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.nodes, scope],
    queryFn: () => api.get<NodeInfo[]>('/api/cluster/nodes'),
    refetchInterval: 20_000,
  })
}

export function useMetering() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.metering, scope],
    queryFn: () => api.get<Metering>('/api/cluster/metering'),
    refetchInterval: 60_000,
  })
}

export function useDrainNode() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, drain }: { id: string; drain: boolean }) =>
      api.post<unknown>(`/api/cluster/nodes/${id}/${drain ? 'drain' : 'resume'}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.nodes }),
  })
}

// ── managed services ─────────────────────────────────────────────────────────

export function useServices() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.services, scope],
    queryFn: () => api.get<ManagedService[]>('/api/services'),
    refetchInterval: 20_000,
  })
}

export function useServiceAction(kind: 'postgres' | 'redis') {
  const client = useQueryClient()
  const invalidate = () => client.invalidateQueries({ queryKey: keys.services })
  return {
    create: useMutation({
      mutationFn: (body: Record<string, string>) =>
        api.post<ManagedService>(`/api/services/${kind}`, body),
      onSuccess: invalidate,
    }),
    recreate: useMutation({
      mutationFn: () => api.post<ManagedService>(`/api/services/${kind}/recreate`),
      onSuccess: invalidate,
    }),
    start: useMutation({
      mutationFn: () => api.post<ManagedService>(`/api/services/${kind}/start`),
      onSuccess: invalidate,
    }),
    stop: useMutation({
      mutationFn: () => api.post<ManagedService>(`/api/services/${kind}/stop`),
      onSuccess: invalidate,
    }),
    destroy: useMutation({
      mutationFn: (keepData?: boolean) =>
        api.delete<void>(`/api/services/${kind}?keep_data=${keepData ? 'true' : 'false'}`),
      onSuccess: invalidate,
    }),
    reveal: () => api.get<ManagedService>(`/api/services/${kind}/connection`),
  }
}

// ── settings ─────────────────────────────────────────────────────────────────

export function useInstance() {
  const scope = useActiveCluster()
  return useQuery({
    queryKey: [...keys.instance, scope],
    queryFn: () => api.get<Instance>('/api/settings/instance'),
  })
}

export function useUpdateInstance() {
  const client = useQueryClient()
  const scope = useActiveCluster()
  return useMutation({
    mutationFn: (body: Record<string, string>) =>
      api.patch<Instance>('/api/settings/instance', body),
    onSuccess: (data) => client.setQueryData([...keys.instance, scope], data),
  })
}

export const useApiKeys = () =>
  useQuery({
    queryKey: keys.apiKeys,
    queryFn: () => api.get<ApiKey[]>('/api/settings/api-keys'),
  })

export function useCreateApiKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; scope: string }) =>
      api.post<ApiKey>('/api/settings/api-keys', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.apiKeys }),
  })
}

export function useRevokeApiKey() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/settings/api-keys/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.apiKeys }),
  })
}

export const useUsers = () =>
  useQuery({ queryKey: keys.users, queryFn: () => api.get<User[]>('/api/settings/users') })

export function useCreateUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<User>('/api/settings/users', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  })
}

export function useUpdateUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      api.patch<User>(`/api/settings/users/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  })
}

export function useDeleteUser() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/settings/users/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post<void>('/api/auth/password', body),
  })
}
