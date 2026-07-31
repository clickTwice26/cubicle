import { useRef, useState, type ReactNode } from 'react'
import { Check, Copy } from '../../components/Icons'
import { cx } from '../../components/ui'

/**
 * A docs snippet with a copy button.
 *
 * The text is read from the rendered DOM rather than passed in alongside the
 * markup. Snippets here are syntax-highlighted with nested spans, so the only
 * other option is keeping a plain-text copy next to every one of them — two
 * things to edit, and eventually two things that disagree.
 *
 * The shell prompt is dropped on copy: nobody wants `$` pasted into their
 * terminal, and every example here uses it as a marker rather than as part of
 * the command.
 */
export function CodeBlock({ children, filename }: { children: ReactNode; filename?: string }) {
  const pre = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    const text = (pre.current?.textContent ?? '')
      .split('\n')
      .map((line) => line.replace(/^\s*\$ ?/, ''))
      .join('\n')
      .trim()
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard blocked — the text is still selectable */
    }
  }

  return (
    <div className="group relative mb-6 overflow-hidden rounded-xl border border-line bg-panel">
      <div className="flex items-center gap-2 border-b border-line px-3.5 py-2">
        <span className="font-mono text-[11.5px] text-ink-3">{filename ?? 'shell'}</span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? 'Copied' : 'Copy to clipboard'}
          className={cx(
            'ml-auto flex items-center gap-1.5 rounded-md border border-line px-2 py-1 font-mono text-[11px] transition',
            // Always reachable by keyboard and on touch; it just steps back
            // visually until the block is hovered.
            'opacity-0 focus-visible:opacity-100 group-hover:opacity-100',
            copied ? 'text-ok opacity-100' : 'text-ink-3 hover:text-ink',
          )}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'copied' : 'copy'}
        </button>
      </div>
      <pre
        ref={pre}
        className="m-0 overflow-x-auto px-4.5 py-4 font-mono text-[13px] leading-[1.75] text-ink"
      >
        {children}
      </pre>
    </div>
  )
}
