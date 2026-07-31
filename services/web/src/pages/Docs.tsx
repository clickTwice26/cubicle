import { useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { Search } from '../components/Icons'
import { Button, cx } from '../components/ui'
import { useSetupStatus } from '../lib/hooks'
import { DOCS } from './docs/content'

export default function Docs() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const { data: status } = useSetupStatus()

  const page = DOCS.find((doc) => doc.id === slug) ?? DOCS[0]
  const index = DOCS.indexOf(page)
  const previous = DOCS[index - 1]
  const next = DOCS[index + 1]

  const groups = useMemo(() => {
    const seen: string[] = []
    for (const doc of DOCS) if (!seen.includes(doc.group)) seen.push(doc.group)
    return seen.map((group) => ({ group, items: DOCS.filter((doc) => doc.group === group) }))
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <header className="sticky top-0 z-30 border-b border-line backdrop-blur-[12px] [background:color-mix(in_srgb,var(--bg)_88%,transparent)]">
        <div className="mx-auto flex h-[60px] max-w-[1440px] items-center gap-6 px-5 sm:px-7">
          <Link to="/" className="flex flex-none items-center gap-2.5">
            <Logo size={26} />
            <span className="ml-1 border-l border-line pl-2.5 text-[13px] text-ink-3">
              Docs
            </span>
          </Link>
          <div className="hidden max-w-[380px] flex-1 md:block">
            <div className="flex h-[34px] items-center gap-2.5 rounded-[9px] border border-line bg-panel px-3 text-ink-3">
              <Search size={14} />
              <span className="text-[13px]">Search the docs…</span>
              <span className="ml-auto rounded-[5px] border border-line px-1.5 py-px font-mono text-[11px]">
                /
              </span>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden rounded-full border border-line px-3 py-1 font-mono text-[12.5px] text-ink-2 sm:inline">
              v{status?.version ?? '1.0.0'}
            </span>
            <ThemeToggle />
            <Button
              variant="primary"
              size="sm"
              onClick={() => navigate(status?.setup_complete ? '/console' : '/setup')}
            >
              {status?.setup_complete ? 'Open console' : 'Start setup'}
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-[1440px] flex-1 items-start gap-10 px-5 sm:px-7 lg:grid-cols-[236px_minmax(0,1fr)]">
        <aside className="sticky top-[60px] hidden max-h-[calc(100vh-60px)] overflow-auto py-8 lg:block">
          {groups.map(({ group, items }) => (
            <div key={group} className="mb-6">
              <div className="px-2.5 pb-2.5 text-[11px] font-bold tracking-[0.07em] text-ink-3 uppercase">
                {group}
              </div>
              <div className="flex flex-col gap-px">
                {items.map((doc) => (
                  <Link
                    key={doc.id}
                    to={`/docs/${doc.id}`}
                    className={cx(
                      'rounded-lg px-2.5 py-1.5 text-[13.5px] leading-snug transition',
                      doc.id === page.id
                        ? 'bg-accent-soft font-semibold text-ink'
                        : 'text-ink-2 hover:bg-panel-2',
                    )}
                  >
                    {doc.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </aside>

        <main className="min-w-0 py-9 pb-20">
          <div className="mb-3.5 flex items-center gap-2 text-[12.5px] text-ink-3">
            <Link to="/docs" className="hover:text-ink">
              Docs
            </Link>
            <span>/</span>
            <span>{page.group}</span>
            <span>/</span>
            <span className="text-ink-2">{page.title}</span>
          </div>

          <h1 className="m-0 mb-3 text-[clamp(2rem,4vw,2.375rem)] leading-[1.12] font-semibold tracking-[-0.03em]">
            {page.title}
          </h1>
          <p className="m-0 mb-9 text-[17px] leading-[1.6] text-ink-2 text-pretty">
            {page.lede}
          </p>

          <article>{page.body()}</article>

          <div className="mt-8 grid gap-3.5 border-t border-line pt-6 sm:grid-cols-2">
            {previous ? (
              <Link to={`/docs/${previous.id}`}>
                <div className="rounded-xl border border-line bg-panel px-4 py-4 transition hover:border-line-strong">
                  <div className="mb-1 text-xs text-ink-3">← Previous</div>
                  <div className="text-[14.5px] font-semibold">{previous.title}</div>
                </div>
              </Link>
            ) : (
              <span />
            )}
            {next ? (
              <Link to={`/docs/${next.id}`} className="sm:col-start-2">
                <div className="rounded-xl border border-line bg-panel px-4 py-4 text-right transition hover:border-line-strong">
                  <div className="mb-1 text-xs text-ink-3">Next →</div>
                  <div className="text-[14.5px] font-semibold">{next.title}</div>
                </div>
              </Link>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  )
}
