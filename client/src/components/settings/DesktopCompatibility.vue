<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'

const info = ref<DesktopDiagnostics | null>(null)
const error = ref('')
const changing = ref(false)
onMounted(async () => {
  if (!window.xiquan?.getDesktopDiagnostics) return
  try { info.value = await window.xiquan.getDesktopDiagnostics() }
  catch { error.value = '无法读取本机版本信息，请确认安装完整' }
})
async function changeRendering() {
  if (!info.value || !window.xiquan?.restartWithSoftwareRendering) return
  try {
    await ElMessageBox.confirm('软件将重新启动，需要重新登录。请先完成当前收款和充值。', '切换显示兼容模式', { type: 'warning' })
  } catch { return }
  changing.value = true
  try {
    const result = await window.xiquan.restartWithSoftwareRendering(!info.value.softwareRendering)
    error.value = result.ok ? '' : result.reason || '暂时不能重启'
  } catch { error.value = '修改显示模式失败，请稍后重试' }
  finally { changing.value = false }
}
</script>

<template>
  <section v-if="info || error" class="desktop-compatibility">
    <h3>本机版本与显示兼容</h3>
    <p v-if="info?.testOnly" class="candidate">兼容测试候选，尚未开启正式自动更新</p>
    <dl v-if="info">
      <dt>安装目标 / 程序架构</dt><dd>{{ info.targetId }} / {{ info.appArch }}</dd>
      <dt>系统 / Electron</dt><dd>{{ info.osRelease }} / {{ info.electronVersion }}</dd>
      <dt>Chromium / Node</dt><dd>{{ info.chromiumVersion }} / {{ info.nodeVersion }}</dd>
      <dt>构建标识</dt><dd>{{ info.buildId }}</dd>
    </dl>
    <p v-if="info">显示模式：{{ info.softwareRendering ? '软件渲染（旧显卡兼容）' : '硬件加速' }}</p>
    <button v-if="info" type="button" :disabled="changing" @click="changeRendering">
      {{ info.softwareRendering ? '恢复硬件加速并重启' : '启用软件渲染并重启' }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.desktop-compatibility { max-width: 700px; margin: 16px 0; padding: 20px; border: 1px solid var(--xq-border); background: white; border-radius: 8px; }
h3 { margin: 0 0 12px; font-size: 17px; }
dl { display: grid; grid-template-columns: minmax(120px, 1fr) 2fr; gap: 8px 16px; font-size: 13px; }
dt { color: var(--xq-text-3); } dd { margin: 0; overflow-wrap: anywhere; }
p { font-size: 13px; } .candidate, [role="alert"] { color: #925600; }
button { padding: 9px 14px; border: 1px solid var(--xq-border); border-radius: 5px; background: #f7f8fa; cursor: pointer; }
button:focus-visible { outline: 2px solid var(--xq-primary); outline-offset: 2px; }
</style>
