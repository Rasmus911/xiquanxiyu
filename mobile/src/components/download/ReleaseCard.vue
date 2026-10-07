<script setup lang="ts">
import type { DownloadConfig } from '../../types'
defineProps<{ config: DownloadConfig }>()
defineEmits<{ download: [] }>()
</script>

<template>
  <section class="release-card">
    <div class="release-heading"><div><span>当前正式版本</span><strong>v{{ config.version }}</strong></div><b>APK</b></div>
    <p>{{ config.releaseNotes || '稳定性与使用体验优化' }}</p>
    <small>SHA256：{{ config.sha256 }}</small>
    <button @click="$emit('download')">下载 APP</button>
  </section>
</template>

<style scoped>
.release-card{padding:22px;border:1px solid var(--m-border);border-radius:22px;background:white;box-shadow:var(--m-shadow)}.release-heading{display:flex;align-items:center;justify-content:space-between}.release-heading span,.release-heading strong{display:block}.release-heading span{color:var(--m-text-3);font-size:10px}.release-heading strong{margin-top:4px;color:var(--m-primary);font-size:24px}.release-heading>b{padding:7px 10px;color:var(--m-accent);border-radius:10px;background:var(--m-accent-soft);font-size:10px}p{color:var(--m-text-2);font-size:12px;line-height:1.65}small{display:block;overflow-wrap:anywhere;color:var(--m-text-3);font-size:9px}button{width:100%;min-height:50px;margin-top:17px;color:white;border:0;border-radius:14px;background:var(--m-primary);font-weight:850}
</style>
