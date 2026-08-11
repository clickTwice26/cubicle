import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { Button, Card, Field } from '../components/ui'
import { Lock, Server, Shield, XCircle } from '../components/Icons'
import { Turnstile } from '../components/Turnstile'
import { useLogin, useSetupStatus } from '../lib/hooks'

/**
 * The sign-in screen.
 *
 * It says nothing about the instance beyond the product name. Which cluster
 * an account can reach is decided after authentication, and naming one here
 * would disclose part of the estate to anyone who can load the page.
 */

const POINTS = [
  {
    icon: Server,
    title: 'Runs on your hardware',
    body: 'Every function executes on machines you own, in a datacentre you chose.',
  },
  {
    icon: Shield,
    title: 'Nothing leaves the network',
    body: 'No telemetry, no analytics and no third party request from this console.',
  },
  {
    icon: Lock,
    title: 'Secrets sealed at rest',
    body: 'Each value is encrypted under a key held outside the database.',
  },
]

export default function Login() {
  const navigate = useNavigate()
  const login = useLogin()
  const { data: setup } = useSetupStatus()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [token, setToken] = useState('')
  // A Turnstile token is single use, so a rejected sign-in has to run the
  // challenge again. Bumping this remounts the widget.
  const [challenge, setChallenge] = useState(0)

  const protectedSignIn = Boolean(setup?.turnstile_enabled && setup.turnstile_site_key)
  const blocked = protectedSignIn && !token

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (blocked) return
    login.mutate(
      {
        email: email.trim(),
        password,
        ...(protectedSignIn ? { turnstile_token: token } : {}),
      },
      {
        onSuccess: () => navigate('/console', { replace: true }),
        onError: () => {
          // The server consumed the token whether or not the password was
          // right, so the page is holding one that will now be refused.
          if (protectedSignIn) {
            setToken('')
            setChallenge((n) => n + 1)
          }
        },
      },
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <header className="border-b border-line">
        <div className="mx-auto flex h-[62px] w-full max-w-[1180px] items-center px-6 sm:px-8">
          <Link to="/" aria-label="Cubicle home">
            <Logo />
          </Link>
          <ThemeToggle className="ml-auto" />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 py-12 sm:py-16">
        <div className="grid w-full max-w-[1000px] items-center gap-12 lg:grid-cols-[1fr_400px] lg:gap-16">
          {/* The pitch. Hidden on small screens, where the form is the whole job. */}
          <section className="hidden lg:block">
            <h2 className="m-0 max-w-[26ch] text-[34px] font-semibold leading-[1.15] tracking-[-0.025em]">
              Serverless functions, on infrastructure you control.
            </h2>
            <p className="mt-4 mb-9 max-w-[46ch] text-[15px] leading-relaxed text-ink-2">
              Write a handler, press deploy, get a URL. No account anywhere, no
              per-seat billing and no data crossing a boundary you did not choose.
            </p>

            <ul className="m-0 grid list-none gap-6 p-0">
              {POINTS.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-3.5">
                  <span className="mt-0.5 grid h-8 w-8 flex-none place-items-center rounded-[9px] border border-line bg-panel text-ink-2">
                    <Icon size={15} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-semibold">{title}</div>
                    <div className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{body}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          {/* The form. */}
          <Card className="mx-auto w-full max-w-[420px] p-7 shadow-card sm:p-8">
            <h1 className="m-0 text-[24px] font-semibold tracking-[-0.02em]">Sign in</h1>
            <p className="mt-1.5 mb-7 text-[13.5px] text-ink-2">
              Use the credentials issued to you by an instance owner.
            </p>

            <form onSubmit={submit} className="grid gap-4" noValidate>
              <Field
                label="Email"
                type="email"
                mono={false}
                value={email}
                placeholder="you@example.com"
                autoComplete="username"
                autoFocus
                required
                onChange={(event) => setEmail(event.target.value)}
              />

              <div>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <span className="text-[12.5px] text-ink-2">Password</span>
                  <button
                    type="button"
                    onClick={() => setReveal((on) => !on)}
                    className="text-[12px] text-ink-3 transition hover:text-ink"
                  >
                    {reveal ? 'Hide' : 'Show'}
                  </button>
                </div>
                <Field
                  type={reveal ? 'text' : 'password'}
                  mono={false}
                  value={password}
                  autoComplete="current-password"
                  required
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>

              {login.error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2.5 rounded-[10px] border border-err bg-err-bg px-3.5 py-2.5 text-[13px]"
                >
                  <span className="mt-px flex-none text-err">
                    <XCircle size={15} />
                  </span>
                  <span>{(login.error as Error).message}</span>
                </div>
              ) : null}

              {protectedSignIn ? (
                <div className="grid gap-2">
                  <Turnstile
                    siteKey={setup!.turnstile_site_key}
                    onToken={setToken}
                    resetKey={challenge}
                  />
                  <p className="m-0 text-center text-[11.5px] text-ink-3">
                    Protected by Cloudflare Turnstile
                  </p>
                </div>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={login.isPending}
                disabled={blocked}
                className="mt-1 w-full"
              >
                {blocked ? 'Waiting for verification' : 'Sign in'}
              </Button>
            </form>

            <p className="mt-7 mb-0 border-t border-line pt-5 text-[12px] leading-relaxed text-ink-3">
              This instance cannot send mail, so there is no reset link. An owner can set a new
              password for any account from Settings, then Users.
            </p>
          </Card>
        </div>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex h-[52px] w-full max-w-[1180px] flex-wrap items-center gap-x-5 gap-y-1 px-6 text-[12px] text-ink-3 sm:px-8">
          <span>Cubicle</span>
          <Link to="/docs" className="transition hover:text-ink">
            Documentation
          </Link>
          <span className="ml-auto">Self-hosted. Apache-2.0.</span>
        </div>
      </footer>
    </div>
  )
}
