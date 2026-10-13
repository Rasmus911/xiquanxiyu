import { expect, it } from 'vitest'

async function factory() {
  const module = await import('./queue').catch(() => null)
  expect(typeof module?.createScanQueue).toBe('function')
  return module!.createScanQueue
}
const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0))

it('serializes rapid cards, retains exact request identity and reports overflow', async () => {
  const create = await factory(); const sent: string[] = []; const results: string[] = []
  const resolves: Array<(value: string) => void> = []
  const queue = create<string, string>(item => { sent.push(item); return new Promise(done => resolves.push(done)) }, value => results.push(value), () => {}, 2)
  expect(queue.enqueue('id-one')).toBe(true); expect(queue.enqueue('id-two')).toBe(true)
  expect(queue.enqueue('id-three')).toBe(false); expect(sent).toEqual(['id-one'])
  resolves[0]!('one'); await tick(); expect(sent).toEqual(['id-one', 'id-two'])
  resolves[1]!('two'); await tick(); expect(results).toEqual(['one', 'two']); expect(queue.pending).toBe(0)
})

it('a failed transport discards queued cards rather than replaying them when online', async () => {
  const create = await factory(); const errors: string[] = []; const sent: string[] = []
  let reject!: (reason: Error) => void
  const queue = create<string, string>(item => { sent.push(item); return new Promise((_done, fail) => { reject = fail }) }, () => {}, (_error, item) => errors.push(item))
  queue.enqueue('same-id-for-explicit-retry'); queue.enqueue('do-not-replay')
  reject(new Error('network')); await tick()
  expect(sent).toEqual(['same-id-for-explicit-retry']); expect(errors).toEqual(sent); expect(queue.pending).toBe(0)
})

it('reset invalidates in-flight results and never sends old waiting requests', async () => {
  const create = await factory(); const sent: string[] = []; const results: string[] = []
  const resolves: Array<(value: string) => void> = []
  const queue = create<string, string>(item => { sent.push(item); return new Promise(done => resolves.push(done)) }, value => results.push(value), () => {})
  queue.enqueue('old'); queue.enqueue('old-waiting'); queue.clear(); queue.enqueue('new')
  resolves[0]!('old'); await tick(); expect(sent).toEqual(['old', 'new']); expect(results).toEqual([])
  resolves[1]!('new'); await tick(); expect(results).toEqual(['new'])
})
