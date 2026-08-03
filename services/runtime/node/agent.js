/**
 * Isolate agent — JavaScript.
 *
 * The Node counterpart of agent.py, speaking the identical protocol so the
 * control plane cannot tell the two apart:
 *
 *   GET  /healthz  -> {"ready": bool, "error": string|null, "fatal": bool}
 *   POST /invoke   -> {"status_code", "body", "headers", "logs",
 *                      "context_writes", "context_deletes", "error"}
 *
 * Node built-ins only. The less this has to load, the shorter the cold start —
 * the same reasoning that keeps the Python agent on the standard library.
 */

'use strict'

const http = require('node:http')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const PORT = Number(process.env.CUBICLE_AGENT_PORT || 8080)
const SOURCE = process.env.CUBICLE_HANDLER_PATH || '/srv/handler.js'
const ENTRYPOINT = process.env.CUBICLE_ENTRYPOINT || 'handler'
const MAX_LOG_LINES = 200

let handler = null
let loadError = null

// ── loading ──────────────────────────────────────────────────────────────────

/**
 * Resolve the exported handler across the shapes people actually write:
 * `export function handler`, `export default`, and `module.exports =`.
 */
function pick(mod) {
  if (!mod) return null
  if (typeof mod[ENTRYPOINT] === 'function') return mod[ENTRYPOINT]
  const fallback = mod.default
  if (typeof fallback === 'function') return fallback
  if (fallback && typeof fallback[ENTRYPOINT] === 'function') return fallback[ENTRYPOINT]
  return null
}

async function load() {
  try {
    // A dynamic import handles ESM and CommonJS alike; require() would refuse
    // the first, which is what most people write now.
    const mod = await import(pathToFileURL(path.resolve(SOURCE)).href)
    handler = pick(mod)
    if (!handler) {
      loadError =
        `${SOURCE} does not export '${ENTRYPOINT}'. ` +
        `Export it by name, or as the default export.`
    }
  } catch (err) {
    loadError = (err && err.stack) || String(err)
    handler = null
  }
}

// ── per-invocation console capture ───────────────────────────────────────────
//
// A module-level buffer is safe here: the pool marks an isolate busy for the
// duration of a request and only ever hands out idle ones, so exactly one
// invocation runs in this process at a time.

let logs = null
const real = {
  log: console.log,
  info: console.info,
  warn: console.warn,
  error: console.error,
  debug: console.debug,
}

function record(level, args) {
  const message = args
    .map((value) => {
      if (typeof value === 'string') return value
      try {
        return JSON.stringify(value)
      } catch {
        return String(value)
      }
    })
    .join(' ')

  for (const line of message.split('\n')) {
    if (logs && logs.length < MAX_LOG_LINES) logs.push({ level, message: line.slice(0, 4000) })
  }
}

function captureConsole() {
  console.log = (...args) => (logs ? record('INFO', args) : real.log(...args))
  console.info = (...args) => (logs ? record('INFO', args) : real.info(...args))
  console.debug = (...args) => (logs ? record('DEBUG', args) : real.debug(...args))
  console.warn = (...args) => (logs ? record('WARN', args) : real.warn(...args))
  console.error = (...args) => (logs ? record('ERROR', args) : real.error(...args))
}

// ── request and context ──────────────────────────────────────────────────────

class Request {
  constructor(payload) {
    this.body = payload.body ?? null
    this.headers = { ...(payload.headers || {}) }
    this.method = payload.method || 'POST'
    this.query = { ...(payload.query || {}) }
    this.path = payload.path || '/'
    this.sessionId = payload.session_id || ''
    this.requestId = payload.request_id || ''
    this.namespace = payload.namespace || ''
    this.function = payload.function || ''
    this.trigger = payload.trigger || 'http'
  }

  /** The body as an object, whether it arrived parsed or as a JSON string. */
  json() {
    if (this.body === null || this.body === '') return null
    if (typeof this.body === 'object') return this.body
    try {
      return JSON.parse(this.body)
    } catch {
      return this.body
    }
  }

  text() {
    if (this.body === null) return ''
    return typeof this.body === 'string' ? this.body : JSON.stringify(this.body)
  }

  header(name, fallback = null) {
    return this.headers[String(name).toLowerCase()] ?? fallback
  }
}

class ContextAccessError extends Error {}

class Context {
  constructor(data, access, sessionId) {
    this._data = { ...(data || {}) }
    this._writes = {}
    this._deletes = []
    this._access = access || 'rw'
    this.sessionId = sessionId || ''
  }

  get readable() {
    return this._access.includes('r')
  }

  get writable() {
    return this._access.includes('w')
  }

  get(key, fallback = null) {
    if (!this.readable) {
      throw new ContextAccessError(
        `this function has '${this._access}' context access and cannot read the context`,
      )
    }
    return key in this._data ? this._data[key] : fallback
  }

  set(key, value) {
    if (!this.writable) {
      throw new ContextAccessError(
        `this function has '${this._access}' context access and cannot write the context`,
      )
    }
    this._data[key] = value
    this._writes[key] = value
    const at = this._deletes.indexOf(key)
    if (at !== -1) this._deletes.splice(at, 1)
  }

  delete(key) {
    if (!this.writable) {
      throw new ContextAccessError(
        `this function has '${this._access}' context access and cannot write the context`,
      )
    }
    delete this._data[key]
    delete this._writes[key]
    if (!this._deletes.includes(key)) this._deletes.push(key)
  }

  keys() {
    if (!this.readable) return []
    return Object.keys(this._data)
  }

  all() {
    if (!this.readable) {
      throw new ContextAccessError(
        `this function has '${this._access}' context access and cannot read the context`,
      )
    }
    return { ...this._data }
  }

  _drain() {
    const writes = this._writes
    const deletes = this._deletes
    this._writes = {}
    this._deletes = []
    return [writes, deletes]
  }
}

// ── invocation ───────────────────────────────────────────────────────────────

/** Accept every documented return shape and produce one response. */
function normalise(result) {
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    const status = result.statusCode ?? result.status_code
    if (status !== undefined && status !== null) {
      let body = result.body
      if (typeof body === 'string') {
        try {
          body = JSON.parse(body)
        } catch {
          /* a plain string body is a legitimate answer */
        }
      }
      const headers = {}
      for (const [key, value] of Object.entries(result.headers || {})) {
        headers[String(key)] = String(value)
      }
      return [Number(status), body ?? null, headers]
    }
  }
  return [200, result ?? null, {}]
}

async function runInvocation(payload) {
  if (!handler) {
    return {
      status_code: 500,
      body: { error: 'handler_not_loaded', message: loadError || 'unknown' },
      headers: {},
      logs: [{ level: 'ERROR', message: String(loadError || '').slice(0, 4000) }],
      error: 'handler failed to import',
      context_writes: {},
      context_deletes: [],
    }
  }

  const request = new Request(payload)
  const context = new Context(payload.context || {}, payload.ctx_access || 'rw', payload.session_id)

  // The same three collections the Python SDK exposes, as plain frozen objects
  // rather than a module import — a handler reads them off the context.
  context.env = Object.freeze({ ...(payload.env || {}) })
  context.secrets = Object.freeze({ ...(payload.secrets || {}) })
  context.services = Object.freeze({ ...(payload.services || {}) })

  logs = []
  const started = process.hrtime.bigint()
  let error = null
  let statusCode = 200
  let body = null
  let headers = {}

  try {
    const result = await handler(request, context)
    ;[statusCode, body, headers] = normalise(result)
  } catch (err) {
    error = `${(err && err.name) || 'Error'}: ${(err && err.message) || String(err)}`
    statusCode = 500
    body = { error: 'handler_error', message: (err && err.message) || String(err) }
    headers = {}
    for (const line of String((err && err.stack) || err).split('\n')) {
      if (logs.length < MAX_LOG_LINES) logs.push({ level: 'ERROR', message: line.slice(0, 4000) })
    }
  }

  const [writes, deletes] = context._drain()
  const collected = logs
  logs = null

  return {
    status_code: statusCode,
    body,
    headers,
    logs: collected,
    error,
    duration_ms: Number(process.hrtime.bigint() - started) / 1e6,
    context_writes: writes,
    context_deletes: deletes,
  }
}

// ── HTTP ─────────────────────────────────────────────────────────────────────

function send(res, status, payload) {
  const data = Buffer.from(JSON.stringify(payload))
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': data.length })
  res.end(data)
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url.startsWith('/healthz')) {
    // `fatal` tells the control plane not to keep waiting: the module threw on
    // import and no amount of patience will change that.
    send(res, handler ? 200 : 503, {
      ready: Boolean(handler),
      error: loadError,
      fatal: Boolean(loadError),
    })
    return
  }

  if (req.method === 'POST' && req.url.startsWith('/invoke')) {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', async () => {
      let payload
      try {
        payload = JSON.parse(Buffer.concat(chunks).toString() || '{}')
      } catch (err) {
        send(res, 400, { error: 'bad_request', message: String(err) })
        return
      }
      try {
        send(res, 200, await runInvocation(payload))
      } catch (err) {
        // The agent itself failed, not the handler. Say so plainly rather than
        // leaving the control plane on a socket that never answers.
        send(res, 500, {
          status_code: 500,
          body: { error: 'agent_error', message: String((err && err.message) || err) },
          headers: {},
          logs: [],
          error: String(err),
          context_writes: {},
          context_deletes: [],
        })
      }
    })
    return
  }

  send(res, 404, { error: 'not_found' })
})

captureConsole()
load().then(() => {
  server.listen(PORT, '0.0.0.0', () => real.log(`cubicle agent listening on ${PORT}`))
})

// Keep serving: a rejected promise somewhere in user code must not take the
// isolate down mid-request and turn one failed call into a cold start.
process.on('unhandledRejection', (reason) => real.error('unhandled rejection:', reason))
