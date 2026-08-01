import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bolt, Check, ChevronDown, X } from './Icons'
import { Badge, Button, Chip, cx, useToast } from './ui'
import { useAiStatus, useGenerate, type ContextSent, type Generation } from '../lib/ai'

/**
 * Cubicle AI, in the editor.
 *
 * The panel never writes to the cluster: a generation lands in the same unsaved
 * draft your own typing does, so the existing Save & deploy — and the build that
 * follows it — stays the only path to a running version. Nothing here can
 * deploy behind you.
 *
 * It also shows what was sent. The assistant is the one feature that talks to
 * something off the machine, so "what did it see" should be readable rather
 * than promised.
 */
export function AiPanel({
  functionId,
  currentCode,
  requirements,
  sessionId,
  onApply,
}: {
  functionId: string
  currentCode: string
  requirements: string
  sessionId: string
  /** Hands the generated file back as an unsaved draft. */
  onApply: (code: string, requirements: string[]) => void
}) {
  const toast = useToast()
  const { data: status } = useAiStatus()
  const generate = useGenerate()

  const [open, setOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState<'edit' | 'write'>('edit')
  const [result, setResult] = useState<Generation | null>(null)

  const run = () => {
    if (!prompt.trim()) return
    generate.mutate(
      {
        function_id: functionId,
        prompt: prompt.trim(),
        mode,
        code: currentCode,
        requirements,
        session_id: sessionId,
      },
      {
        onSuccess: setResult,
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-2.5">
        <Button size="sm" icon={<Bolt size={13} />} onClick={() => setOpen(true)}>
          Cubicle AI
        </Button>
        <span className="text-[12.5px] text-ink-3">
          {status?.enabled
            ? `Describe the change and it writes the handler · ${status.model}`
            : 'Not configured yet — an admin adds a key under Settings'}
        </span>
      </div>
    )
  }

  return (
    <div className="border-b border-line bg-panel-2">
      <div className="flex items-center gap-2.5 px-5 pt-3.5">
        <Bolt size={14} className="text-accent" />
        <span className="text-[13px] font-semibold">Cubicle AI</span>
        {status?.enabled ? (
          <Badge>{status.model}</Badge>
        ) : (
          <Badge tone="warn">not configured</Badge>
        )}
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close"
          className="ml-auto text-ink-3 transition hover:text-ink"
        >
          <X size={15} />
        </button>
      </div>

      {status && !status.enabled ? (
        <div className="px-5 pt-2.5 pb-4 text-[13px] leading-relaxed text-ink-2">
          The assistant needs a provider key before it can write anything. An admin adds one
          under{' '}
          <Link to="/console/settings" className="font-semibold text-ink underline">
            Settings → Cubicle AI
          </Link>
          . Nothing is sent anywhere until then.
        </div>
      ) : (
        <>
          <div className="px-5 pt-3">
            <textarea
              value={prompt}
              spellCheck={false}
              placeholder={
                mode === 'edit'
                  ? 'Validate the body, write the order to Postgres, and put the order id on the context…'
                  : 'A webhook that verifies a signature header and stores the payload…'
              }
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') run()
              }}
              className="h-[76px] w-full resize-y rounded-[9px] border border-line-strong bg-bg p-3 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-3 focus:border-accent"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 px-5 py-3">
            <Chip active={mode === 'edit'} onClick={() => setMode('edit')}>
              edit this file
            </Chip>
            <Chip active={mode === 'write'} onClick={() => setMode('write')}>
              write from scratch
            </Chip>
            <span className="text-[12px] text-ink-3">⌘↵ to run</span>
            <Button
              size="sm"
              variant="primary"
              className="ml-auto"
              loading={generate.isPending}
              disabled={!prompt.trim()}
              onClick={run}
            >
              Generate
            </Button>
          </div>
        </>
      )}

      {result ? (
        <div className="border-t border-line px-5 py-4">
          <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
            <span className="text-[13px] font-semibold">Proposed handler.py</span>
            <span className="font-mono text-[11.5px] text-ink-3">
              {result.model} · {result.usage.prompt_tokens + result.usage.completion_tokens}{' '}
              tokens · {(result.duration_ms / 1000).toFixed(1)}s
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                icon={<Check size={13} />}
                onClick={() => {
                  onApply(result.code, result.requirements)
                  setResult(null)
                  toast.push('Applied as an unsaved draft — review, then Save & deploy', 'info')
                }}
              >
                Apply to editor
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setResult(null)}>
                Discard
              </Button>
            </div>
          </div>

          {result.notes ? (
            <p className="mt-0 mb-3 text-[13px] leading-relaxed text-ink-2">{result.notes}</p>
          ) : null}

          {result.requirements.length ? (
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[12.5px]">
              <span className="text-ink-3">requirements.txt:</span>
              {result.requirements.map((line) => (
                <span
                  key={line}
                  className="rounded-md border border-line bg-bg px-2 py-0.5 font-mono text-[11.5px]"
                >
                  {line}
                </span>
              ))}
            </div>
          ) : null}

          <pre className="m-0 max-h-[340px] overflow-auto rounded-[10px] border border-line bg-bg px-4 py-3.5 font-mono text-[12.5px] leading-[1.7] whitespace-pre-wrap text-ink">
            {result.code}
          </pre>

          <ContextDisclosure sent={result.context_sent} />
        </div>
      ) : null}
    </div>
  )
}

/** Exactly what was sent, spelled out — including what deliberately was not. */
function ContextDisclosure({ sent }: { sent: ContextSent }) {
  const [open, setOpen] = useState(false)
  const services = sent.services.filter((s) => s.available).map((s) => s.kind)

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1.5 text-[12.5px] text-ink-3 transition hover:text-ink"
      >
        <ChevronDown size={13} className={cx('transition', open && 'rotate-180')} />
        What the model was given
      </button>
      {open ? (
        <div className="mt-2.5 grid gap-2 rounded-[10px] border border-line bg-bg px-3.5 py-3 text-[12.5px] text-ink-2">
          <Row label="Function">
            {sent.function.method} /{sent.function.namespace}/{sent.function.name} ·{' '}
            {sent.function.runtime} · context {sent.function.context_access} ·{' '}
            {sent.function.timeout_seconds}s · {sent.function.memory_mb} MB
          </Row>
          <Row label="Env keys">
            {sent.env_keys.length
              ? sent.env_keys.map((entry) => entry.key).join(', ')
              : 'none defined'}
          </Row>
          {sent.secret_keys.length ? (
            <Row label="Secret keys">{sent.secret_keys.join(', ')}</Row>
          ) : null}
          <Row label="Context">
            {sent.context.length
              ? sent.context.map((entry) => `${entry.key} (${entry.type})`).join(', ')
              : 'empty this session'}
          </Row>
          <Row label="Services">{services.length ? services.join(', ') : 'none running'}</Row>
          {sent.siblings.length ? (
            <Row label="Namespace">
              {sent.siblings.map((entry) => `${entry.method} ${entry.path}`).join(', ')}
            </Row>
          ) : null}
          <Row label="Never sent">
            The values behind those env and secret keys. Names are all the model needs.
          </Row>
        </div>
      ) : null}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5 sm:grid-cols-[110px_minmax(0,1fr)]">
      <span className="text-[11.5px] font-bold tracking-[0.04em] text-ink-3 uppercase">
        {label}
      </span>
      <span className="min-w-0 font-mono text-[11.5px] break-words">{children}</span>
    </div>
  )
}
