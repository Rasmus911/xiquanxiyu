// @vitest-environment jsdom
import { beforeEach, expect, it } from 'vitest'
import { effectScope } from 'vue'
import { http } from '../api/http'
import { clearBusinessSession } from '../business/state'
import { useCatalogLayout } from './useCatalogLayout'

beforeEach(() => clearBusinessSession())
it('cancel never saves, conflict preserves edits and double save has one request', async () => {
  let writes = 0; let fail = true; const bodies: any[] = []
  http.defaults.adapter = async config => {
    if (config.method === 'put') {
      writes++; bodies.push(JSON.parse(config.data))
      if (fail) throw new Error('排列已改变')
    }
    return { config, headers: {}, status: 200, statusText: '', data: { data: {
      revision: config.method === 'put' ? 5 : 4, ids: config.method === 'put' ? JSON.parse(config.data).ids : ['scrub', 'towel', 'mud'],
    } } }
  }
  const scope = effectScope(); const layout = scope.run(() => useCatalogLayout())!
  try {
    await layout.begin(); layout.move('mud', 'towel'); layout.cancel()
    expect(writes).toBe(0)
    await layout.begin(); layout.move('mud', 'towel')
    await Promise.all([layout.save(), layout.save()])
    expect(writes).toBe(1); expect(layout.editing.value).toBe(true)
    expect(layout.ids.value).toEqual(['scrub', 'mud', 'towel'])
    fail = false; await layout.save()
    expect(bodies[1]).toEqual({ revision: 4, ids: ['scrub', 'mud', 'towel'] })
    expect(layout.revision.value).toBe(5); expect(layout.editing.value).toBe(false)
  } finally { scope.stop() }
})
it('old layout request cannot refill a new session', async () => {
  let finish!: () => void
  http.defaults.adapter = config => new Promise(resolve => { finish = () => resolve({
    config, headers: {}, status: 200, statusText: '', data: { data: { revision: 1, ids: ['old'] } },
  }) })
  const scope = effectScope(); const layout = scope.run(() => useCatalogLayout())!
  try {
    const old = layout.begin(); clearBusinessSession(); finish(); await old
    expect(layout.ids.value).toEqual([]); expect(layout.editing.value).toBe(false)
  } finally { scope.stop() }
})
