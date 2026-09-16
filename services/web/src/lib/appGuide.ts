import template from './deploy-prompt.md?raw'
import type { Hosting } from './apps'

/**
 * What a repository needs to deploy here, in the two forms people use it.
 *
 * The page shows the rules; the prompt carries the same rules to whatever
 * assistant has the repository open, so "make this deployable" is one paste
 * rather than a conversation about ports. The prompt is a Markdown file of its
 * own because it is prose meant to be read and edited as prose — and because
 * it states facts about the runtime, it is the file to update when the runtime
 * changes what it does.
 */

export const CUBICLE_JSON_EXAMPLE = `{
  "schemaVersion": 1,
  "dockerfilePath": "./Dockerfile",
  "port": 3000,
  "healthCheckPath": "/healthz",
  "env": { "NODE_ENV": "production" },
  "buildArgs": { "NEXT_PUBLIC_API_URL": "https://api.example.com" }
}
`

export const CAPTAIN_DEFINITION_EXAMPLE = `{
  "schemaVersion": 2,
  "dockerfileLines": [
    "FROM node:22-alpine",
    "WORKDIR /app",
    "COPY . .",
    "RUN npm ci --omit=dev",
    "EXPOSE 3000",
    "CMD [\\"node\\", \\"server.js\\"]"
  ]
}
`

/** Every key the definition reads, in the order a person would reach for them. */
export const DEFINITION_KEYS: { key: string; means: string }[] = [
  {
    key: 'healthCheckPath',
    means: 'Must answer below 400 before traffic moves. The one worth setting.',
  },
  {
    key: 'port',
    means: 'What the container listens on. Only needed when EXPOSE does not say it.',
  },
  {
    key: 'dockerfilePath',
    means: 'A Dockerfile somewhere other than the root. The context stays the root.',
  },
  {
    key: 'dockerfileLines',
    means: 'The Dockerfile itself, inline, for a repository that carries none.',
  },
  { key: 'imageName', means: 'Skip the build and run a published image.' },
  { key: 'buildArgs', means: 'Passed to docker build. Committed, so never a secret.' },
  { key: 'env', means: 'Non-secret defaults. The Environment tab overrides them.' },
]

type Addresses = Pick<Hosting, 'base_domain' | 'instance_url' | 'configured'>

/**
 * The prompt, with this instance's real addresses in it.
 *
 * An assistant that knows the app will live at `name.cubicle.example.com` and
 * under `/<token>` can make better choices about base paths than one told
 * "some hostname". Without hosting data it falls back to the shape.
 */
export function deployPrompt(hosting?: Addresses | null): string {
  const instance = (hosting?.instance_url || 'https://<instance>').replace(/\/+$/, '')
  const scheme = instance.startsWith('http://') ? 'http' : 'https'
  const app =
    hosting && !hosting.configured
      ? 'its own hostname once this instance has a domain'
      : `\`${scheme}://<app-name>.${hosting?.base_domain || '<instance-domain>'}/\``
  return template
    .replace('{{app_address}}', app)
    .replace('{{instant_address}}', `\`${instance}/<token>/\``)
}
