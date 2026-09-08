import { useEffect, useState } from 'react'
import { Lock, Refresh } from './Icons'
import { Badge, Button, Card, CardHeader, CopyButton, Field, cx, useToast } from './ui'
import {
  useCertificates,
  useIssueCertificate,
  useRenewCertificate,
  useSaveAcmeCredentials,
  type Certificate,
} from '../lib/certificates'
import { useHosting } from '../lib/apps'
import { relativeTime } from '../lib/format'

/**
 * Certificates, for the installs that need them.
 *
 * An instance that owns 80 and 443 issues its own on first request, so this
 * renders nothing there rather than offering a button that would duplicate
 * work Caddy already did. Behind another web server nobody can: a wildcard
 * cannot be issued over HTTP, which is why a DNS token is asked for and why
 * that is the only thing asked for.
 */
export function CertificatesCard() {
  const toast = useToast()
  const { data: state } = useCertificates()
  const { data: hosting } = useHosting()
  const save = useSaveAcmeCredentials()
  const issue = useIssueCertificate()

  const [token, setToken] = useState('')
  const [email, setEmail] = useState('')
  const [staging, setStaging] = useState(false)

  useEffect(() => {
    if (state) setEmail(state.email)
  }, [state])

  if (!state || !state.manages_certificates) return null

  const wildcard = hosting?.base_domain ? `*.${hosting.base_domain}` : ''
  const existing = state.certificates.find((c) => c.hostnames.includes(wildcard))
  const ready = Boolean(state.token_hint || token.trim())

  return (
    <Card className="mb-5 overflow-hidden">
      <CardHeader
        title="TLS certificates"
        subtitle="This instance sits behind another web server, so the certificate for app hostnames is one it has to obtain"
        action={existing ? <StatusBadge certificate={existing} /> : null}
      />

      <div className="grid gap-4 px-5 py-5">
        <div className="rounded-[10px] border border-line bg-panel-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
          A wildcard cannot be issued over HTTP — Let&apos;s Encrypt only issues one after seeing
          a record in your DNS. So this needs a token that can write in the zone, and nothing
          else: it is used to add one TXT record, which is removed as soon as the certificate is
          signed. Stored encrypted, never shown again, and renewed automatically at 30 days.
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Cloudflare API token"
            type="password"
            autoComplete="off"
            value={token}
            placeholder={state.token_hint ? `stored · ${state.token_hint}` : 'Zone:DNS:Edit'}
            onChange={(event) => setToken(event.target.value)}
            hint="My Profile → API Tokens → Edit zone DNS, scoped to this one zone."
          />
          <Field
            label="Contact email"
            mono={false}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            hint="Where Let's Encrypt sends expiry warnings."
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            size="sm"
            loading={save.isPending}
            disabled={!token.trim() && email === state.email}
            onClick={() =>
              save.mutate(
                {
                  provider: 'cloudflare',
                  ...(token.trim() ? { token: token.trim() } : {}),
                  email: email.trim(),
                },
                {
                  onSuccess: () => {
                    setToken('')
                    toast.push('Saved')
                  },
                  onError: (error) => toast.push(error.message, 'err'),
                },
              )
            }
          >
            Save token
          </Button>

          {wildcard ? (
            <Button
              size="sm"
              variant="primary"
              icon={<Lock size={13} />}
              loading={issue.isPending || existing?.status === 'issuing'}
              disabled={!ready}
              onClick={() =>
                issue.mutate(
                  { hostnames: [wildcard], staging },
                  {
                    onSuccess: () =>
                      toast.push('Requesting the certificate', 'ok', 'a minute or so'),
                    onError: (error) => toast.push(error.message, 'err'),
                  },
                )
              }
            >
              {existing ? 'Reissue' : 'Get certificate'} for {wildcard}
            </Button>
          ) : null}

          <button
            type="button"
            onClick={() => setStaging((value) => !value)}
            className={cx(
              'rounded-md border px-2 py-1 font-mono text-[11px] transition',
              staging ? 'border-warn text-warn' : 'border-line text-ink-3 hover:text-ink',
            )}
            title="Let's Encrypt's staging CA — untrusted by browsers, but not rate limited"
          >
            staging
          </button>
        </div>

        {state.certificates.map((certificate) => (
          <CertificateRow key={certificate.id} certificate={certificate} />
        ))}
      </div>
    </Card>
  )
}

function StatusBadge({ certificate }: { certificate: Certificate }) {
  if (certificate.status === 'issued')
    return (
      <Badge tone="accent">
        {certificate.days_left !== null ? `${certificate.days_left} days left` : 'issued'}
      </Badge>
    )
  if (certificate.status === 'issuing') return <Badge tone="warn">issuing</Badge>
  if (certificate.status === 'failed') return <Badge tone="err">failed</Badge>
  return <Badge>pending</Badge>
}

function CertificateRow({ certificate }: { certificate: Certificate }) {
  const toast = useToast()
  const renew = useRenewCertificate()
  const [showLog, setShowLog] = useState(false)

  return (
    <div className="rounded-[10px] border border-line">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-3.5 py-2.5">
        <span className="font-mono text-[12.5px] font-semibold">
          {certificate.hostnames.join(', ')}
        </span>
        <StatusBadge certificate={certificate} />
        <span className="text-[12px] text-ink-3">
          {certificate.issued_at ? `issued ${relativeTime(certificate.issued_at)}` : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            icon={<Refresh size={12} />}
            loading={renew.isPending || certificate.status === 'issuing'}
            onClick={() =>
              renew.mutate(certificate.id, {
                onSuccess: () => toast.push('Renewing'),
                onError: (error) => toast.push(error.message, 'err'),
              })
            }
          >
            Renew
          </Button>
          {certificate.last_log ? (
            <Button size="sm" variant="ghost" onClick={() => setShowLog((value) => !value)}>
              {showLog ? 'Hide log' : 'Log'}
            </Button>
          ) : null}
        </div>
      </div>

      {certificate.status === 'issued' ? (
        <div className="grid gap-2 px-3.5 py-3 text-[12px]">
          <span className="text-ink-2">
            Point your web server at these, then reload it. They stay the same across renewals.
          </span>
          <PathRow label="ssl_certificate" value={certificate.paths.fullchain} />
          <PathRow label="ssl_certificate_key" value={certificate.paths.privkey} />
        </div>
      ) : null}

      {certificate.last_error ? (
        <div className="border-t border-line bg-err-bg px-3.5 py-2.5 font-mono text-[11.5px] break-words">
          {certificate.last_error}
        </div>
      ) : null}

      {showLog ? (
        <pre className="m-0 max-h-[320px] overflow-auto border-t border-line px-3.5 py-3 font-mono text-[11px] leading-[1.6] whitespace-pre-wrap text-ink-2">
          {certificate.last_log}
        </pre>
      ) : null}
    </div>
  )
}

function PathRow({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-center gap-2 rounded-[8px] border border-line bg-bg px-2.5 py-1.5">
      <span className="flex-none font-mono text-[11px] text-ink-3">{label}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{value}</span>
      <CopyButton value={value} label="" />
    </span>
  )
}
