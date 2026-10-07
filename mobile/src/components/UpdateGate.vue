<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isNativeAndroidApp, openExternal } from '../native'
import type { AndroidReleasePolicy, AndroidUpdateDecision } from '../update/release-policy'
import { ApkUpdater, type PluginListenerHandle } from '../update/native-updater'
import { initialNativeUpdateState, reduceUpdater } from '../update/updater-state'

const DOWNLOAD_PAGE_URL = 'https://api.pqxqxy.xyz/mobile/download'
const props = defineProps<{
  policy: AndroidReleasePolicy | null
  decision: AndroidUpdateDecision
  businessBusy: string | null
}>()

const dismissedVersionCode = ref<number | null>(null)
const state = ref(initialNativeUpdateState())
let progressHandle: PluginListenerHandle | null = null

const required = computed(() => props.decision === 'required')
const visible = computed(() => {
  if (!props.policy || props.decision === 'none') return false
  return required.value || dismissedVersionCode.value !== props.policy.latestVersionCode
})
const nativeAndroid = computed(() => isNativeAndroidApp())
const busyMessage = computed(() => props.businessBusy ? `${props.businessBusy}，完成后即可更新` : '')
const actionLabel = computed(() => {
  if (!nativeAndroid.value) return '打开最新版下载页'
  if (state.value.status === 'downloading') return `正在下载 ${state.value.percent}%`
  if (state.value.status === 'downloaded') return '安装最新版'
  if (state.value.status === 'needs-install-permission') return '允许安装后继续'
  if (state.value.status === 'installing') return '再次打开安装确认'
  if (state.value.status === 'error') return '重新下载'
  return '应用内下载并更新'
})
const actionDisabled = computed(() => Boolean(props.businessBusy) || state.value.status === 'downloading')

function dismiss() {
  if (required.value || !props.policy) return
  dismissedVersionCode.value = props.policy.latestVersionCode
}

async function installDownloaded() {
  if (!state.value.path || props.businessBusy) return
  const permission = await ApkUpdater.canInstallPackages()
  if (!permission.allowed) {
    state.value = reduceUpdater(state.value, { type: 'permission-required' })
    return
  }
  state.value = reduceUpdater(state.value, { type: 'installing' })
  try {
    await ApkUpdater.install({ path: state.value.path || '' })
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    if (text.includes('INSTALL_PERMISSION_REQUIRED')) {
      state.value = reduceUpdater(state.value, { type: 'permission-required' })
    } else {
      state.value = reduceUpdater(state.value, { type: 'error', message: text })
    }
  }
}

async function primaryAction() {
  if (!props.policy || actionDisabled.value) return
  if (!nativeAndroid.value) {
    await openExternal(DOWNLOAD_PAGE_URL)
    return
  }
  if (state.value.status === 'needs-install-permission') {
    await ApkUpdater.openInstallSettings()
    return
  }
  if (['downloaded', 'installing'].includes(state.value.status)) {
    await installDownloaded()
    return
  }

  const previousPath = state.value.path
  state.value = reduceUpdater(initialNativeUpdateState(), { type: 'progress', percent: 0 })
  try {
    if (previousPath) await ApkUpdater.clearDownload({ path: previousPath }).catch(() => undefined)
    const result = await ApkUpdater.download({
      url: props.policy.downloadUrl,
      sha256: props.policy.sha256,
      fileName: `xiquan-mobile-ordering-${props.policy.latestVersion}.apk`,
    })
    state.value = reduceUpdater(state.value, { type: 'downloaded', path: result.path })
    await installDownloaded()
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    state.value = reduceUpdater(
      state.value,
      text.includes('HASH_MISMATCH')
        ? { type: 'hash-mismatch' }
        : { type: 'error', message: text },
    )
  }
}

async function continueAfterPermission() {
  if (state.value.status !== 'needs-install-permission') return
  await installDownloaded()
}
function showUpdateAgain() { dismissedVersionCode.value = null }

watch(() => props.policy?.latestVersionCode, () => {
  state.value = initialNativeUpdateState()
})

onMounted(async () => {
  window.addEventListener('xiquan:check-update', showUpdateAgain)
  if (!nativeAndroid.value) return
  progressHandle = await ApkUpdater.addListener('downloadProgress', (event) => {
    state.value = reduceUpdater(state.value, { type: 'progress', percent: event.percent })
  })
})

onBeforeUnmount(() => { window.removeEventListener('xiquan:check-update', showUpdateAgain); void progressHandle?.remove() })
</script>

<template>
  <div v-if="visible" class="update-gate" :class="{ required }">
    <section class="update-panel" role="dialog" aria-modal="true" aria-labelledby="mobile-update-title">
      <div class="update-symbol">↑</div>
      
      <h2 id="mobile-update-title">{{ required ? '必须更新后才能继续' : '发现溪泉移动端新版本' }}</h2>
      <p class="version-copy">当前可更新至 <strong>v{{ policy?.latestVersion }}</strong></p>

      <div v-if="policy?.releaseNotes.length" class="update-notes">
        <span>本次更新</span>
        <ul><li v-for="note in policy.releaseNotes" :key="note">{{ note }}</li></ul>
      </div>

      <div v-if="state.status === 'downloading'" class="download-progress">
        <div><span>安装包下载中</span><strong>{{ state.percent }}%</strong></div>
        <i><em :style="{ width: `${state.percent}%` }"></em></i>
      </div>

      <div v-if="state.status === 'needs-install-permission'" class="permission-help">
        <strong>还差一步系统授权</strong>
        <p>点下方按钮进入设置，允许“安装未知应用”，返回后再点“继续安装”。</p>
        <button @click="continueAfterPermission">我已授权，继续安装</button>
      </div>

      <p v-if="busyMessage" class="update-warning">{{ busyMessage }}</p>
      <p v-else-if="state.error" class="update-error">{{ state.error }}</p>
      <p v-else-if="nativeAndroid" class="safe-tip">下载后由系统弹出一次安装确认；不会清除登录终端信息。</p>
      <p v-else class="safe-tip">网页版无法直接覆盖安装，将为你打开官方下载页。</p>

      <button class="update-primary" :disabled="actionDisabled" @click="primaryAction">{{ actionLabel }}</button>
      <button v-if="!required" class="update-later" @click="dismiss">营业结束后更新</button>
    </section>
  </div>
</template>

<style scoped>
.update-gate { position: fixed; inset: 0; z-index: 110; display: grid; place-items: center; padding: 20px; background: rgba(25, 35, 29, .48); }
.update-panel { width: min(100%, 400px); padding: 28px 24px 22px; border: 1px solid var(--m-border); border-radius: 10px; color: var(--m-text-1); background: white; box-shadow: 0 8px 30px rgba(25, 35, 29, .18); }
.update-symbol { width: 60px; height: 60px; display: grid; place-items: center; margin-bottom: 16px; border-radius: 8px; color: white; background: var(--m-primary); font-size: 30px; font-weight: 900; }
.eyebrow { color: #64dcca; font-size: 11px; font-weight: 800; letter-spacing: .13em; }
h2 { margin: 7px 0 6px; font-size: 23px; line-height: 1.3; }
.version-copy { margin: 0 0 17px; color: var(--m-text-2); }
.version-copy strong { color: var(--m-primary); }
.update-notes { padding: 14px 16px; border: 1px solid rgba(255, 255, 255, .1); border-radius: 15px; background: var(--m-surface-soft); }
.update-notes span { color: var(--m-primary); font-size: 12px; font-weight: 800; }
.update-notes ul { margin: 8px 0 0; padding-left: 18px; color: var(--m-text-2); font-size: 13px; line-height: 1.65; }
.download-progress { margin: 17px 0; }
.download-progress div { display: flex; justify-content: space-between; margin-bottom: 8px; color: #aab9ca; font-size: 12px; }
.download-progress i { display: block; height: 8px; overflow: hidden; border-radius: 99px; background: rgba(255, 255, 255, .1); }
.download-progress em { display: block; height: 100%; border-radius: inherit; background: var(--m-primary); transition: width .2s ease; }
.permission-help, .update-warning, .update-error, .safe-tip { margin: 16px 0; padding: 12px 14px; border-radius: 13px; font-size: 12px; line-height: 1.55; }
.permission-help { color: #795312; background: rgba(218, 153, 44, .13); }
.permission-help p { margin: 4px 0 9px; }
.permission-help button { border: 0; padding: 8px 11px; border-radius: 9px; color: #201508; background: #f2c461; font-weight: 800; }
.update-warning { color: #795312; background: rgba(227, 157, 34, .14); }
.update-error { color: #a53c30; background: rgba(226, 71, 71, .14); }
.safe-tip { color: var(--m-text-2); background: rgba(255, 255, 255, .04); }
.update-primary, .update-later { width: 100%; min-height: 50px; border: 0; border-radius: 14px; font-weight: 850; }
.update-primary { color: white; background: var(--m-primary); }
.update-primary:disabled { opacity: .48; }
.update-later { margin-top: 10px; color: var(--m-text-2); background: var(--m-surface-soft); }
</style>
