/**
 * The cluster the console is currently pointed at.
 *
 * Held outside React so the fetch layer can read it synchronously on every
 * request, and mirrored into localStorage so a reload stays where you were.
 * Unset means "whatever the instance considers default", which is what a
 * single-cluster install always wants.
 */

import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'cubicle-cluster'

let active: string | null = read()
const listeners = new Set<(next: string | null) => void>()

function read(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function activeCluster(): string | null {
  return active
}

export function setActiveCluster(slugOrId: string | null): void {
  active = slugOrId
  try {
    if (slugOrId) localStorage.setItem(STORAGE_KEY, slugOrId)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private browsing — the choice just will not persist */
  }
  for (const listener of listeners) listener(active)
}

export function onClusterChange(listener: (next: string | null) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/**
 * The active cluster, as React state.
 *
 * Every cluster-scoped query key ends with this value, so switching clusters
 * changes the keys rather than refetching the same ones. Without that, two
 * clusters share a cache slot and a switch shows the previous cluster's
 * numbers under the new cluster's name until each panel happens to settle.
 */
export function useActiveCluster(): string {
  return useSyncExternalStore(
    onClusterChange,
    () => active ?? 'default',
    () => 'default',
  )
}
