<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { App } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'
import { dataOf, errorMessage, http } from '../api'
import { businessGeneration, onBusinessSessionClear } from '../business/state'
import { useSessionStore } from '../stores/session'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import { tokenDisplay, TokenRequests, type TokenSnapshot, type TokenState } from '../registration/token-state'

const session = useSessionStore(), route = useRoute(), router = useRouter()
const account = session.employee?.id, path = route.fullPath, generation = businessGeneration.capture()
const state = shallowRef<TokenState | null>(null), now = ref(performance.now())
const notice = ref('正在查询注册授权码…'), pending = ref(false)
const requests = new TokenRequests()
let active = true, foreground = !Capacitor.isNativePlatform(), online = navigator.onLine, nativeStateObserved = false
let lastQuery = -Infinity, timer: ReturnType<typeof setInterval> | undefined
let removeNative: (() => Promise<void>) | undefined
const display = computed(() => tokenDisplay(state.value, now.value))
const authorized = () => session.authenticated && session.employee?.id === account && session.employee?.capabilities?.registration_token_view === true && businessGeneration.isCurrent(generation)
const visible = () => active && foreground && document.visibilityState === 'visible' && route.fullPath === path
function clear(message: string) { requests.invalidate(); state.value = null; notice.value = message }
onBusinessSessionClear(() => clear('登录状态已变化，请重新登录后查询'))
watch([() => session.authenticated, () => session.employee?.id, () => session.employee?.capabilities?.registration_token_view], () => clear('账号或授权已变化，请返回我的重新进入'), { flush: 'sync' })
watch(() => route.fullPath, () => clear('已离开授权码页面'), { flush: 'sync' })

async function query() {
  if (pending.value || !visible() || !online || !authorized()) return
  const owned = requests.begin(), started = performance.now()
  lastQuery = started; pending.value = true
  try {
    const snapshot = dataOf<TokenSnapshot>(await http.post('/auth/registration-token/current', {}, { headers: { 'Cache-Control': 'no-store' } }))
    if (!visible() || !online || !authorized()) return
    // Subtract the full request duration conservatively; phone wall time is never authoritative.
    const accepted = requests.accept(owned, snapshot, started)
    if (!accepted) { clear('授权码信息已变化，请重新查询'); return }
    now.value = performance.now()
    if (!tokenDisplay(accepted, now.value).code) { clear('授权码已过期，请重新查询'); return }
    state.value = accepted; notice.value = ''
  } catch (error) {
    if (active && visible() && authorized()) clear(`无法查询授权码：${errorMessage(error)}。请检查网络后重试`)
  } finally { pending.value = false }
}
function visibility() {
  if (!visible()) clear('应用已进入后台，返回后将重新查询')
  else { clear('正在重新查询注册授权码…'); void query() }
}
function offline() { online = false; clear('网络已断开，请联网后重新查询') }
function connected() { online = true; clear('正在重新查询注册授权码…'); void query() }
onMounted(async () => {
  document.addEventListener('visibilitychange', visibility)
  window.addEventListener('offline', offline); window.addEventListener('online', connected)
  timer = setInterval(() => {
    now.value = performance.now()
    if (!authorized()) { clear('无权查看注册授权码，请重新登录或联系管理员'); return }
    if (!visible()) { clear('应用已进入后台，返回后将重新查询'); return }
    if (state.value && !display.value.code) clear('授权码已过期，请重新查询')
    if (now.value - lastQuery >= 5000) void query()
  }, 250)
  if (Capacitor.isNativePlatform()) {
    try {
      const handle = await App.addListener('appStateChange', ({ isActive }) => { nativeStateObserved = true; foreground = isActive; visibility() })
      if (!active) { await handle.remove(); return }
      removeNative = () => handle.remove()
      const appState = await App.getState()
      if (!active) return
      if (!nativeStateObserved) foreground = appState.isActive
    } catch { clear('无法确认应用前台状态，请返回我的后重新进入'); return }
  }
  if (!authorized()) clear('无权查看注册授权码，请重新登录或联系管理员')
  else if (!online) offline()
  else void query()
})
onBeforeUnmount(() => {
  active = false; clear(''); if (timer) clearInterval(timer)
  document.removeEventListener('visibilitychange', visibility)
  window.removeEventListener('offline', offline); window.removeEventListener('online', connected)
  void removeNative?.()
})
</script>

<template>
  <div>
    <MobileTopbar title="注册授权码" subtitle="用于批准桌面员工账号注册" back @back="router.push('/profile')" />
    <main class="mobile-page">
      <section class="mobile-card token-card">
        <p>请将授权码提供给需要注册的员工</p>
        <template v-if="display.code"><strong class="token-code" data-testid="registration-token">{{ display.code }}</strong><p>剩余 {{ display.remainingSeconds }} 秒 · 注册成功后立即更换</p></template>
        <p v-else class="notice" role="status">{{ notice }}</p>
        <p>授权码不是短信验证码，也不验证手机号归属。新员工账号仅限桌面查看手牌和点单。</p>
        <button class="outline-button" :disabled="pending" @click="query">{{ pending ? '查询中…' : '重新查询' }}</button>
      </section>
    </main>
  </div>
</template>
<style scoped>.token-card{text-align:center}.token-code{display:block;font-size:46px;font-weight:900;letter-spacing:8px;color:var(--m-primary)}.token-card p{line-height:1.7;color:var(--m-text-3)}.outline-button{width:100%;min-height:48px;border:1px solid var(--m-primary);border-radius:13px;background:white;color:var(--m-primary);font-weight:800}</style>
