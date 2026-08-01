import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bolt, Check, ChevronDown, X } from './Icons'
import { Badge, Button, Chip, cx, useToast } from './ui'
import { useAiStatus, useGenerate, type ContextSent, type Generation } from '../lib/ai'
import { collapse, diffLines, diffStats } from '../lib/diff'

/**
 * Cubicle AI, as a conversation beside the editor.
 *
 * The sidebar never writes to the cluster. A generation lands in the same
 * unsaved draft your own typing does, so Save & deploy — and the build behind
 * it — stays the only path to a running version. Nothing here deploys behind
 * you, and nothing applies without you saying so.
 *
 * Each turn also carries what was sent. The assistant is the one feature that
 * talks to something off this machine, so "what did it see" is readable rather
 * than promised.
 */

export interface Turn {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** Present on assistant turns that produced a file. */
  result?: Generation
  applied?: boolean
  failed?: boolean
  /** The editor buffer at the moment Apply ran, so the diff is what changed. */
  appliedFrom?: string
}

let seq = 0
const nextId = () => `t${(seq += 1)}`

const WIDTH_KEY = 'cubicle-ai-width'
const MIN_WIDTH = 340
const DEFAULT_WIDTH = 520

/** Never so wide that the editor it is discussing has nowhere left to go. */
function clampWidth(px: number): number {
  const room = typeof window === 'undefined' ? 1280 : window.innerWidth
  return Math.max(MIN_WIDTH, Math.min(px, Math.max(MIN_WIDTH, room - 320)))
}

/**
 * Width as a dragged, remembered preference.
 *
 * A diff needs horizontal room and a chat does not, so the right width depends
 * on what you are doing with it — which makes it yours to set rather than ours
 * to guess.
 */
function useResizable() {
  const [width, setWidth] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(WIDTH_KEY))
      return stored ? clampWidth(stored) : DEFAULT_WIDTH
    } catch {
      return DEFAULT_WIDTH
    }
  })
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (!dragging) return
    // Pointer events on the window, not the handle: the cursor routinely
    // outruns a 6px target during a fast drag.
    const move = (event: PointerEvent) =>
      setWidth(clampWidth(window.innerWidth - event.clientX))
    const stop = () => setDragging(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    // Stops the editor selecting text while the drag crosses it.
    const previous = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.style.userSelect = previous
      document.body.style.cursor = ''
    }
  }, [dragging])

  useEffect(() => {
    if (dragging) return
    try {
      localStorage.setItem(WIDTH_KEY, String(width))
    } catch {
      /* private browsing — the width just will not persist */
    }
  }, [width, dragging])

  // A window that shrinks below the stored width should not push the editor
  // off the screen.
  useEffect(() => {
    const onResize = () => setWidth((current) => clampWidth(current))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return {
    width,
    dragging,
    startDrag: () => setDragging(true),
    reset: () => setWidth(DEFAULT_WIDTH),
  }
}

export function AiSidebar({
  open,
  onClose,
  functionId,
  currentCode,
  requirements,
  sessionId,
  onApply,
}: {
  open: boolean
  onClose: () => void
  functionId: string
  currentCode: string
  requirements: string
  sessionId: string
  onApply: (code: string, requirements: string[]) => void
}) {
  const toast = useToast()
  const { data: status } = useAiStatus()
  const generate = useGenerate()

  const [turns, setTurns] = useState<Turn[]>([])
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState<'edit' | 'write'>('edit')
  const transcript = useRef<HTMLDivElement>(null)
  const { width, dragging, startDrag, reset } = useResizable()

  // A new turn should be visible without scrolling for it.
  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight, behavior: 'smooth' })
  }, [turns, generate.isPending])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const send = () => {
    const text = prompt.trim()
    if (!text || generate.isPending) return
    setPrompt('')
    setTurns((current) => [...current, { id: nextId(), role: 'user', text }])

    generate.mutate(
      {
        function_id: functionId,
        prompt: text,
        mode,
        code: currentCode,
        requirements,
        session_id: sessionId,
        // Only what was said, not the code: the current buffer is sent
        // separately and replaying old files would waste the context window.
        history: turns.map((turn) => ({
          role: turn.role,
          content: turn.role === 'assistant' ? (turn.result?.notes ?? turn.text) : turn.text,
        })),
      },
      {
        onSuccess: (result) =>
          setTurns((current) => [
            ...current,
            {
              id: nextId(),
              role: 'assistant',
              text: result.notes || 'Rewrote handler.py.',
              result,
            },
          ]),
        onError: (error) =>
          setTurns((current) => [
            ...current,
            { id: nextId(), role: 'assistant', text: error.message, failed: true },
          ]),
      },
    )
  }

  const apply = (turn: Turn) => {
    if (!turn.result) return
    // Captured before onApply, because after it the buffer is the new file and
    // there is nothing left to compare against.
    const from = currentCode
    onApply(turn.result.code, turn.result.requirements)
    setTurns((current) =>
      current.map((t) => (t.id === turn.id ? { ...t, applied: true, appliedFrom: from } : t)),
    )
    toast.push('Applied to the editor — deploy when you are ready')
  }

  return (
    <>
      {/* Dims the editor without unmounting it, so the draft survives. */}
      <div
        aria-hidden
        onClick={onClose}
        className={cx(
          'fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px] transition-opacity duration-300',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      <aside
        aria-label="Cubicle AI"
        style={{ ['--ai-width' as string]: `${width}px` }}
        className={cx(
          // Full width on a phone; from sm up it is whatever you dragged it to.
          'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-line bg-panel shadow-2xl',
          'sm:w-(--ai-width)',
          dragging ? '' : 'transition-transform duration-300 ease-out',
          open ? 'translate-x-0' : 'pointer-events-none translate-x-full',
        )}
      >
        {/* The grab handle. Hidden on a phone, where the panel is full width
            and there is nothing to trade against. */}
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize"
          title="Drag to resize · double-click to reset"
          onPointerDown={(event) => {
            event.preventDefault()
            startDrag()
          }}
          onDoubleClick={reset}
          className={cx(
            'group absolute inset-y-0 left-0 z-10 hidden w-2 -translate-x-1/2 cursor-col-resize sm:block',
          )}
        >
          <span
            className={cx(
              'absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 rounded-full transition-colors duration-150',
              dragging ? 'bg-accent' : 'bg-transparent group-hover:bg-accent-soft',
            )}
          />
          <span
            className={cx(
              'absolute top-1/2 left-1/2 h-9 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors duration-150',
              dragging ? 'bg-accent' : 'bg-line-strong group-hover:bg-accent',
            )}
          />
        </div>
        <header className="flex flex-none flex-wrap items-center gap-2.5 border-b border-line px-4 py-3.5">
          <Bolt size={15} className="text-accent" />
          <span className="text-[13.5px] font-semibold">Cubicle AI</span>
          {status?.enabled ? (
            <Badge>{status.model}</Badge>
          ) : (
            <Badge tone="warn">not configured</Badge>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto grid h-7 w-7 place-items-center rounded-lg text-ink-3 transition hover:bg-panel-2 hover:text-ink"
          >
            <X size={15} />
          </button>
        </header>

        {status && !status.enabled ? (
          <div className="px-4 py-5 text-[13px] leading-relaxed text-ink-2">
            The assistant needs a provider key before it can write anything. An admin adds one
            under{' '}
            <Link to="/console/settings" className="font-semibold text-ink underline">
              Settings → Cubicle AI
            </Link>
            . Nothing is sent anywhere until then.
          </div>
        ) : (
          <>
            <div
              ref={transcript}
              className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-4 py-4"
            >
              {turns.length === 0 ? (
                <Empty mode={mode} />
              ) : (
                <div className="grid min-w-0 gap-3">
                  {turns.map((turn) => (
                    <Message key={turn.id} turn={turn} onApply={() => apply(turn)} />
                  ))}
                </div>
              )}
              {generate.isPending ? <Working /> : null}
            </div>

            <div className="flex-none border-t border-line px-4 py-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Chip active={mode === 'edit'} onClick={() => setMode('edit')}>
                  edit this file
                </Chip>
                <Chip active={mode === 'write'} onClick={() => setMode('write')}>
                  write from scratch
                </Chip>
                {turns.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setTurns([])}
                    className="ml-auto text-[12px] text-ink-3 transition hover:text-ink"
                  >
                    Clear
                  </button>
                ) : null}
              </div>

              <textarea
                value={prompt}
                spellCheck={false}
                rows={3}
                placeholder={
                  mode === 'edit'
                    ? 'Validate the body and write the order to Postgres…'
                    : 'A webhook that verifies a signature header and stores the payload…'
                }
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') send()
                }}
                className="w-full resize-y rounded-[9px] border border-line-strong bg-bg p-2.5 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-3 focus:border-accent"
              />

              <div className="mt-2 flex items-center gap-2">
                <span className="text-[11.5px] text-ink-3">⌘↵ to send</span>
                <Button
                  size="sm"
                  variant="primary"
                  className="ml-auto"
                  loading={generate.isPending}
                  disabled={!prompt.trim()}
                  onClick={send}
                >
                  Send
                </Button>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  )
}

/**
 * The wait, with something to read.
 *
 * A single frozen "writing…" makes a six-second round trip feel like a hang.
 * These are moods rather than a progress bar — the client cannot see the
 * provider's internal stages, so nothing here claims a step has finished. It
 * only says the request is still out.
 */
const WAITING = [
  'Reading your handler',
  'Thinking it through',
  'Weighing the edge cases',
  'Consulting the runtime brief',
  'Choosing the shape',
  'Writing the handler',
  'Checking the imports',
  'Pinning what it needs',
  'Reading it back',
  'Tidying the edges',
  'Nearly there',
]

function Working() {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    // Walks forward and then holds on the last one: cycling back to "Reading
    // your handler" after twenty seconds would read as a stall.
    const timer = window.setInterval(
      () => setIndex((n) => Math.min(n + 1, WAITING.length - 1)),
      2100,
    )
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="animate-turn-in mt-3 mr-4 flex items-center gap-2.5 rounded-xl rounded-bl-[4px] border border-line bg-panel-2 px-3.5 py-2.5">
      <span className="flex flex-none items-end gap-[3px] pb-[3px]">
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="animate-dot h-[5px] w-[5px] rounded-full bg-accent"
            style={{ animationDelay: `${dot * 140}ms` }}
          />
        ))}
      </span>
      {/* Keyed so each word replays the fade rather than swapping in place. */}
      <span key={index} className="animate-word text-[12.5px] text-ink-2">
        {WAITING[index]}…
      </span>
    </div>
  )
}

function Empty({ mode }: { mode: 'edit' | 'write' }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-4 py-6 text-[12.5px] leading-relaxed text-ink-3">
      Describe what the handler should do and it writes one.
      <div className="mt-2.5 text-ink-2">
        {mode === 'edit'
          ? 'Editing what is open in the editor, including changes you have not deployed.'
          : 'Starting from nothing — the current file is not sent.'}
      </div>
      <div className="mt-2.5">
        Nothing it produces is deployed. It lands as an unsaved draft and you deploy it
        yourself.
      </div>
    </div>
  )
}

function Message({ turn, onApply }: { turn: Turn; onApply: () => void }) {
  if (turn.role === 'user') {
    return (
      <div className="animate-turn-in ml-4 min-w-0 rounded-xl rounded-br-[4px] border border-accent bg-accent-soft px-3.5 py-2.5 text-[13px] leading-relaxed [overflow-wrap:anywhere]">
        {turn.text}
      </div>
    )
  }

  return (
    <div
      className={cx(
        'animate-turn-in mr-4 min-w-0 rounded-xl rounded-bl-[4px] border px-3.5 py-2.5 text-[13px] leading-relaxed',
        turn.failed ? 'border-err bg-err-bg' : 'border-line bg-panel-2',
      )}
    >
      <div className={cx('[overflow-wrap:anywhere]', turn.failed ? 'text-ink' : 'text-ink-2')}>
        {turn.text}
      </div>

      {turn.result ? (
        <>
          {turn.result.requirements.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {turn.result.requirements.map((line) => (
                <span
                  key={line}
                  className="rounded-full border border-line bg-bg px-2 py-0.5 font-mono text-[11px] text-ink-2"
                >
                  {line}
                </span>
              ))}
            </div>
          ) : null}

          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={turn.applied ? 'ghost' : 'primary'}
              icon={turn.applied ? <Check size={12} /> : undefined}
              onClick={onApply}
            >
              {turn.applied ? 'Applied' : 'Apply to editor'}
            </Button>
            <span className="font-mono text-[11px] text-ink-3">
              {Math.round(turn.result.duration_ms)}ms ·{' '}
              {turn.result.usage.prompt_tokens + turn.result.usage.completion_tokens} tokens
            </span>
          </div>

          {turn.applied && turn.appliedFrom !== undefined ? (
            <Diff before={turn.appliedFrom} after={turn.result.code} />
          ) : null}

          <Sent context={turn.result.context_sent} />
        </>
      ) : null}
    </div>
  )
}

/**
 * What the apply actually changed, as a unified diff.
 *
 * Shown after applying rather than before: until you apply, the interesting
 * question is what the assistant proposes, and afterwards it is what moved in
 * your file. Long runs of untouched lines are collapsed, because a one-function
 * rewrite in a long file should read as one change.
 */
function Diff({ before, after }: { before: string; after: string }) {
  const [open, setOpen] = useState(true)
  const lines = diffLines(before, after)
  const { added, removed } = diffStats(lines)

  if (added === 0 && removed === 0) {
    return (
      <div className="mt-2 border-t border-line pt-2 text-[11.5px] text-ink-3">
        Identical to what was already in the editor — nothing changed.
      </div>
    )
  }

  return (
    <div className="mt-2 border-t border-line pt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 text-[11.5px] text-ink-3 transition hover:text-ink"
      >
        <ChevronDown size={12} className={cx('transition', open && 'rotate-180')} />
        Changes
        <span className="ml-1 font-mono text-ok">+{added}</span>
        <span className="font-mono text-err">−{removed}</span>
      </button>

      {open ? (
        <div className="mt-2 max-w-full overflow-x-auto rounded-[8px] border border-line bg-bg">
          {collapse(lines).map((hunk, index) => (
            <div key={index}>
              {hunk.skipped > 0 ? (
                <div className="border-y border-line bg-panel-2 px-2 py-1 font-mono text-[10.5px] text-ink-3">
                  ⋯ {hunk.skipped} unchanged line{hunk.skipped === 1 ? '' : 's'}
                </div>
              ) : null}
              {hunk.lines.map((line, n) => (
                <div
                  key={n}
                  style={{ animationDelay: `${Math.min(n, 12) * 18}ms` }}
                  className={cx(
                    'animate-line-in flex w-max min-w-full gap-2 px-2 font-mono text-[11px] leading-[1.65] whitespace-pre',
                    line.kind === 'add' && 'bg-ok-bg',
                    line.kind === 'del' && 'bg-err-bg',
                  )}
                >
                  <span
                    className="w-[9px] flex-none select-none"
                    style={{
                      color:
                        line.kind === 'add'
                          ? 'var(--ok)'
                          : line.kind === 'del'
                            ? 'var(--err)'
                            : 'var(--text-3)',
                    }}
                  >
                    {line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}
                  </span>
                  <span className={line.kind === 'same' ? 'text-ink-3' : 'text-ink'}>
                    {line.text || ' '}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** What actually left the machine for this turn. */
function Sent({ context }: { context: ContextSent }) {
  const [open, setOpen] = useState(false)
  const counts = [
    `${context.env_keys.length} env key${context.env_keys.length === 1 ? '' : 's'}`,
    `${context.secret_keys.length} secret name${context.secret_keys.length === 1 ? '' : 's'}`,
    `${context.siblings.length} sibling${context.siblings.length === 1 ? '' : 's'}`,
  ]
  return (
    <div className="mt-2 border-t border-line pt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 text-[11.5px] text-ink-3 transition hover:text-ink"
      >
        <ChevronDown size={12} className={cx('transition', open && 'rotate-180')} />
        What was sent · {counts.join(' · ')}
      </button>
      {open ? (
        <div className="mt-2 grid gap-1.5 font-mono text-[11px] text-ink-3">
          <div>
            {context.function.namespace}/{context.function.name} · {context.function.method} ·{' '}
            {context.function.runtime}
          </div>
          {context.env_keys.length ? (
            <div className="break-all">
              names only: {context.env_keys.map((entry) => entry.key).join(', ')}
            </div>
          ) : null}
          {context.secret_keys.length ? (
            <div className="break-all">
              secrets, names only: {context.secret_keys.join(', ')}
            </div>
          ) : null}
          <div className="text-ink-2">Values of env and secrets are never sent.</div>
        </div>
      ) : null}
    </div>
  )
}
