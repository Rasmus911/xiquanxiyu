import type { CatalogItem } from '../../types'

export interface AdmissionBand { id: string; number: string }
export function admissionChoices(items: CatalogItem[]) {
  const choices = items.filter(row => row.kind === 'ticket' && row.is_active &&
    ['ticket.adult', 'ticket.child'].includes(row.reference_code || ''))
  if (new Set(choices.map(row => row.reference_code)).size !== choices.length)
    throw new Error('票种配置重复，请先核对项目')
  return choices.sort((a, b) => (a.reference_code === 'ticket.adult' ? 0 : 1) - (b.reference_code === 'ticket.adult' ? 0 : 1))
}
export function initialTicketSelection(bands: AdmissionBand[], tickets: CatalogItem[]) {
  const adult = tickets.find(row => row.reference_code === 'ticket.adult')
  if (!adult) throw new Error('成人门票尚未配置，请先完成正式价目表切换')
  return Object.fromEntries(bands.map(row => [row.id, adult.id])) as Record<string, string>
}
export function ticketSelectionPayload(bands: AdmissionBand[], tickets: CatalogItem[], selected: Record<string, string>) {
  const allowed = new Set(tickets.map(row => row.id))
  if (Object.keys(selected).length !== bands.length || bands.some(row => !allowed.has(selected[row.id] || '')))
    throw new Error('请为每张新手牌选择有效门票')
  return Object.fromEntries(bands.map(row => [row.id, selected[row.id]])) as Record<string, string>
}
