import { expect, it } from 'vitest'

async function factory() {
  const module = await import('./keyboard').catch(() => null)
  expect(typeof module?.createChipReceiver).toBe('function')
  return module!.createChipReceiver
}

it('reads fast numeric bursts terminated by Enter without removing leading zeroes', async () => {
  const create = await factory()
  const values: string[] = []; let now = 0
  const receiver = create({ onRead: uid => values.push(uid), canRead: () => true, clock: () => now })
  for (const key of '000315346091') { receiver.keydown(new KeyboardEvent('keydown', { key })); now += 10 }
  const enter = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true })
  receiver.keydown(enter)
  expect(values).toEqual(['000315346091']); expect(enter.defaultPrevented).toBe(true)
  receiver.keydown(new KeyboardEvent('keydown', { key: 'Enter' }))
  expect(values).toHaveLength(1)
})

it('slow typing, ordinary Enter, modifiers, overflow and paused input never open a band', async () => {
  const create = await factory(); const values: string[] = []; let now = 0; let enabled = true
  const receiver = create({ onRead: uid => values.push(uid), canRead: () => enabled, clock: () => now })
  const type = (uid: string, gap: number) => { for (const key of uid) { now += gap; receiver.keydown(new KeyboardEvent('keydown', { key })) }; now += gap; receiver.keydown(new KeyboardEvent('keydown', { key: 'Enter' })) }
  type('315346091', 200)
  receiver.keydown(new KeyboardEvent('keydown', { key: 'Enter' }))
  type('1'.repeat(65), 10)
  enabled = false; type('315346091', 10); enabled = true
  receiver.keydown(new KeyboardEvent('keydown', { key: '3', ctrlKey: true })); type('123', 10)
  expect(values).toEqual([])
  type('315346091', 10); expect(values).toEqual(['315346091'])
})

it('leaving the page clears an unfinished burst and preserves normal Enter', async () => {
  const create = await factory(); const values: string[] = []; let now = 0
  const receiver = create({ onRead: uid => values.push(uid), canRead: () => true, clock: () => now })
  for (const key of '315346091') { receiver.keydown(new KeyboardEvent('keydown', { key })); now += 10 }
  receiver.reset()
  const enter = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true })
  receiver.keydown(enter); expect(values).toEqual([]); expect(enter.defaultPrevented).toBe(false)
})
