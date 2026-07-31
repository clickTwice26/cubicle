import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'
import { api } from './api'
import type {
  ApiKey,
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
  Metering,
  NodeInfo,
  Secret,
  SetupStatus,
  TestResult,
  User,
  Version,
} from './types'

export const keys = {
  setup: ['setup'] as const,
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

// ── dashboard ────────────────────────────────────────────────────────────────

export const useDashboard = (hours = 24) =>
  useQuery({
    queryKey: keys.dashboard(hours),
    queryFn: () => api.get<Dashboard>(`/api/dashboard?hours=${hours}`),
    refetchInterval: 15_000,
  })

// ── namespaces & functions ───────────────────────────────────────────────────

export const useGroups = () =>
  useQuery({ queryKey: keys.groups, queryFn: () => api.get<Group[]>('/api/groups') })

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

export const useFunctions = (groupId?: string) =>
  useQuery({
    queryKey: groupId ? ([...keys.functions, groupId] as const) : keys.functions,
    queryFn: () =>
      api.get<FunctionSummary[]>(
        groupId ? `/api/functions?group_id=${groupId}` : '/api/functions',
      ),
  })

export const useFunction = (id: string | undefined, options: Q<FunctionDetail> = {}) =>
  useQuery({
    queryKey: keys.fn(id ?? ''),
    queryFn: () => api.get<FunctionDetail>(`/api/functions/${id}`),
    enabled: Boolean(id),
    ...options,
  })

export const useFunctionMetrics = (id: string | undefined) =>
  useQuery({
    queryKey: keys.fnMetrics(id ?? ''),
    queryFn: () => api.get<FunctionMetrics>(`/api/functions/${id}/metrics`),
    enabled: Boolean(id),
  })

export const useFunctionLogs = (id: string | undefined) =>
  useQuery({
    queryKey: keys.fnLogs(id ?? ''),
    queryFn: () => api.get<LogLine[]>(`/api/functions/${id}/logs`),
    enabled: Boolean(id),
    refetchInterval: 10_000,
  })

export const useVersions = (id: string | undefined) =>
  useQuery({
    queryKey: keys.versions(id ?? ''),
    queryFn: () => api.get<Version[]>(`/api/functions/${id}/versions`),
    enabled: Boolean(id),
  })

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
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch<FunctionDetail>(`/api/functions/${id}`, body),
    onSuccess: (data) => {
      client.setQueryData(keys.fn(id), data)
      void client.invalidateQueries({ queryKey: keys.functions })
    },
  })
}

export function useDeployFunction(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (files: Record<string, string>) =>
      api.post<FunctionDetail>(`/api/functions/${id}/deploy`, { files }),
    onSuccess: (data) => {
      client.setQueryData(keys.fn(id), data)
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

export const useContextState = (groupId: string | undefined, session: string) =>
  useQuery({
    queryKey: keys.context(groupId ?? '', session),
    queryFn: () =>
      api.get<ContextState>(
        `/api/groups/${groupId}/context?session=${encodeURIComponent(session)}`,
      ),
    enabled: Boolean(groupId && session),
  })

export function useClearContext(groupId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (session: string) =>
      api.delete<void>(`/api/groups/${groupId}/context?session=${encodeURIComponent(session)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['context'] }),
  })
}

// ── configuration ────────────────────────────────────────────────────────────

export const useEnvVars = () =>
  useQuery({ queryKey: keys.env, queryFn: () => api.get<EnvVar[]>('/api/env') })

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

export const useSecrets = (functionId: string | undefined) =>
  useQuery({
    queryKey: keys.fnSecrets(functionId ?? ''),
    queryFn: () => api.get<Secret[]>(`/api/functions/${functionId}/secrets`),
    enabled: Boolean(functionId),
  })

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

export const useLogs = (level: string) =>
  useQuery({
    queryKey: keys.logs(level),
    queryFn: () => api.get<LogLine[]>(`/api/logs?level=${level}&limit=150`),
  })

// ── cluster ──────────────────────────────────────────────────────────────────

export const useNodes = () =>
  useQuery({
    queryKey: keys.nodes,
    queryFn: () => api.get<NodeInfo[]>('/api/cluster/nodes'),
    refetchInterval: 20_000,
  })

export const useMetering = () =>
  useQuery({
    queryKey: keys.metering,
    queryFn: () => api.get<Metering>('/api/cluster/metering'),
    refetchInterval: 60_000,
  })

export function useDrainNode() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, drain }: { id: string; drain: boolean }) =>
      api.post<unknown>(`/api/cluster/nodes/${id}/${drain ? 'drain' : 'resume'}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.nodes }),
  })
}

// ── managed services ─────────────────────────────────────────────────────────

export const useServices = () =>
  useQuery({
    queryKey: keys.services,
    queryFn: () => api.get<ManagedService[]>('/api/services'),
    refetchInterval: 20_000,
  })

export function useServiceAction(kind: 'postgres' | 'redis') {
  const client = useQueryClient()
  const invalidate = () => client.invalidateQueries({ queryKey: keys.services })
  return {
    create: useMutation({
      mutationFn: (body: Record<string, string>) =>
        api.post<ManagedService>(`/api/services/${kind}`, body),
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
      mutationFn: () => api.delete<void>(`/api/services/${kind}`),
      onSuccess: invalidate,
    }),
    reveal: () => api.get<ManagedService>(`/api/services/${kind}/connection`),
  }
}

// ── settings ─────────────────────────────────────────────────────────────────

export const useInstance = () =>
  useQuery({
    queryKey: keys.instance,
    queryFn: () => api.get<Instance>('/api/settings/instance'),
  })

export function useUpdateInstance() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, string>) =>
      api.patch<Instance>('/api/settings/instance', body),
    onSuccess: (data) => client.setQueryData(keys.instance, data),
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
    mutationFn: (body: Record<string, string>) => api.post<User>('/api/settings/users', body),
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
