import { expect, it } from 'vitest'
import { registrationPayload, registrationIdentity, RegistrationRetry } from './registration'
const form = { username: '13800138000', display_name: '员工', role: 'floor_attendant', password: 'safe-password', confirmation: 'safe-password', code: '123456' }
it('restricts the seven-field request to desktop staff and validates ASCII inputs', () => {
  expect(registrationPayload(form, 'XS-test')).toEqual({ username: '13800138000', display_name: '员工', role: 'floor_attendant', password: 'safe-password', code: '123456', terminal_code: 'XS-test', client_channel: 'desktop' })
  for (const patch of [{username:'１３８００１３８０００'}, {role:'admin'}, {display_name:' '}, {display_name:'x'.repeat(81)}, {password:'short'}, {confirmation:'different'}, {code:'１２３４５６'}]) expect(() => registrationPayload({...form,...patch},'XS-test')).toThrow()
})
it('retries only identical data in memory and rejects unsafe success identities', () => {
  const retry = new RegistrationRetry(), body = registrationPayload(form, 'XS-test')
  const key = retry.key(body)
  expect(retry.key({...body})).toBe(key)
  expect(retry.key({...body,code:'654321'})).not.toBe(key)
  retry.clear(); expect(retry.key(body)).not.toBe(key)
  const identity = {id:'e',username:form.username,display_name:'员工',role:'floor_attendant',is_active:true,allowed_channels:['desktop']}
  expect(registrationIdentity(identity,body)).toBe(form.username)
  for (const patch of [{role:'admin'},{allowed_channels:['mobile']},{access_token:'secret'},{username:'other'},{is_active:'true'}]) expect(()=>registrationIdentity({...identity,...patch},body)).toThrow()
})
