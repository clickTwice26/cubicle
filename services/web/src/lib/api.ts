export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }

  get needsSetup() {
    return this.status === 409 && this.code === 'setup_required'
  }

  get unauthenticated() {
    return this.status === 401
  }
}

type Options = Omit<RequestInit, 'body'> & { body?: unknown; raw?: boolean }

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options

  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...rest,
  })

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('json')
    ? await response.json().catch(() => null)
    : await response.text()

  if (!response.ok) {
    const detail = (payload as { detail?: unknown })?.detail
    if (detail && typeof detail === 'object') {
      const structured = detail as { message?: string; code?: string }
      throw new ApiError(
        structured.message ?? 'Request failed.',
        response.status,
        structured.code,
      )
    }
    throw new ApiError(
      typeof detail === 'string'
        ? detail
        : typeof payload === 'string' && payload
          ? payload
          : `Request failed with ${response.status}.`,
      response.status,
    )
  }

  return (raw ? response : payload) as T
}

export const api = {
  get: <T>(path: string, init?: Options) => request<T>(path, { ...init, method: 'GET' }),
  post: <T>(path: string, body?: unknown, init?: Options) =>
    request<T>(path, { ...init, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, init?: Options) =>
    request<T>(path, { ...init, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, init?: Options) =>
    request<T>(path, { ...init, method: 'PUT', body }),
  delete: <T>(path: string, init?: Options) => request<T>(path, { ...init, method: 'DELETE' }),
}

/** Subscribe to a server-sent event stream, returning an unsubscribe function. */
export function subscribe<T>(
  path: string,
  onMessage: (payload: T) => void,
  onError?: (error: Event) => void,
): () => void {
  const source = new EventSource(path, { withCredentials: true })
  source.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data) as T)
    } catch {
      /* a keep-alive comment, or a partial frame — nothing to do */
    }
  }
  if (onError) source.onerror = onError
  return () => source.close()
}
