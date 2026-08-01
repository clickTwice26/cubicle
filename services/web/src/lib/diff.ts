/**
 * A line diff, small enough to keep rather than take a dependency for.
 *
 * Classic longest-common-subsequence over lines. Files here are handlers —
 * hundreds of lines at the outside — so the O(n·m) table is a few hundred
 * kilobytes in the worst case and nothing in the normal one. A guard bails out
 * to a whole-file replacement if something enormous ever arrives, because a
 * diff nobody can read is worth less than an honest "this was rewritten".
 */

export type LineKind = 'add' | 'del' | 'same'

export interface DiffLine {
  kind: LineKind
  text: string
  /** 1-based line number in the old file, when the line exists there. */
  before?: number
  /** 1-based line number in the new file, when the line exists there. */
  after?: number
}

export interface DiffStats {
  added: number
  removed: number
}

/** Above this, the LCS table stops being worth building. */
const MAX_LINES = 4000

export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.length ? before.replace(/\n$/, '').split('\n') : []
  const b = after.length ? after.replace(/\n$/, '').split('\n') : []

  if (a.length > MAX_LINES || b.length > MAX_LINES) {
    return [
      ...a.map((text, i) => ({ kind: 'del' as const, text, before: i + 1 })),
      ...b.map((text, i) => ({ kind: 'add' as const, text, after: i + 1 })),
    ]
  }

  // lcs[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  )
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i], before: i + 1, after: j + 1 })
      i += 1
      j += 1
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: 'del', text: a[i], before: i + 1 })
      i += 1
    } else {
      out.push({ kind: 'add', text: b[j], after: j + 1 })
      j += 1
    }
  }
  while (i < a.length) {
    out.push({ kind: 'del', text: a[i], before: i + 1 })
    i += 1
  }
  while (j < b.length) {
    out.push({ kind: 'add', text: b[j], after: j + 1 })
    j += 1
  }
  return out
}

export function diffStats(lines: DiffLine[]): DiffStats {
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.kind === 'add') added += 1
    else if (line.kind === 'del') removed += 1
  }
  return { added, removed }
}

export interface Hunk {
  /** How many unchanged lines were dropped immediately before this run. */
  skipped: number
  lines: DiffLine[]
}

/**
 * Drop long runs of unchanged lines, keeping `context` of them either side.
 *
 * A rewrite of one function in a 200-line file should read as one change, not
 * as 200 lines you have to scan for the highlighted ones.
 */
export function collapse(lines: DiffLine[], context = 3): Hunk[] {
  const keep = new Array<boolean>(lines.length).fill(false)
  lines.forEach((line, index) => {
    if (line.kind === 'same') return
    for (
      let k = Math.max(0, index - context);
      k <= Math.min(lines.length - 1, index + context);
      k += 1
    ) {
      keep[k] = true
    }
  })

  const hunks: Hunk[] = []
  let current: Hunk | null = null
  let skipped = 0
  lines.forEach((line, index) => {
    if (keep[index]) {
      if (!current) {
        current = { skipped, lines: [] }
        hunks.push(current)
        skipped = 0
      }
      current.lines.push(line)
    } else {
      current = null
      skipped += 1
    }
  })
  return hunks
}
