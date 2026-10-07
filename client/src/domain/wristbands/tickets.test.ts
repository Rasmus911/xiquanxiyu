import { expect, it } from 'vitest'
import { admissionChoices, initialTicketSelection, ticketSelectionPayload } from './tickets'
import type { CatalogItem } from '../../types'

const items = [
  { id: 'adult', kind: 'ticket', reference_code: 'ticket.adult', name: '门票', price: '15.00', is_active: true },
  { id: 'child', kind: 'ticket', reference_code: 'ticket.child', name: '儿童门票（一米以下）', price: '10.00', is_active: true },
  { id: 'scrub', kind: 'service', reference_code: 'bath.scrub', name: '搓澡', price: '10.00', is_active: true },
] as CatalogItem[]
const bands = [{ id: 'male', number: '001' }, { id: 'female', number: '051' }]

it('defaults each new guest to adult and sends only per-UUID server ticket IDs', () => {
  const choices = admissionChoices(items)
  expect(choices.map(row => row.id)).toEqual(['adult', 'child'])
  const selected = initialTicketSelection(bands, choices)
  selected.female = 'child'
  expect(ticketSelectionPayload(bands, choices, selected)).toEqual({ male: 'adult', female: 'child' })
})
it('does not grant admission authority to a service ID or silently skip a guest', () => {
  const choices = admissionChoices(items)
  expect(() => ticketSelectionPayload(bands, choices, { male: 'adult' })).toThrow()
  expect(() => ticketSelectionPayload(bands, choices, { male: 'adult', female: 'scrub' })).toThrow()
  expect(() => ticketSelectionPayload(bands, choices, { male: 'adult', female: 'child', extra: 'adult' })).toThrow()
})
it('requires an active unambiguous adult option and does not invent its price', () => {
  expect(() => initialTicketSelection(bands, admissionChoices(items.map(row => ({ ...row, is_active: row.id !== 'adult' }))))).toThrow()
  expect(() => admissionChoices([...items, { ...items[0], id: 'duplicate' } as CatalogItem])).toThrow()
  expect(admissionChoices([{ ...items[0], price: '18.00' } as CatalogItem])[0]?.price).toBe('18.00')
})
