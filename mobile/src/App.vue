<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UpdateGate from './components/UpdateGate.vue'
import NetworkBanner from './components/navigation/NetworkBanner.vue'
import { getInstalledBuildNumber, onAppResume } from './native'
import { useBusinessStore } from './stores/business'
import { useConnectivityStore } from './stores/connectivity'
import { useSessionStore } from './stores/session'
import { reconcileBusinessSession } from './api'
import { businessGeneration, sessionEpoch } from './business/state'
import {
  decideAndroidUpdate,
  normalizeAndroidPolicy,
  type AndroidReleasePolicy,
  type AndroidUpdateDecision,
} from './update/release-policy'
import { updateRequiredKey } from './update/context'

const RELEASE_POLICY_URL = 'https://api.pqxqxy.xyz/releases/client-policy.json'
const DOWNLOAD_CONFIG_URL = 'https://api.pqxqxy.xyz/mobile/download-config.json'

const route = useRoute()
const router = useRouter()
const business = useBusinessStore()
const connectivity = useConnectivityStore()
const session = useSessionStore()
const policy = ref<AndroidReleasePolicy | null>(null)
const decision = ref<AndroidUpdateDecision>('none')
const updateRequired = computed(() => decision.value === 'required')
let removeResume: (() => Promise<void>) | null = null
let active = true
provide(updateRequiredKey, updateRequired)

const showNetworkBanner = computed(() => (
  session.authenticated && !['login', 'download'].includes(String(route.name))
))

async function readReleasePolicy() {
  let payload: unknown
  try {
    const response = await fetch(RELEASE_POLICY_URL, { cache: 'no-store' })
    if (!response.ok) throw new Error(`RELEASE_POLICY_${response.status}`)
    const document = await response.json() as { schemaVersion?: number; android?: unknown }
    payload = document.schemaVersion === 1 ? document.android : null
  } catch {
    const response = await fetch(DOWNLOAD_CONFIG_URL, { cache: 'no-store' })
    if (!response.ok) return null
    payload = await response.json()
  }
  return normalizeAndroidPolicy(payload)
}

async function checkForUpdate() {
  try {
    const next = await readReleasePolicy()
    policy.value = next
    decision.value = next
      ? decideAndroidUpdate(await getInstalledBuildNumber(), next)
      : 'none'
  } catch {
    policy.value = null
    decision.value = 'none'
  }
}

function updateBrowserConnectivity() {
  connectivity.browserOnline = navigator.onLine
  if (navigator.onLine && session.authenticated) {
    const generation = businessGeneration.capture()
    void reconcileBusinessSession().then(valid => {
      if (valid && active && businessGeneration.isCurrent(generation)) void business.refreshBootstrap(true).catch(() => undefined)
    })
  }
}

function handleLoggedOut() {
  if (!['login', 'download'].includes(String(route.name))) void router.replace('/login')
}

function requestUpdateCheck() { void checkForUpdate() }

onMounted(async () => {
  window.addEventListener('online', updateBrowserConnectivity)
  window.addEventListener('offline', updateBrowserConnectivity)
  window.addEventListener('xiquan:logged-out', handleLoggedOut)
  window.addEventListener('xiquan:session-cleared', handleLoggedOut)
  window.addEventListener('xiquan:check-update', requestUpdateCheck)
  await checkForUpdate()
  if (!active) return
  removeResume = await onAppResume(async () => {
    const generation = businessGeneration.capture()
    await checkForUpdate()
    if (!active || !businessGeneration.isCurrent(generation) || !session.authenticated) return
    if (await reconcileBusinessSession() && active && businessGeneration.isCurrent(generation)) await business.refreshBootstrap(true).catch(() => undefined)
  })
  if (!active) void removeResume()
})

onBeforeUnmount(() => {
  active = false
  window.removeEventListener('online', updateBrowserConnectivity)
  window.removeEventListener('offline', updateBrowserConnectivity)
  window.removeEventListener('xiquan:logged-out', handleLoggedOut)
  window.removeEventListener('xiquan:session-cleared', handleLoggedOut)
  window.removeEventListener('xiquan:check-update', requestUpdateCheck)
  if (removeResume) void removeResume()
})
</script>

<template>
  <UpdateGate :policy="policy" :decision="decision" :business-busy="business.businessBusy" />
  <NetworkBanner v-if="showNetworkBanner" />
  <router-view :key="['login', 'download'].includes(String(route.name)) ? String(route.name) : sessionEpoch" />
</template>
