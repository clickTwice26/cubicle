import { useState } from 'react'
import { Plus } from '../components/Icons'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  CodeBlock,
  ConfirmButton,
  CopyButton,
  EmptyState,
  Field,
  PAGE,
  PageHeader,
  Skeleton,
  useToast,
} from '../components/ui'
import { revealEnvVar, useDeleteEnvVar, useEnvVars, useSaveEnvVar } from '../lib/hooks'
import { relativeTime } from '../lib/format'

const SNIPPET = `from cubicle_context import env

base = env.get("PAYMENTS_API_BASE")
key  = env.get("STRIPE_SECRET_KEY")        # decrypted in-process
pool = env.get_int("DB_POOL_SIZE", default=10)`

export default function GlobalEnv() {
  const toast = useToast()
  const { data: vars, isLoading } = useEnvVars()
  const save = useSaveEnvVar()
  const remove = useDeleteEnvVar()

  const [adding, setAdding] = useState(false)
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [secret, setSecret] = useState(false)
  const [revealed, setRevealed] = useState<Record<string, string>>({})

  const submit = () => {
    save.mutate(
      { key: key.trim(), value, is_secret: secret },
      {
        onSuccess: () => {
          toast.push(`${key.trim().toUpperCase()} saved`)
          setAdding(false)
          setKey('')
          setValue('')
          setSecret(false)
        },
        onError: (error) => toast.push(error.message, 'err'),
      },
    )
  }

  return (
    <div className={PAGE}>
      <PageHeader
        title="Global env"
        subtitle={
          <>
            One store per cluster. Any function in any namespace reads these at invocation with{' '}
            <span className="font-mono">env.get()</span> — no redeploy when a value changes.
          </>
        }
        action={
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setAdding(true)}>
            Add variable
          </Button>
        }
      />

      {adding ? (
        <Card className="mb-4.5 border-accent p-6">
          <div className="mb-4 text-[15px] font-semibold">New variable</div>
          <div className="grid gap-3.5 sm:grid-cols-[1fr_1.4fr]">
            <Field
              label="Key"
              autoFocus
              value={key}
              placeholder="PAYMENTS_API_BASE"
              onChange={(event) => setKey(event.target.value.toUpperCase())}
            />
            <Field
              label="Value"
              type={secret ? 'password' : 'text'}
              value={value}
              placeholder="https://payments.internal/v2"
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <div className="mt-4">
            <Checkbox
              checked={secret}
              onChange={setSecret}
              label="Store as secret — envelope-encrypted, masked in the console"
            />
          </div>
          <div className="mt-4.5 flex gap-2.5">
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!key.trim()}
              onClick={submit}
            >
              Save variable
            </Button>
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : vars && vars.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="hidden grid-cols-[1.1fr_1.6fr_90px_100px_120px] gap-3 border-b border-line px-5 py-3 text-[11.5px] font-semibold tracking-[0.04em] text-ink-3 uppercase md:grid">
            <span>Key</span>
            <span>Value</span>
            <span>Type</span>
            <span>Updated</span>
            <span />
          </div>
          {vars.map((item) => (
            <div
              key={item.key}
              className="grid grid-cols-1 items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0 md:grid-cols-[1.1fr_1.6fr_90px_100px_120px]"
            >
              <div className="truncate font-mono text-[13px] font-semibold">{item.key}</div>
              <div className="truncate font-mono text-[12.5px] text-ink-2">
                {revealed[item.key] ?? item.value}
              </div>
              <div>
                <Badge tone={item.is_secret ? 'warn' : 'neutral'}>
                  {item.is_secret ? 'secret' : 'plain'}
                </Badge>
              </div>
              <div className="text-[12.5px] text-ink-3">{relativeTime(item.updated_at)}</div>
              <div className="flex items-center justify-end gap-3">
                {item.is_secret ? (
                  <button
                    type="button"
                    className="text-xs text-ink-3 transition hover:text-ink"
                    onClick={async () => {
                      if (revealed[item.key]) {
                        setRevealed((current) => {
                          const next = { ...current }
                          delete next[item.key]
                          return next
                        })
                        return
                      }
                      try {
                        const full = await revealEnvVar(item.key)
                        setRevealed((current) => ({ ...current, [item.key]: full.value }))
                      } catch (error) {
                        toast.push((error as Error).message, 'err')
                      }
                    }}
                  >
                    {revealed[item.key] ? 'Hide' : 'Reveal'}
                  </button>
                ) : (
                  <CopyButton value={item.value} />
                )}
                <ConfirmButton
                  label="Delete"
                  confirmLabel="Confirm"
                  onConfirm={() =>
                    remove.mutate(item.key, { onSuccess: () => toast.push('Variable deleted') })
                  }
                />
              </div>
            </div>
          ))}
        </Card>
      ) : (
        <EmptyState
          title="No variables yet"
          body="Anything you add here is readable from every function on the cluster."
          action={
            <Button variant="primary" icon={<Plus size={15} />} onClick={() => setAdding(true)}>
              Add variable
            </Button>
          }
        />
      )}

      <Card className="mt-5 px-5 py-4.5">
        <div className="mb-1 text-[13.5px] font-semibold">Reading from a function</div>
        <div className="mb-3.5 text-[12.5px] text-ink-2">
          Values resolve at invocation time from the cluster store, not at build time.
        </div>
        <CodeBlock className="border-0 bg-transparent">
          <span className="text-ink-2">{SNIPPET}</span>
        </CodeBlock>
      </Card>
    </div>
  )
}
