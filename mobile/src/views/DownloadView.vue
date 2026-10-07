<script setup lang="ts">
import { onMounted, ref } from 'vue'
import DownloadHero from '../components/download/DownloadHero.vue'
import InstallSteps from '../components/download/InstallSteps.vue'
import ReleaseCard from '../components/download/ReleaseCard.vue'
import { openExternal } from '../native'
import type { DownloadConfig } from '../types'

const config = ref<DownloadConfig | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    const response = await fetch('https://api.pqxqxy.xyz/mobile/download-config.json', { cache: 'no-store' })
    if (!response.ok) throw new Error('下载信息读取失败')
    config.value = await response.json() as DownloadConfig
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '下载信息读取失败'
  }
})

async function download() {
  if (!config.value) return
  if (!config.value.androidApkUrl) {
    error.value = '安装包尚未发布，请稍后再试。'
    return
  }
  await openExternal(new URL(config.value.androidApkUrl, location.href).toString())
}
</script>

<template>
  <main class="download-view">
    <DownloadHero :version="config?.version" />
    <div class="wechat-tip">如果微信内无法下载，请点右上角“在浏览器打开”后重试。</div>
    <div class="download-grid">
      <ReleaseCard v-if="config" :config="config" @download="download" />
      <section v-else class="loading-card">正在读取最新版本…</section>
      <InstallSteps />
    </div>
    <div v-if="error" class="notice">{{ error }}</div>
    <footer>溪泉洗浴 · 员工移动工作台 · 数据与 ECS 实时同步</footer>
  </main>
</template>

<style scoped>
.download-view{min-height:100vh;padding:32px 18px 44px;background:var(--m-bg)}.download-view>*{width:min(100%,860px);margin-right:auto;margin-left:auto}.download-grid{display:grid;grid-template-columns:.9fr 1.35fr;gap:14px;margin-top:14px}.wechat-tip{margin-top:14px;padding:12px 14px;color:#78520f;border:1px solid #f1dda9;border-radius:13px;background:#fff8e5;font-size:12px}.loading-card{display:grid;place-items:center;min-height:200px;color:var(--m-text-3);border:1px solid var(--m-border);border-radius:22px;background:white}.notice{margin-top:14px}footer{padding-top:24px;color:var(--m-text-3);text-align:center;font-size:9px}@media(max-width:700px){.download-view{padding-top:18px}.download-grid{grid-template-columns:1fr}}
</style>
