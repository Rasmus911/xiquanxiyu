interface PendingRequest {
  fingerprint: string
  key: string
}

const PREFIX = 'xiquan:pending-request:'

export function pendingRequestKey(scope: string, fingerprint: string) {
  const storageKey = `${PREFIX}${scope}`
  try {
    const existing = JSON.parse(sessionStorage.getItem(storageKey) || 'null') as PendingRequest | null
    if (existing?.fingerprint === fingerprint && existing.key) return existing.key
  } catch {
    sessionStorage.removeItem(storageKey)
  }
  const key = crypto.randomUUID()
  sessionStorage.setItem(storageKey, JSON.stringify({ fingerprint, key } satisfies PendingRequest))
  return key
}

export function clearPendingRequestKey(scope: string, expectedKey?: string) {
  if (expectedKey) {
    try {
      const current = JSON.parse(sessionStorage.getItem(`${PREFIX}${scope}`) || 'null') as PendingRequest | null
      if (current?.key !== expectedKey) return
    } catch { return }
  }
  sessionStorage.removeItem(`${PREFIX}${scope}`)
}
