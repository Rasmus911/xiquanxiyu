import { onBeforeUnmount, ref } from 'vue'
import type { AdmissionBand } from '../domain/wristbands/tickets'

export function useAdmissionDialog() {
  const visible = ref(false)
  const bands = ref<AdmissionBand[]>([])
  const title = ref('逐人选择门票')
  const description = ref('')
  const initial = ref<Record<string, string>>({})
  let complete: ((selection: Record<string, string> | null) => void) | undefined
  function close(selection: Record<string, string> | null = null) {
    visible.value = false
    const callback = complete
    complete = undefined
    callback?.(selection)
  }
  function open(rows: AdmissionBand[], heading: string, note = '', selected: Record<string, string> = {}) {
    close()
    bands.value = rows.map(({ id, number }) => ({ id, number }))
    title.value = heading
    description.value = note
    initial.value = { ...selected }
    return new Promise<Record<string, string> | null>(done => {
      complete = done
      visible.value = true
    })
  }
  onBeforeUnmount(() => close())
  return { visible, bands, title, description, initial, open, close }
}
