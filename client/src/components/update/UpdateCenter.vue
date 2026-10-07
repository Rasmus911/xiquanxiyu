<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRuntimeStore } from '../../stores/runtime'
import { updatePresentation, updateDialogVisible } from '../../update/update-copy'

const runtime = useRuntimeStore()
const dismissedVersion = ref<string | null>(null)
const actionError = ref('')
let unsubscribe: (() => void) | undefined

const state = computed(() => runtime.updateState)
const presentation = computed(() => state.value ? updatePresentation(state.value) : null)
const isDesktop = computed(() => Boolean(window.xiquan))
const visible = computed({
  get: () => isDesktop.value && updateDialogVisible(state.value, runtime.updateCenterVisible, dismissedVersion.value),
  set: (value: boolean) => {
    if (value) return runtime.openUpdateCenter()
    dismiss()
  },
})

function dismiss() {
  if (!presentation.value?.allowDismiss) return
  dismissedVersion.value = state.value?.availableVersion || null
  runtime.closeUpdateCenter()
  actionError.value = ''
}

async function primaryAction() {
  const current = state.value
  if (!current || !window.xiquan) return
  actionError.value = ''
  if (current.status === 'downloaded') {
    const result = await window.xiquan.installUpdate()
    if (!result.ok) actionError.value = result.reason || '当前无法安装更新'
    return
  }
  runtime.setUpdateState(await window.xiquan.checkForUpdates())
}

watch(() => state.value?.businessBusyReason, (reason) => {
  if (!reason) actionError.value = ''
})

onMounted(async () => {
  if (!window.xiquan) return
  try {
    runtime.setUpdateState(await window.xiquan.getUpdateState())
    unsubscribe = window.xiquan.onUpdateState(runtime.setUpdateState)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '读取更新状态失败')
  }
})

onBeforeUnmount(() => unsubscribe?.())
</script>

<template>
  <el-dialog
    v-if="isDesktop && state && presentation"
    v-model="visible"
    width="min(520px, calc(100vw - 24px))"
    class="update-center-dialog"
    :close-on-click-modal="presentation.allowDismiss"
    :close-on-press-escape="presentation.allowDismiss"
    :show-close="presentation.allowDismiss"
    align-center
  >
    <div class="update-hero">
      <div class="update-mark"><el-icon><Download /></el-icon></div>
      <div>
        
        <h2>{{ presentation.title }}</h2>
        <p>{{ state.message }}</p>
      </div>
    </div>

    <div v-if="state.availableVersion" class="version-line">
      <span>当前 {{ state.currentVersion }}</span><el-icon><Right /></el-icon><strong>新版 {{ state.availableVersion }}</strong>
    </div>

    <el-progress
      v-if="['checking', 'downloading', 'downloaded'].includes(state.status)"
      :percentage="state.status === 'checking' ? 0 : state.percent"
      :indeterminate="state.status === 'checking'"
      :duration="2"
      :stroke-width="10"
    />

    <div v-if="state.releaseNotes.length" class="release-notes">
      <strong>本次更新</strong>
      <ul><li v-for="note in state.releaseNotes" :key="note">{{ note }}</li></ul>
    </div>

    <el-alert
      v-if="presentation.blockReason || actionError"
      :title="actionError || `${presentation.blockReason}，完成后即可安装`"
      type="warning"
      :closable="false"
      show-icon
    />

    <template #footer>
      <div class="dialog-actions">
        <span class="action-spacer" />
        <el-button v-if="presentation.secondaryAction" @click="dismiss">{{ presentation.secondaryAction }}</el-button>
        <el-button
          v-if="presentation.primaryAction"
          type="primary"
          :loading="['checking', 'downloading'].includes(state.status)"
          :disabled="presentation.primaryDisabled"
          @click="primaryAction"
        >{{ presentation.primaryAction }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.update-hero { display: flex; gap: 16px; align-items: center; padding: 4px 0 18px; }
.update-mark { width: 58px; height: 58px; flex: 0 0 58px; display: grid; place-items: center; border-radius: 8px; color: white; background: var(--xq-primary); font-size: 26px; }
.eyebrow { color: #2b9f91; font-size: 11px; font-weight: 800; letter-spacing: .1em; }
h2 { margin: 4px 0; color: #172942; font-size: 22px; }
p { margin: 0; color: #77859a; }
.version-line { display: flex; align-items: center; gap: 10px; margin: 0 0 18px; padding: 12px 14px; border-radius: 12px; color: #7a8798; background: #f3f7fb; }
.version-line strong { color: #276fd2; }
.release-notes { margin: 18px 0; padding: 15px 17px; border: 1px solid #e8edf4; border-radius: 13px; background: #fbfcfe; color: #4b5d73; }
.release-notes ul { margin: 8px 0 0; padding-left: 20px; }
.release-notes li + li { margin-top: 5px; }
.dialog-actions { display: flex; align-items: center; width: 100%; flex-wrap: wrap; gap: 8px; }
.action-spacer { flex: 1; }
</style>
