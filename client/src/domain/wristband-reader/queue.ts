export function createScanQueue<T, R>(send: (item: T) => Promise<R>, onResult: (result: R, item: T) => void,
  onError: (error: unknown, item: T) => void, limit = 12) {
  let generation = 0; let running = false
  const waiting: Array<{ item: T; generation: number }> = []
  async function drain() {
    if (running) return
    running = true
    try {
      while (waiting.length) {
        const next = waiting.shift()!
        try {
          const result = await send(next.item)
          if (next.generation === generation) onResult(result, next.item)
        } catch (error) {
          if (next.generation === generation) {
            waiting.length = 0
            onError(error, next.item)
          }
        }
      }
    } finally { running = false }
  }
  return {
    enqueue(item: T) {
      if (waiting.length + Number(running) >= limit) return false
      waiting.push({ item, generation }); void drain(); return true
    },
    clear() { generation += 1; waiting.length = 0 },
    get pending() { return waiting.length + Number(running) },
  }
}
