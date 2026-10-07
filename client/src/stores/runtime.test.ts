import { expect, test } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { clearBusinessSession } from '../business/state'
import { useRuntimeStore } from './runtime'
test('delayed bridge busy state cannot replace a newer session busy state', async () => {
  setActivePinia(createPinia())
  let finish!: () => void
  window.xiquan = { setBusinessBusy: (reason: string | null) => reason === null ? Promise.resolve({ businessBusyReason: null }) : new Promise(resolve => { finish = () => resolve({ businessBusyReason: 'old' } as UpdateState) }) } as unknown as NonNullable<Window['xiquan']>
  const runtime = useRuntimeStore()
  const old = runtime.setBusinessBusy('old')
  clearBusinessSession()
  runtime.businessBusyReason = 'new'
  finish(); await old
  expect(runtime.updateState?.businessBusyReason).not.toBe('old')
  expect(runtime.businessBusyReason).toBe('new')
  delete window.xiquan
})
test('an old busy finalizer cannot release a replacement operation', async () => {
  setActivePinia(createPinia())
  const runtime = useRuntimeStore()
  const releaseOld = await runtime.setBusinessBusy('old')
  await runtime.setBusinessBusy('new')
  await releaseOld?.()
  expect(runtime.businessBusyReason).toBe('new')
  expect(releaseOld).toBeTypeOf('function')
})
