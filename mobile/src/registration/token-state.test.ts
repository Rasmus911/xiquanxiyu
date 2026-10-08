import { expect, it } from 'vitest'
import { acceptTokenSnapshot, tokenDisplay, TokenRequests } from './token-state'
const snapshot={code:'123456',generation:1,server_time:'2026-10-08T00:00:00Z',expires_at:'2026-10-08T00:03:00Z'}
it('expired token is never displayed as usable and uses monotonic elapsed time',()=>{
  const state=acceptTokenSnapshot(snapshot,1000)
  expect(tokenDisplay(state,180999).remainingSeconds).toBe(1)
  expect(tokenDisplay(state,181000).code).toBe('')
  expect(tokenDisplay(state,999).code).toBe('')
})
it('rejects invalid snapshots and generation rollback or obsolete ownership',()=>{
  for(const patch of [{code:'１２３４５６'},{generation:0},{server_time:'bad'},{expires_at:snapshot.server_time},{expires_at:'2026-10-08T00:04:00Z'}])expect(()=>acceptTokenSnapshot({...snapshot,...patch},1000)).toThrow()
  const requests=new TokenRequests(),old=requests.begin();requests.invalidate();expect(requests.accept(old,snapshot,0)).toBeNull()
  const current=requests.begin();expect(requests.accept(current,{...snapshot,generation:2},0)).not.toBeNull();expect(requests.accept(requests.begin(),snapshot,0)).toBeNull()
})
