import type { ReactNode } from 'react'

/**
 * Enough markdown to read a function's README.
 *
 * React elements, never `dangerouslySetInnerHTML`: a README can be written by
 * the assistant or arrive from the marketplace, so rendering it must not be a
 * way to get script into the console. Anything this does not understand falls
 * through as text, which is the right failure — an unrendered heading is
 * legible, an executed one is not.
 */

/** `**bold**`, `` `code` `` and `[text](href)`, in one pass over the line. */
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g
  let last = 0
  let match: RegExpExecArray | null
  let index = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]

    if (token.startsWith('**')) {
      out.push(<strong key={`${key}-b${index}`}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      out.push(
        <code
          key={`${key}-c${index}`}
          className="rounded bg-panel-2 px-1 py-0.5 font-mono text-[12px]"
        >
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      const split = token.indexOf('](')
      const label = token.slice(1, split)
      const href = token.slice(split + 2, -1)
      // Only http(s). A README is untrusted text, and javascript: in a link is
      // the oldest trick there is.
      const safe = /^https?:\/\//i.test(href)
      out.push(
        safe ? (
          <a
            key={`${key}-a${index}`}
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-accent-ink underline underline-offset-2"
          >
            {label}
          </a>
        ) : (
          <span key={`${key}-a${index}`}>{label}</span>
        ),
      )
    }
    last = match.index + token.length
    index += 1
  }

  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    // Fenced code. Everything inside is text — no inline parsing, because a
    // README's code block is the one place backticks mean themselves.
    if (line.trimStart().startsWith('```')) {
      const language = line.trim().slice(3).trim()
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trimStart().startsWith('```')) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <div key={`f${index}`} className="my-3 overflow-hidden rounded-[9px] border border-line">
          {language ? (
            <div className="border-b border-line bg-panel-2 px-3 py-1.5 font-mono text-[11px] text-ink-3">
              {language}
            </div>
          ) : null}
          <pre className="m-0 overflow-x-auto px-3 py-2.5 font-mono text-[12px] leading-relaxed">
            {body.join('\n')}
          </pre>
        </div>,
      )
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const size = ['text-[19px]', 'text-[16px]', 'text-[14px]', 'text-[13px]'][level - 1]
      blocks.push(
        <div
          key={`h${index}`}
          className={`mt-4 mb-2 font-semibold first:mt-0 ${size}`}
        >
          {inline(heading[2], `h${index}`)}
        </div>,
      )
      index += 1
      continue
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items: string[] = []
      const ordered = /^\s*\d+\./.test(line)
      while (index < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*+]|\d+\.)\s+/, ''))
        index += 1
      }
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List
          key={`l${index}`}
          className={`my-2 ml-5 grid gap-1 ${ordered ? 'list-decimal' : 'list-disc'}`}
        >
          {items.map((item, n) => (
            <li key={n}>{inline(item, `l${index}-${n}`)}</li>
          ))}
        </List>,
      )
      continue
    }

    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      blocks.push(<hr key={`r${index}`} className="my-4 border-line" />)
      index += 1
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    // A paragraph runs until a blank line or the start of another block.
    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trimStart().startsWith('```') &&
      !/^#{1,4}\s/.test(lines[index]) &&
      !/^\s*([-*+]|\d+\.)\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={`p${index}`} className="my-2 leading-relaxed">
        {inline(paragraph.join(' '), `p${index}`)}
      </p>,
    )
  }

  return (
    <div className="text-[13px] text-ink-2 [overflow-wrap:anywhere]">
      {blocks.length ? blocks : <span className="text-ink-3">Nothing to preview.</span>}
    </div>
  )
}
