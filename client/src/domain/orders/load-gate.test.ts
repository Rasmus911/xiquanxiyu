import { expect, it } from 'vitest'
import { createVisitLoadGate } from './load-gate'

it('only the latest request for the selected UUID may complete', () => {
  const gate = createVisitLoadGate()
  const a = gate.begin('a'); const b = gate.begin('b')
  expect(gate.current(a)).toBe(false)
  expect(gate.current(b)).toBe(true)
  gate.reset()
  expect(gate.current(b)).toBe(false)
})
