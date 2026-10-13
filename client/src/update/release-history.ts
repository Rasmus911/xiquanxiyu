import historyData from './history-data.json'

export interface ReleaseHistoryEntry {
  version: string
  publishedAt: string | null
  state: 'published' | 'unverified' | 'pending'
  source: 'user' | 'backfilled'
  notes: string[]
}

function validIsoTimestamp(value: string | null): value is string {
  if (typeof value !== 'string') return false
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value)
  if (!match || !Number.isFinite(Date.parse(value))) return false
  const [, year, month, day, hour, minute, second] = match
  const daysInMonth = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate()
  return Number(month) >= 1 && Number(month) <= 12 && Number(day) >= 1 && Number(day) <= daysInMonth &&
    Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60
}

// The optional metadata is supplied only by the verified desktop updater state.
// It changes a date, never the approved offline notes or the list of versions.
export function getReleaseHistory(verified?: { version: string; publishedAt: string }): ReleaseHistoryEntry[] {
  return (historyData as ReleaseHistoryEntry[]).map(row => {
    const entry = { ...row, notes: [...row.notes] }
    if (verified?.version === entry.version && validIsoTimestamp(verified.publishedAt)) {
      entry.publishedAt = verified.publishedAt
      entry.state = 'published'
    }
    return entry
  }).sort((left, right) => {
    const a = left.version.split('.').map(Number)
    const b = right.version.split('.').map(Number)
    for (let index = 0; index < 3; index++) {
      if (a[index] !== b[index]) return b[index]! - a[index]!
    }
    return 0
  })
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
})

export function historyDateLabel(entry: ReleaseHistoryEntry): string {
  if (entry.state === 'pending') return '待发布'
  if (entry.state !== 'published' || !validIsoTimestamp(entry.publishedAt)) return '发布日期未核实'
  return dateFormatter.format(new Date(entry.publishedAt))
}
