import { defineStore } from 'pinia'
import { ref } from 'vue'
import { businessGeneration, onBusinessSessionClear } from '../business/state'

export const useRuntimeStore = defineStore('runtime', () => {
  const businessBusyReason = ref<string | null>(null)
  const updateState = ref<UpdateState | null>(null)
  const updateCenterVisible = ref(false)
  let busyOperation = 0
  onBusinessSessionClear(() => { businessBusyReason.value = null; busyOperation++; void window.xiquan?.setBusinessBusy(null).catch(() => undefined) })

  async function setBusinessBusy(reason: string | null) {
    const generation = businessGeneration.capture(); const owned = ++busyOperation
    businessBusyReason.value = reason
    try {
      if (window.xiquan) {
        const state = await window.xiquan.setBusinessBusy(reason)
        if (businessGeneration.isCurrent(generation) && busyOperation === owned) updateState.value = state
      }
    } catch (error) {
      if (businessGeneration.isCurrent(generation) && busyOperation === owned) console.error('Failed to synchronize desktop busy state.', error)
    }
    // Payment pages may navigate away before their finally runs. The release
    // belongs to this operation, not whichever page or session is now active.
    return async () => {
      if (businessGeneration.isCurrent(generation) && busyOperation === owned) await setBusinessBusy(null)
    }
  }

  function setUpdateState(value: UpdateState) {
    updateState.value = value
    businessBusyReason.value = value.businessBusyReason
  }

  function openUpdateCenter() {
    updateCenterVisible.value = true
  }

  function closeUpdateCenter() {
    updateCenterVisible.value = false
  }

  return {
    businessBusyReason,
    closeUpdateCenter,
    openUpdateCenter,
    setBusinessBusy,
    setUpdateState,
    updateCenterVisible,
    updateState,
  }
})
