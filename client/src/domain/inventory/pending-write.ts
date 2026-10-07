import { shallowRef } from 'vue'
import { onBusinessSessionClear } from '../../business/state'

export interface PendingStockWrite {
  scope: string
  fingerprint: string
  body: Record<string, unknown>
  key: string
  method: 'post' | 'patch' | 'delete'
  url: string
}
// Like visit ordering, retain an uncertain write while navigating between pages.
export const pendingStockWrite = shallowRef<PendingStockWrite>()
onBusinessSessionClear(() => { pendingStockWrite.value = undefined })
