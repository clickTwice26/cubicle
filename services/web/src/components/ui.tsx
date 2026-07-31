import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react'
import { Bolt, Check, Copy, Trash, X } from './Icons'

export const cx = (...parts: (string | false | null | undefined)[]) =>
  parts.filter(Boolean).join(' ')

// ── button ───────────────────────────────────────────────────────────────────

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: ReactNode
  loading?: boolean
}

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 rounded-[9px] font-semibold transition ' +
  'disabled:cursor-not-allowed disabled:opacity-55 whitespace-nowrap'

const VARIANTS = {
  primary: 'bg-accent text-accent-ink border-0 hover:brightness-[1.06]',
  secondary: 'bg-panel text-ink border border-line-strong hover:bg-panel-2',
  ghost: 'bg-transparent text-ink-2 border border-line hover:bg-panel-2',
  danger: 'bg-transparent text-err border border-line-strong hover:bg-err-bg',
} as const

const SIZES = {
  sm: 'h-8 px-3 text-[12.5px]',
  md: 'h-9 px-3.5 text-[13px]',
  lg: 'h-[42px] px-5 text-sm',
} as const

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  loading,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cx(BUTTON_BASE, VARIANTS[variant], SIZES[size], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Spinner size={14} /> : icon}
      {children}
    </button>
  )
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={cx(
        'grid h-8 w-8 place-items-center rounded-lg border border-line bg-transparent',
        'text-ink-2 transition hover:bg-panel-2 hover:text-ink',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="animate-spin-slow inline-block rounded-full border-2 border-current border-t-transparent"
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  )
}

// ── surfaces ─────────────────────────────────────────────────────────────────

export function Card({
  className,
  children,
  ...rest
}: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx('rounded-xl border border-line bg-panel', className)} {...rest}>
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cx(
        'flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4',
        className,
      )}
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold">{title}</div>
        {subtitle ? <div className="mt-0.5 text-[12.5px] text-ink-2">{subtitle}</div> : null}
      </div>
      {action}
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="m-0 text-2xl tracking-[-0.02em]">{title}</h1>
        {subtitle ? <p className="mt-1.5 mb-0 text-sm text-ink-2">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
  dashed = true,
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
  dashed?: boolean
}) {
  return (
    <div
      className={cx(
        'rounded-xl bg-panel p-10 text-center',
        dashed ? 'border border-dashed border-line-strong' : 'border border-line',
      )}
    >
      <div className="text-[15px] font-semibold">{title}</div>
      {body ? <div className="mt-1.5 text-[13.5px] text-ink-2">{body}</div> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  )
}

export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: React.CSSProperties
}) {
  return <div className={cx('skeleton', className)} style={style} />
}

// ── inputs ───────────────────────────────────────────────────────────────────

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: string
  hint?: ReactNode
  mono?: boolean
  error?: string | null
}

export function Field({ label, hint, mono = true, error, className, ...rest }: FieldProps) {
  const id = useId()
  return (
    <div className={className}>
      {label ? (
        <label htmlFor={id} className="mb-1.5 block text-[12.5px] text-ink-2">
          {label}
        </label>
      ) : null}
      <input
        id={id}
        className={cx(
          'h-10 w-full rounded-[9px] border bg-bg px-3 text-sm text-ink outline-none transition',
          'placeholder:text-ink-3 focus:border-accent',
          error ? 'border-err' : 'border-line-strong',
          mono && 'font-mono text-[13.5px]',
        )}
        aria-invalid={Boolean(error)}
        {...rest}
      />
      {error ? (
        <div className="mt-1.5 text-xs text-err">{error}</div>
      ) : hint ? (
        <div className="mt-1.5 font-mono text-xs text-ink-3">{hint}</div>
      ) : null}
    </div>
  )
}

export function Chip({
  active,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      type="button"
      className={cx(
        'rounded-lg border px-3 py-[7px] text-[12.5px] font-medium transition',
        active
          ? 'border-accent bg-accent-soft text-ink'
          : 'border-line bg-panel text-ink-2 hover:border-line-strong',
        className,
      )}
      aria-pressed={active}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Segment({
  active,
  title,
  subtitle,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean
  title: string
  subtitle?: string
}) {
  return (
    <button
      type="button"
      className={cx(
        'rounded-[10px] border px-3.5 py-3 text-left transition',
        active
          ? 'border-[1.5px] border-accent bg-accent-soft'
          : 'border border-line-strong bg-bg hover:border-line',
      )}
      aria-pressed={active}
      {...rest}
    >
      <div className="text-sm font-semibold">{title}</div>
      {subtitle ? <div className="mt-0.5 text-xs text-ink-2">{subtitle}</div> : null}
    </button>
  )
}

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: ReactNode
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2.5 text-left"
    >
      <span
        className={cx(
          'grid h-[18px] w-[18px] flex-none place-items-center rounded-[5px] border transition',
          checked ? 'border-accent bg-accent text-accent-ink' : 'border-line-strong',
        )}
      >
        {checked ? <Check size={11} /> : null}
      </span>
      <span className="text-[13px] text-ink-2">{label}</span>
    </button>
  )
}

// ── tabs ─────────────────────────────────────────────────────────────────────

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  className,
}: {
  value: T
  onChange: (next: T) => void
  tabs: { value: T; label: string }[]
  className?: string
}) {
  return (
    <div className={cx('flex gap-1 border-b border-line', className)} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={cx(
            'mr-3 h-[38px] border-b-2 bg-transparent px-1 text-[13.5px] font-semibold transition',
            value === tab.value
              ? 'border-accent text-ink'
              : 'border-transparent text-ink-2 hover:text-ink',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

// ── data display ─────────────────────────────────────────────────────────────

export function StatusDot({ tone }: { tone: 'ok' | 'warn' | 'err' | 'idle' | 'info' }) {
  const colour = {
    ok: 'var(--ok)',
    warn: 'var(--warn)',
    err: 'var(--err)',
    info: 'var(--info)',
    idle: 'var(--text-3)',
  }[tone]
  return (
    <span
      className="inline-block h-[7px] w-[7px] flex-none rounded-full"
      style={{ background: colour }}
    />
  )
}

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: 'neutral' | 'accent' | 'ok' | 'warn' | 'err' | 'info'
  children: ReactNode
  className?: string
}) {
  const tones = {
    neutral: 'border-line text-ink-2',
    accent: 'border-accent bg-accent-soft text-ink',
    ok: 'border-ok text-ok',
    warn: 'border-warn text-warn',
    err: 'border-err text-err',
    info: 'border-info text-info',
  } as const
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px]',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

const METHOD_TONE: Record<string, 'info' | 'ok' | 'warn' | 'err' | 'neutral'> = {
  GET: 'info',
  POST: 'ok',
  PUT: 'warn',
  PATCH: 'warn',
  DELETE: 'err',
}

export function MethodBadge({ method }: { method: string }) {
  return (
    <Badge tone={METHOD_TONE[method] ?? 'neutral'} className="font-semibold tracking-[0.03em]">
      {method}
    </Badge>
  )
}

export function Meter({
  value,
  tone = 'accent',
  className,
}: {
  value: number
  tone?: 'accent' | 'warn' | 'err' | 'ok'
  className?: string
}) {
  const colour = {
    accent: 'var(--accent)',
    warn: 'var(--warn)',
    err: 'var(--err)',
    ok: 'var(--ok)',
  }[tone]
  return (
    <div className={cx('h-1.5 overflow-hidden rounded-full bg-panel-3', className)}>
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: colour }}
      />
    </div>
  )
}

export function CopyButton({
  value,
  label = 'Copy',
  className,
}: {
  value: string
  label?: string
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          timer.current = window.setTimeout(() => setCopied(false), 1600)
        } catch {
          /* clipboard denied — the value is on screen either way */
        }
      }}
      className={cx(
        'inline-flex flex-none items-center gap-1.5 text-xs text-ink-3 transition hover:text-ink',
        className,
      )}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? 'Copied' : label}
    </button>
  )
}

export function CodeBlock({
  children,
  className,
  filename,
  copyValue,
}: {
  children: ReactNode
  className?: string
  filename?: string
  copyValue?: string
}) {
  return (
    <div className={cx('overflow-hidden rounded-xl border border-line bg-panel', className)}>
      {filename ? (
        <div className="flex items-center justify-between border-b border-line px-3.5 py-2 font-mono text-[11.5px] text-ink-3">
          <span>{filename}</span>
          {copyValue ? <CopyButton value={copyValue} /> : null}
        </div>
      ) : null}
      <pre className="m-0 overflow-x-auto px-4 py-4 font-mono text-[13px] leading-[1.75] text-ink">
        {children}
      </pre>
    </div>
  )
}

export function KeyValue({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 text-[13.5px]">
      <span className="text-ink-2">{label}</span>
      <span className="truncate font-mono">{value}</span>
    </div>
  )
}

// ── modal ────────────────────────────────────────────────────────────────────

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = 460,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  width?: number
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="animate-rise w-full overflow-hidden rounded-2xl border border-line-strong bg-panel shadow-2xl"
        style={{ maxWidth: width }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="text-[15px] font-semibold">{title}</div>
          <IconButton label="Close" onClick={onClose} className="h-7 w-7 border-0">
            <X size={15} />
          </IconButton>
        </div>
        <div className="px-5 py-5">{children}</div>
        {footer ? (
          <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-4">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/**
 * A destructive action that needs a second click.
 *
 * `as="button"` renders it as a real, outlined button — use that anywhere the
 * action sits in open space, where a bare link reads as a caption rather than
 * something you can press. The default text style stays for dense table rows,
 * where a row of outlined buttons would drown the data.
 */
export function ConfirmButton({
  onConfirm,
  label,
  confirmLabel = 'Click again to confirm',
  className,
  as = 'text',
  size = 'sm',
  hint,
}: {
  onConfirm: () => void
  label: string
  confirmLabel?: string
  className?: string
  as?: 'text' | 'button'
  size?: 'sm' | 'md'
  /** Shown on hover, and to screen readers, in button mode. */
  hint?: string
}) {
  const [armed, setArmed] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const fire = () => {
    if (armed) {
      window.clearTimeout(timer.current)
      setArmed(false)
      onConfirm()
      return
    }
    setArmed(true)
    timer.current = window.setTimeout(() => setArmed(false), 4000)
  }

  if (as === 'button') {
    return (
      <Button
        variant="danger"
        size={size}
        onClick={fire}
        title={hint}
        aria-label={hint ? `${label} — ${hint}` : label}
        className={cx(armed && 'border-err bg-err-bg font-semibold', className)}
        icon={<Trash size={13} />}
      >
        {armed ? confirmLabel : label}
      </Button>
    )
  }

  return (
    <button
      type="button"
      className={cx(
        'text-[12.5px] transition',
        armed ? 'font-semibold text-err' : 'text-err hover:underline',
        className,
      )}
      onClick={fire}
    >
      {armed ? confirmLabel : label}
    </button>
  )
}

// ── toasts ───────────────────────────────────────────────────────────────────

type Toast = { id: number; message: string; tone: 'ok' | 'err' | 'info'; meta?: string }

const ToastContext = createContext<{
  push: (message: string, tone?: Toast['tone'], meta?: string) => void
}>({ push: () => {} })

export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, tone: Toast['tone'] = 'ok', meta?: string) => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message, tone, meta }])
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      tone === 'err' ? 6000 : 3200,
    )
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className="animate-rise pointer-events-auto flex items-center gap-3 rounded-xl border border-line-strong bg-panel px-4 py-3 shadow-2xl"
          >
            <span
              className="grid h-[22px] w-[22px] place-items-center rounded-md"
              style={{
                background: toast.tone === 'err' ? 'var(--err)' : 'var(--accent)',
                color: toast.tone === 'err' ? '#fff' : 'var(--accent-ink)',
              }}
            >
              {toast.tone === 'err' ? <X size={12} /> : <Bolt size={12} />}
            </span>
            <span className="text-[13.5px] font-semibold">{toast.message}</span>
            {toast.meta ? (
              <span className="font-mono text-xs text-ok">{toast.meta}</span>
            ) : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
