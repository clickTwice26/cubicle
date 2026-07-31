export type Runtime = 'python312' | 'python311'
export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type CtxAccess = 'rw' | 'r' | 'w' | 'none'
export type Role = 'owner' | 'admin' | 'developer' | 'readonly'

export interface Cluster {
  id: string
  name: string
  slug: string
  ingress_domain: string
  data_dir: string
  kms_backend: string
  default_node_pool: string
  is_default: boolean
  status: string
  description: string
  base_url: string
  node_count: number
  function_count: number
  namespace_count: number
  created_at: string
}

export interface SetupStatus {
  setup_complete: boolean
  version: string
  cluster_name: string | null
  public_url: string
  domain: string
  tls: boolean
}

export interface JoinableNode {
  name: string
  spec: string
  status: string
  is_local: boolean
  engine_version: string
  detected: boolean
}

export interface ProvisionStep {
  id: string
  label: string
  meta: string
  status: 'pending' | 'running' | 'done' | 'failed'
}

export interface User {
  id: string
  email: string
  name: string
  role: Role
  initials: string
  is_active: boolean
  last_login_at: string | null
}

export interface Group {
  id: string
  name: string
  ns: string
  base_url: string
  function_count: number
  created_at: string
}

export interface FunctionStats {
  invocations: number
  invocations_label: string
  p50: string
  p90?: string
  p95: string
  p99?: string
  error_rate: string
  cold_rate: string
  errors?: number
  last_deploy?: string | null
}

export interface FunctionSummary {
  id: string
  group_id: string
  namespace: string
  name: string
  method: Method
  runtime: Runtime
  runtime_label: string
  ctx_access: CtxAccess
  memory_mb: number
  timeout_s: number
  min_instances: number
  node_pool: string
  auth_required: boolean
  status: 'active' | 'paused' | 'degraded'
  path: string
  url: string
  version: number
  version_status: 'pending' | 'building' | 'ready' | 'failed'
  cluster?: string
  updated_at: string
  created_at: string
  stats: FunctionStats
  warm?: boolean
}

export interface FunctionDetail extends FunctionSummary {
  files: Record<string, string>
  build_log: string
  build_ms: number
}

export interface Version {
  id: string
  number: number
  status: string
  build_ms: number
  build_log: string
  created_at: string
  deployed_at: string | null
}

export interface Kpi {
  label: string
  value: string
  delta: string | null
  direction: 'up' | 'down' | 'flat'
}

export interface ChartBar {
  bucket: string
  ok: number
  err: number
}

export interface Dashboard {
  kpis: Kpi[]
  chart: ChartBar[]
  functions: FunctionSummary[]
  function_count: number
  node_count: number
  warm_isolates: number
  window_hours: number
}

export interface LogLine {
  id: string
  ts: string
  time: string
  level: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG'
  function_name: string
  message: string
  duration: string | null
  request_id: string
}

export interface EnvVar {
  key: string
  value: string
  is_secret: boolean
  masked: boolean
  updated_at: string
}

export interface Secret {
  key: string
  value: string
  updated_at: string
}

export interface NodeInfo {
  id: string
  name: string
  pool: string
  status: string
  arch: string
  cpus: number
  memory_bytes: number
  spec: string
  is_local: boolean
  schedulable: boolean
  engine_version: string
  cpu_allocated_pct: number
  memory_allocated_pct: number
  memory_label: string
  isolates: number
  last_error: string | null
}

export interface CostRow {
  key: string
  name: string
  colour: string
  requests: number
  compute: number
  egress: number
  total: number
  bar: number
  saved: number | null
  self?: boolean
}

export interface Metering {
  window_start: string
  window_end: string
  window_progress: number
  invocations: number
  invocations_label: string
  gb_seconds: number
  gb_seconds_label: string
  egress_bytes: number
  egress_label: string
  storage_bytes: number
  storage_label: string
  warm_isolates: number
  namespaces: {
    name: string
    invocations: number
    invocations_label: string
    gb_seconds: number
    gb_seconds_label: string
  }[]
  cost: {
    rows: CostRow[]
    self_hosted_total: number
    avoided_vs_aws: number
    rates_as_of: string
    kwh_price: number
  }
}

export interface ManagedService {
  kind: 'postgres' | 'redis'
  created: boolean
  status: 'not_created' | 'running' | 'stopped'
  version: string
  config: Record<string, string>
  connection_url: string | null
  node: string
  stats: Record<string, number | string>
  last_error: string | null
}

export interface Instance {
  cluster_id: string
  cluster_name: string
  cluster_slug: string
  ingress_domain: string
  data_dir: string
  kms_backend: string
  default_node_pool: string
  is_default: boolean
  base_url: string
  cluster_count: number
  version: string
  public_url: string
  tls: boolean
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  scope: string
  created_at: string
  last_used_at: string | null
  token?: string | null
}

export interface ContextState {
  session_id: string
  data: Record<string, unknown>
  log: { time: string; fn: string; detail: string }[]
  size_bytes: number
  ttl_seconds: number
}

export interface TestResult {
  status_code: number
  duration_ms: number
  cold: boolean
  body: unknown
  logs: string[]
  error: string | null
  context_read: string[]
  context_wrote: string[]
}

export interface LatencyPoint {
  bucket: string
  p95: number
  fill: number
  cold: number
  cold_pct: number
}

export interface FunctionMetrics {
  stats: FunctionStats & { gb_seconds: number }
  latency: LatencyPoint[]
  invocations: ChartBar[]
}
