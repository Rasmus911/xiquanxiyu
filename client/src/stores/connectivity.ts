import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type RealtimeConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export const useConnectivityStore = defineStore('connectivity', () => {
  const realtimeStatus = ref<RealtimeConnectionStatus>('connecting')
  const lastConnectedAt = ref<number | null>(null)
  const lastChangedAt = ref<number | null>(null)
  const isOnline = computed(() => realtimeStatus.value === 'connected')

  function setRealtimeStatus(status: RealtimeConnectionStatus) {
    realtimeStatus.value = status
    if (status === 'connected') lastConnectedAt.value = Date.now()
  }

  function markChanged() {
    lastChangedAt.value = Date.now()
  }

  return {
    isOnline,
    lastChangedAt,
    lastConnectedAt,
    markChanged,
    realtimeStatus,
    setRealtimeStatus,
  }
})
