function normalizeBusyReason(value) {
  if (typeof value !== 'string') return null
  const reason = value.trim()
  return reason || null
}

function installationDecision(status, busyReason) {
  const normalizedReason = normalizeBusyReason(busyReason)
  if (normalizedReason) return { ok: false, reason: normalizedReason }
  if (status !== 'downloaded') return { ok: false, reason: '更新尚未下载完成' }
  return { ok: true }
}

module.exports = { installationDecision, normalizeBusyReason }
