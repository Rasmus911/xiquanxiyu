export type Quantities = Record<string, number>
import type { ManualConsumption } from '../../types'
export interface SubmissionSnapshot {
  visitId: string
  visitVersion: number
  quantities: Readonly<Quantities>
  units: number
  kinds: number
  confirmReplace?: boolean
  consumptions?: Readonly<Record<string, readonly ManualConsumption[]>>
}
export class VisitDraftBook {
  private values = new Map<string, Quantities>()
  read(id: string): Quantities { return { ...this.values.get(id) } }
  replace(id: string, values: Quantities) { this.values.set(id, { ...values }) }
  clear(id?: string) { if (id === undefined) this.values.clear(); else this.values.delete(id) }
  capture(visitId: string, visitVersion: number): SubmissionSnapshot {
    const quantities = Object.freeze(this.read(visitId))
    const values = Object.values(quantities).filter(value => value > 0)
    return Object.freeze({ visitId, visitVersion, quantities, units: values.reduce((sum, value) => sum + value, 0), kinds: values.length })
  }
}
