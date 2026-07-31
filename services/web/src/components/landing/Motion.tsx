import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cx } from '../ui'

/**
 * "Tell me when this element has been reached."
 *
 * One shared scroll listener rather than an IntersectionObserver per element.
 * An observer only reports when the intersection *changes*, so jumping
 * straight to the bottom of the page — an anchor link, Cmd+End, a flick on a
 * trackpad — carries an element from below the fold to above it without ever
 * producing a callback, and a one-way reveal leaves that whole section blank
 * for the rest of the visit.
 *
 * The registry drains as elements reveal, so the listener costs one rect read
 * per pending element per frame and then unhooks itself entirely.
 */
const pending = new Map<Element, () => void>()
let frame = 0

function sweep(): void {
  frame = 0
  const limit = window.innerHeight * 0.9
  for (const [element, reveal] of pending) {
    // top < limit covers both directions: approaching from below, and already
    // scrolled past (top goes negative).
    if (element.getBoundingClientRect().top < limit) {
      pending.delete(element)
      reveal()
    }
  }
  if (pending.size === 0) detach()
}

function schedule(): void {
  if (!frame) frame = requestAnimationFrame(sweep)
}

function attach(): void {
  window.addEventListener('scroll', schedule, { passive: true })
  window.addEventListener('resize', schedule, { passive: true })
}

function detach(): void {
  window.removeEventListener('scroll', schedule)
  window.removeEventListener('resize', schedule)
}

function whenReached(element: Element, reveal: () => void): () => void {
  if (pending.size === 0) attach()
  pending.set(element, reveal)
  schedule()
  return () => {
    pending.delete(element)
    if (pending.size === 0) detach()
  }
}

/**
 * Reveals its children once they scroll into view.
 *
 * The hidden state is applied by CSS but only ever removed from here, so a
 * page rendered without JavaScript — or read by a crawler — still shows
 * everything rather than a column of blank space.
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const element = ref.current
    if (!element) return
    return whenReached(element, () => setShown(true))
  }, [])

  return (
    <div
      ref={ref}
      className={cx('reveal min-w-0', className)}
      data-shown={shown}
      style={{ '--reveal-delay': `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </div>
  )
}

/** Counts up to its value the first time it is reached. */
export function CountUp({
  to,
  suffix = '',
  duration = 900,
}: {
  to: number
  suffix?: string
  duration?: number
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [value, setValue] = useState(0)

  useEffect(() => {
    const element = ref.current
    if (!element) return
    return whenReached(element, () => {
      const started = performance.now()
      const step = (now: number) => {
        const t = Math.min(1, (now - started) / duration)
        setValue(Math.round(to * (1 - (1 - t) ** 3)))
        if (t < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    })
  }, [to, duration])

  return (
    <span ref={ref}>
      {value}
      {suffix}
    </span>
  )
}
