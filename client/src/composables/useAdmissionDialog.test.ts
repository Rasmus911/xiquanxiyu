import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { useAdmissionDialog } from './useAdmissionDialog'

it('a new choice cancels the prior promise; closing resolves only the latest immutable rows', async () => {
  let dialog!: ReturnType<typeof useAdmissionDialog>
  const wrapper=mount({setup(){dialog=useAdmissionDialog();return ()=>null}})
  try {
    const rows=[{id:'a',number:'001'}]
    const first=dialog.open(rows,'开牌')
    rows[0]!.id='tampered'
    expect(dialog.bands.value[0]?.id).toBe('a')
    const second=dialog.open([{id:'b',number:'051'}],'第二位')
    await expect(first).resolves.toBeNull()
    dialog.close({b:'child'})
    await expect(second).resolves.toEqual({b:'child'})
    expect(dialog.visible.value).toBe(false)
  } finally {wrapper.unmount()}
})
it('page teardown cancels an unanswered dialog without leaving an unresolved command', async () => {
  let dialog!: ReturnType<typeof useAdmissionDialog>
  const wrapper=mount({setup(){dialog=useAdmissionDialog();return ()=>null}})
  const result=dialog.open([{id:'a',number:'001'}],'开牌')
  wrapper.unmount()
  await expect(result).resolves.toBeNull()
})
