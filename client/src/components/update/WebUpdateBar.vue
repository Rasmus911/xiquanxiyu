<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRuntimeStore } from '../../stores/runtime'
import { normalizeWebRelease, webUpdateDecision, type WebReleasePolicy } from '../../update/web-version'

const CHECK_INTERVAL_MS = 15 * 60 * 1000
const runtime = useRuntimeStore()
const remote = ref<WebReleasePolicy | null>(null)
const checking = ref(false)
let timer = 0

const browserMode = computed(() => !window.xiquan)
const decision = computed(() => remote.value
  ? webUpdateDecision(__XIQUAN_BUILD_ID__, remote.value, runtime.businessBusyReason)
  : 'none')
const visible = computed(() => browserMode.value && decision.value !== 'none')
const buttonLabel = computed(() => decision.value === 'deferred' ? '操作完成后刷新' : '刷新到最新版')

async function check() {
  if (!browserMode.value || checking.value) return
  checking.value = true
  try {
    const response = await fetch('/app/version.json', { cache: 'no-store' })
    if (!response.ok) return
    remote.value = normalizeWebRelease(await response.json())
  } catch {
    // A temporary version endpoint failure must never interrupt the cashier UI.
  } finally {
    checking.value = false
  }
}

function refresh() {
  if (decision.value === 'deferred') return
  location.reload()
}

function onFocus() { void check() }

onMounted(() => {
  if (!browserMode.value) return
  void check()
  window.addEventListener('focus', onFocus)
  timer = window.setInterval(check, CHECK_INTERVAL_MS)
})

onBeforeUnmount(() => {
  window.removeEventListener('focus', onFocus)
  window.clearInterval(timer)
})
</script>

<template>
  <transition name="web-update">
    <aside v-if="visible" class="web-update-bar" :class="decision">
      <div class="update-dot">↑</div>
      <div>
        <strong>{{ decision === 'required' ? '系统需要刷新到最新版' : '云端已发布新版本' }}</strong>
        <span v-if="decision === 'deferred'">{{ runtime.businessBusyReason }}，系统不会中断当前操作</span>
        <span v-else>{{ remote?.releaseNotes[0] || '刷新后即可使用最新功能' }}</span>
      </div>
      <button :disabled="decision === 'deferred'" @click="refresh">{{ buttonLabel }}</button>
    </aside>
  </transition>
</template>

<style scoped>
.web-update-bar { position: fixed; z-index: 120; top: 14px; left: 50%; width: min(680px, calc(100vw - 32px)); transform: translateX(-50%); display: grid; grid-template-columns: 38px 1fr auto; align-items: center; gap: 12px; padding: 11px 12px; border: 1px solid #cce7df; border-radius: 15px; color: #193b36; background: rgba(239, 252, 248, .97); box-shadow: 0 16px 42px rgba(30, 71, 78, .18); backdrop-filter: blur(12px); }
.web-update-bar.required { border-color: #f1c99a; color: #5b3415; background: rgba(255, 248, 237, .98); }
.web-update-bar.deferred { border-color: #d9dee8; color: #445064; background: rgba(248, 250, 253, .98); }
.update-dot { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 12px; color: white; background: var(--xq-primary); font-size: 20px; font-weight: 900; }
.web-update-bar strong, .web-update-bar span { display: block; }
.web-update-bar span { margin-top: 2px; color: #708075; font-size: 12px; }
.web-update-bar button { min-height: 36px; padding: 0 14px; border: 0; border-radius: 10px; color: white; background: #238f80; font-weight: 700; cursor: pointer; }
.web-update-bar button:disabled { color: #8892a2; background: #e5e9f0; cursor: not-allowed; }
.web-update-enter-active, .web-update-leave-active { transition: .22s ease; }
.web-update-enter-from, .web-update-leave-to { opacity: 0; transform: translate(-50%, -12px); }
</style>
