import { io, type Socket } from 'socket.io-client'
import { getApiBaseUrl, reconcileBusinessSession } from '../api'
import { businessGeneration, clearBusinessSession, onBusinessSessionClear } from '../business/state'
import { getAccessToken } from '../session'
import { refreshDomainsForEvent, type MobileRefreshDomain } from '../realtime/events'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'

let socket: Socket | null = null
let refreshTimer = 0
let fallbackTimer = 0
let pending = new Set<MobileRefreshDomain>()
onBusinessSessionClear(() => disconnectRealtime())
const reconcile = () => {
  const owned = socket
  const generation = businessGeneration.capture()
  if (!owned) return
  void reconcileBusinessSession().then(valid => {
    if (valid && socket === owned && businessGeneration.isCurrent(generation)) schedule(['orders', 'reports', 'inventory'])
  })
}
const visible = () => { if (document.visibilityState === 'visible') reconcile() }
const tokenRefreshed = () => { if (socket) { disconnectRealtime(); connectRealtime() } }

async function flushRefresh() {
  const generation = businessGeneration.capture()
  const domains = [...pending]
  pending = new Set()
  if (!await reconcileBusinessSession() || !businessGeneration.isCurrent(generation)) return
  await useBusinessStore().refreshDomains(domains, true)
}

function schedule(domains: MobileRefreshDomain[]) {
  domains.forEach((domain) => pending.add(domain))
  window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(flushRefresh, 350)
}

export function connectRealtime() {
  if (socket || !getAccessToken()) return
  const generation = businessGeneration.capture()
  const connectivity = useConnectivityStore()
  const owned = io(getApiBaseUrl().replace(/\/api\/?$/, ''), {
    auth: { token: getAccessToken() }, transports: ['websocket', 'polling'], reconnection: true,
  })
  socket = owned
  const current = () => socket === owned && businessGeneration.isCurrent(generation)
  window.addEventListener('focus', reconcile)
  window.addEventListener('online', reconcile)
  window.addEventListener('xiquan:token-refreshed', tokenRefreshed)
  document.addEventListener('visibilitychange', visible)
  socket.on('business.reset', () => { if (current()) { clearBusinessSession(); window.dispatchEvent(new Event('xiquan:logged-out')) } })
  socket.on('session.invalidated', () => { if (current()) { clearBusinessSession(); window.dispatchEvent(new Event('xiquan:logged-out')) } })
  socket.on('access_policy.changed', () => { if (current()) { clearBusinessSession(); window.dispatchEvent(new Event('xiquan:logged-out')) } })
  socket.on('connect', async () => {
    if (!current() || !await reconcileBusinessSession() || !current()) return
    connectivity.socketConnected = true
    schedule(['orders', 'inventory', 'reports'])
  })
  socket.on('disconnect', () => { if (current()) connectivity.socketConnected = false })
  socket.on('connect_error', () => { if (current()) { connectivity.socketConnected = false; reconcile() } })
  for (const event of ['wristbands.changed', 'visit.changed', 'catalog.changed', 'inventory.changed', 'checkout.completed', 'checkout.refunded', 'member.changed']) {
    socket.on(event, () => { if (current()) schedule(refreshDomainsForEvent(event)) })
  }
  window.clearInterval(fallbackTimer)
  fallbackTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !connectivity.socketConnected) {
      schedule(['orders', 'reports', 'inventory'])
    }
  }, 15000)
}

export function disconnectRealtime() {
  const owned = socket; socket = null; owned?.disconnect()
  window.clearInterval(fallbackTimer)
  window.clearTimeout(refreshTimer)
  pending = new Set()
  window.removeEventListener('focus', reconcile)
  window.removeEventListener('online', reconcile)
  window.removeEventListener('xiquan:token-refreshed', tokenRefreshed)
  document.removeEventListener('visibilitychange', visible)
  useConnectivityStore().socketConnected = false
}
