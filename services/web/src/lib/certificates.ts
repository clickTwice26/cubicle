import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

const ROOT = '/api/certificates'

export interface Certificate {
  id: string
  name: string
  hostnames: string[]
  status: 'pending' | 'issuing' | 'issued' | 'failed'
  provider: string
  issued_at: string | null
  expires_at: string | null
  days_left: number | null
  last_error: string | null
  last_log: string
  renewals: number
  paths: { fullchain: string; privkey: string }
}

export interface CertificateState {
  /** False when Caddy owns the ports — it issues its own and this is moot. */
  manages_certificates: boolean
  provider: string
  email: string
  token_hint: string | null
  cert_dir: string
  certificates: Certificate[]
}

export function useCertificates() {
  return useQuery({
    queryKey: ['certificates'],
    queryFn: () => api.get<CertificateState>(ROOT),
    // An issuance runs in the background and takes as long as DNS does.
    refetchInterval: (query) =>
      (query.state.data?.certificates ?? []).some((c) => c.status === 'issuing') ? 5000 : false,
  })
}

function useCertMutation<T, V>(fn: (vars: V) => Promise<T>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['certificates'] }),
  })
}

export const useSaveAcmeCredentials = () =>
  useCertMutation<CertificateState, { provider: string; token?: string; email?: string }>((args) =>
    api.put(`${ROOT}/credentials`, args),
  )

export const useIssueCertificate = () =>
  useCertMutation<Certificate, { hostnames: string[]; staging?: boolean }>((args) =>
    api.post(`${ROOT}/issue`, args),
  )

export const useRenewCertificate = () =>
  useCertMutation<Certificate, string>((id) => api.post(`${ROOT}/${id}/renew`))
