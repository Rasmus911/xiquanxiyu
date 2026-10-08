export interface TokenSnapshot { code: string; generation: number; server_time: string; expires_at: string }
export interface TokenState { snapshot: TokenSnapshot; baseline: number; lifetime: number }
export function acceptTokenSnapshot(snapshot: TokenSnapshot, monotonicNow: number): TokenState {
  const lifetime = Date.parse(snapshot?.expires_at) - Date.parse(snapshot?.server_time)
  if (!snapshot || !/^[0-9]{6}$/.test(snapshot.code) || !Number.isSafeInteger(snapshot.generation) || snapshot.generation < 1
    || !Number.isFinite(monotonicNow) || !Number.isFinite(lifetime) || lifetime <= 0 || lifetime > 180000
    || !/Z$|\+00:00$/.test(snapshot.server_time) || !/Z$|\+00:00$/.test(snapshot.expires_at)) throw new Error('授权码信息已失效，请重新查询')
  return { snapshot: { ...snapshot }, baseline: monotonicNow, lifetime }
}
export function tokenDisplay(state: TokenState | null, monotonicNow: number) {
  const elapsed = state ? monotonicNow - state.baseline : -1
  const remaining = state && Number.isFinite(elapsed) && elapsed >= 0 ? state.lifetime - elapsed : 0
  return { code: remaining > 0 ? state!.snapshot.code : '', remainingSeconds: Math.max(0, Math.ceil(remaining / 1000)) }
}
export class TokenRequests {
  private ownership = 0
  private generation = 0
  begin() { return ++this.ownership }
  invalidate() { this.ownership++ }
  accept(request: number, snapshot: TokenSnapshot, monotonicNow: number) {
    if (request !== this.ownership || snapshot.generation < this.generation) return null
    const state = acceptTokenSnapshot(snapshot, monotonicNow)
    this.generation = snapshot.generation
    return state
  }
}
