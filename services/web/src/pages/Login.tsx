import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo, ThemeToggle } from '../components/Layout'
import { Button, Card, Field } from '../components/ui'
import { useLogin, useSetupStatus } from '../lib/hooks'

export default function Login() {
  const navigate = useNavigate()
  const login = useLogin()
  const { data: status } = useSetupStatus()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    login.mutate(
      { email: email.trim(), password },
      { onSuccess: () => navigate('/console', { replace: true }) },
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <header className="border-b border-line">
        <div className="mx-auto flex h-[62px] max-w-[860px] items-center px-6 sm:px-8">
          <Link to="/">
            <Logo />
          </Link>
          <ThemeToggle className="ml-auto" />
        </div>
      </header>

      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <Card className="w-full max-w-[420px] p-8">
          <h1 className="m-0 mb-1.5 text-[26px] font-semibold tracking-[-0.02em]">Sign in</h1>
          <p className="m-0 mb-7 text-sm text-ink-2">
            {status?.cluster_name ? (
              <>
                <span className="font-mono">{status.cluster_name}</span> · self-hosted, no
                registration.
              </>
            ) : (
              'Self-hosted instance.'
            )}
          </p>

          <form onSubmit={submit} className="grid gap-4">
            <Field
              label="Email"
              type="email"
              value={email}
              autoComplete="username"
              required
              onChange={(event) => setEmail(event.target.value)}
            />
            <Field
              label="Password"
              type="password"
              mono={false}
              value={password}
              autoComplete="current-password"
              required
              onChange={(event) => setPassword(event.target.value)}
            />

            {login.error ? (
              <div className="rounded-[10px] border border-err bg-err-bg px-3.5 py-2.5 text-[13px]">
                {(login.error as Error).message}
              </div>
            ) : null}

            <Button type="submit" variant="primary" size="lg" loading={login.isPending}>
              Sign in
            </Button>
          </form>

          <p className="mt-6 mb-0 text-xs leading-relaxed text-ink-3">
            There is no password reset by email — nothing on this instance can send mail. An
            owner can set a new password for any account from Settings → Users.
          </p>
        </Card>
      </div>
    </div>
  )
}
