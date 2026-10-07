import { onBusinessSessionClear } from '../../business/state'

interface DashboardReturn { area: 'all' | 'male' | 'female'; keyword: string; scrollTop: number }
let current: DashboardReturn | null = null
export function saveDashboardReturn(state: DashboardReturn) { current = { ...state } }
export function readDashboardReturn() { return current ? { ...current } : null }
export function clearDashboardReturn() { current = null }
onBusinessSessionClear(clearDashboardReturn)
