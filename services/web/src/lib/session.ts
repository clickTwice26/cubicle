/**
 * The playground session for a namespace.
 *
 * Runtime context is keyed by ``X-Cubicle-Session``, so the group page and a
 * function's workbench have to agree on the value — otherwise a test invoke
 * writes into one context while the panel next to it reads another. Held per
 * group outside React and mirrored into sessionStorage, so navigating between
 * the two pages keeps the same session and a reload does not silently start a
 * fresh one.
 */

import { useCallback, useSyncExternalStore } from 'react'
import { newSessionId } from './format'

const STORAGE_PREFIX = 'cubicle-session:'

const sessions = new Map<string, string>()
const listeners = new Set<() => void>()

function load(groupId: string): string {
  const cached = sessions.get(groupId)
  if (cached) return cached

  let value: string | null = null
  try {
    value = sessionStorage.getItem(STORAGE_PREFIX + groupId)
  } catch {
    /* private browsing — a fresh session per page load is an acceptable floor */
  }
  const session = value ?? newSessionId()
  sessions.set(groupId, session)
  if (!value) persist(groupId, session)
  return session
}

function persist(groupId: string, session: string): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + groupId, session)
  } catch {
    /* the in-memory map still keeps both pages in sync for this page load */
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The current session for a group, plus a way to roll it. */
export function useGroupSession(groupId: string): [string, () => void] {
  const session = useSyncExternalStore(
    subscribe,
    () => load(groupId),
    () => load(groupId),
  )

  const reset = useCallback(() => {
    const next = newSessionId()
    sessions.set(groupId, next)
    persist(groupId, next)
    for (const listener of listeners) listener()
  }, [groupId])

  return [session, reset]
}
