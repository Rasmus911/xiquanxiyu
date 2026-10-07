import { io, type Socket } from 'socket.io-client'
import { getApiBaseUrl, reconcileBusinessSession } from '../api/http'
import { businessGeneration, clearBusinessSession, onBusinessSessionClear } from '../business/state'
import { getAccessToken } from '../auth/session'
import { dispatchRealtimeChange, dispatchRealtimeSnapshot, domainsForSocketEvent } from '../realtime/events'
import { useConnectivityStore } from '../stores/connectivity'

let socket: Socket | null = null
let hasConnected = false
const reconcile = () => {
  const owned = socket
  const generation = businessGeneration.capture()
  if (!owned) return
  void reconcileBusinessSession().then(valid => {
    if (valid && socket === owned && businessGeneration.isCurrent(generation)) dispatchRealtimeSnapshot()
  })
}
const visible = () => { if (document.visibilityState === 'visible') reconcile() }
onBusinessSessionClear(() => stopRealtime())

export function startRealtime() {
  const connectivity = useConnectivityStore()
  if (socket) return socket
  const generation = businessGeneration.capture()

  connectivity.setRealtimeStatus('connecting')
  const socketUrl = getApiBaseUrl().replace(/\/api\/?$/, '')
  const owned = io(socketUrl, {
    auth: { token: getAccessToken() },
    transports: ['websocket', 'polling'],
  })
  socket = owned
  const current = () => socket === owned && businessGeneration.isCurrent(generation)
  window.addEventListener('focus', reconcile)
  window.addEventListener('online', reconcile)
  document.addEventListener('visibilitychange', visible)

  socket.on('connect', async () => {
    if (!current() || !await reconcileBusinessSession() || !current()) return
    connectivity.setRealtimeStatus('connected')
    if (hasConnected) dispatchRealtimeSnapshot()
    hasConnected = true
  })
  socket.on('disconnect', () => { if (current()) connectivity.setRealtimeStatus('disconnected') })
  socket.on('connect_error', () => { if (current()) { connectivity.setRealtimeStatus('disconnected'); reconcile() } })
  socket.onAny((event, payload) => {
    if (!current()) return
    if (event === 'business.reset' || event === 'session.invalidated' || event === 'access_policy.changed') {
      clearBusinessSession(); window.location.hash = '#/login'; return
    }
    if (!domainsForSocketEvent(event).length) return
    connectivity.markChanged()
    dispatchRealtimeChange(event, payload)
  })
  return socket
}

export function stopRealtime() {
  const owned = socket
  socket = null
  owned?.disconnect()
  hasConnected = false
  window.removeEventListener('focus', reconcile)
  window.removeEventListener('online', reconcile)
  document.removeEventListener('visibilitychange', visible)
  useConnectivityStore().setRealtimeStatus('disconnected')
}
