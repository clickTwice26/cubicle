/**
 * The Cloudflare Turnstile widget on the sign-in form.
 *
 * The script is loaded on demand rather than in index.html, so an instance
 * that has not turned this on never talks to Cloudflare at all. That matters
 * for a platform whose whole premise is that it runs on your own hardware and
 * does not call home: the third-party request appears only once an operator
 * has asked for it.
 *
 * The site key arrives at runtime from /api/setup/status, which means turning
 * Turnstile on takes effect on the next page load. Nothing is baked into the
 * bundle at build time and no rebuild is needed to change a key.
 */
import { useEffect, useRef } from 'react'

const SCRIPT_ID = 'cf-turnstile-script'
const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string
      remove: (id: string) => void
      reset: (id?: string) => void
    }
  }
}

/** Load the Turnstile script once, and resolve when it is ready to render. */
function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()

  const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('script failed')))
    })
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.id = SCRIPT_ID
    script.src = SCRIPT_SRC
    script.async = true
    script.defer = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('script failed'))
    document.head.appendChild(script)
  })
}

export interface TurnstileProps {
  siteKey: string
  /** Called with the token when the challenge passes, and with '' when it does not. */
  onToken: (token: string) => void
  /** Bumping this re-runs the challenge. A token is single use, so a failed sign-in needs a new one. */
  resetKey?: number
  theme?: 'auto' | 'light' | 'dark'
}

export function Turnstile({ siteKey, onToken, resetKey = 0, theme = 'auto' }: TurnstileProps) {
  const host = useRef<HTMLDivElement>(null)
  // Held in a ref rather than state: re-rendering on every token would tear
  // down the widget that just produced it.
  const widgetId = useRef<string | null>(null)
  const emit = useRef(onToken)
  emit.current = onToken

  useEffect(() => {
    let cancelled = false

    void loadScript()
      .then(() => {
        if (cancelled || !host.current || !window.turnstile) return
        if (widgetId.current) {
          window.turnstile.remove(widgetId.current)
          widgetId.current = null
        }
        widgetId.current = window.turnstile.render(host.current, {
          sitekey: siteKey,
          theme,
          callback: (token: string) => emit.current(token),
          // Any of these means the page does not hold a usable token any more.
          // Clearing it keeps the submit button in step with reality.
          'expired-callback': () => emit.current(''),
          'timeout-callback': () => emit.current(''),
          'error-callback': () => emit.current(''),
        })
      })
      .catch(() => {
        // Cloudflare is unreachable. Say nothing here: the sign-in form
        // reports it, because it is the thing that knows a token is required.
        if (!cancelled) emit.current('')
      })

    return () => {
      cancelled = true
      if (widgetId.current && window.turnstile) {
        window.turnstile.remove(widgetId.current)
        widgetId.current = null
      }
    }
  }, [siteKey, theme, resetKey])

  return <div ref={host} className="flex justify-center" />
}
