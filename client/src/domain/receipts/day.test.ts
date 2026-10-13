import {expect,it} from 'vitest'
import {receiptDayClock} from './day'
it('uses server expiry and offset, not the local timezone or clock',()=>{
 const clock=receiptDayClock({server_time:'2026-10-11T15:59:59Z',expires_at:'2026-10-11T16:00:00Z'},100)
 expect(clock.expired(1099)).toBe(false);expect(clock.expired(1100)).toBe(true)
 expect(clock.delay(100)).toBe(1000)
})
it('an invalid clock is expired and cannot authorize reprinting',()=>{
 expect(receiptDayClock({server_time:'bad',expires_at:'bad'},100).expired(100)).toBe(true)
})
