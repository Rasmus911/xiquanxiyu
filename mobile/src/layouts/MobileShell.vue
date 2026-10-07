<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted } from 'vue'
import { App as CapacitorApp } from '@capacitor/app'
import { useRoute, useRouter } from 'vue-router'
import MobileBottomNav from '../components/navigation/MobileBottomNav.vue'
import { connectRealtime, disconnectRealtime } from '../composables/useRealtime'
import { useBootstrap } from '../composables/useBootstrap'
import { useBusinessStore } from '../stores/business'
import { updateRequiredKey } from '../update/context'
import { businessGeneration, permissions } from '../business/state'
import { scopedMobileCapabilities } from '../mobile-management'
import { mobileLanding } from '../router/access'
import { useSessionStore } from '../stores/session'

const route = useRoute(); const router = useRouter(); const business = useBusinessStore(); const bootstrap = useBootstrap()
const updateRequired = inject(updateRequiredKey)
let backHandle: Awaited<ReturnType<typeof CapacitorApp.addListener>> | null = null
let active = true
onMounted(async () => {
  const generation = businessGeneration.capture()
  if (!await bootstrap.initialise().catch(() => false) || !active || !businessGeneration.isCurrent(generation)) return
  connectRealtime()
  backHandle = await CapacitorApp.addListener('backButton', () => {
    if (!active || !businessGeneration.isCurrent(generation)) return
    if (updateRequired?.value || business.businessBusy) return
    const event = new Event('xiquan:back-request', { cancelable: true })
    if (!document.dispatchEvent(event)) return
    const landing = mobileLanding(scopedMobileCapabilities(useSessionStore().employee?.capabilities, permissions.value))
    if (route.path !== landing) void router.replace(landing)
    else if (window.confirm('确认退出溪泉移动点单端？')) void CapacitorApp.exitApp()
  })
  if (!active || !businessGeneration.isCurrent(generation)) void backHandle.remove()
})
onBeforeUnmount(() => { active = false; void backHandle?.remove(); disconnectRealtime() })
</script>
<template><div class="mobile-shell"><main><router-view /></main><MobileBottomNav /></div></template>
