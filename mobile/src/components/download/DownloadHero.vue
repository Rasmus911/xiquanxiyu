<script setup lang="ts">
defineProps<{ version?: string }>()
const baseUrl = import.meta.env.BASE_URL
</script>

<template>
  <section class="download-hero">
    <div class="hero-copy">
      <div class="brand-mark">溪</div>
      <span>溪泉洗浴 · 安卓员工端</span>
      <h1>溪泉员工点单</h1>
      <p>为溪泉洗浴员工打造的移动工作台。手牌、项目、库存与前台实时同步。</p>
      <div class="hero-tags"><b>v{{ version || '—' }}</b><b>正式签名</b><b>覆盖安装</b></div>
    </div>
    <div class="qr-card">
      <img :src="`${baseUrl}download-qr.svg`" alt="溪泉移动点单端下载二维码" />
      <strong>微信扫码进入下载页</strong>
      <span>请在系统浏览器中下载安装</span>
    </div>
  </section>
</template>

<style scoped>
.download-hero{display:grid;grid-template-columns:minmax(0,1fr) 178px;gap:28px;align-items:center;padding:30px;border:1px solid var(--m-border);border-radius:10px;background:white;box-shadow:var(--m-shadow)}.brand-mark{display:grid;place-items:center;width:58px;height:58px;margin-bottom:17px;border-radius:8px;color:white;background:var(--m-primary);font-size:28px;font-weight:900}.hero-copy>span{color:var(--m-primary);font-size:10px;font-weight:850;letter-spacing:.13em}h1{margin:8px 0;color:var(--m-text-1);font-size:clamp(28px,6vw,42px);line-height:1.2}p{max-width:520px;margin:0;color:var(--m-text-3);line-height:1.75}.hero-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}.hero-tags b{padding:7px 10px;color:var(--m-primary);border-radius:99px;background:var(--m-primary-soft);font-size:10px}.qr-card{padding:14px;border:1px solid var(--m-border);border-radius:20px;background:var(--m-surface-soft);text-align:center}.qr-card img{display:block;width:146px;height:146px;margin:auto;border-radius:12px;background:white}.qr-card strong,.qr-card span{display:block}.qr-card strong{margin-top:11px;color:var(--m-text-1);font-size:11px}.qr-card span{margin-top:4px;color:var(--m-text-3);font-size:9px}@media(max-width:600px){.download-hero{grid-template-columns:1fr;padding:22px}.qr-card{display:none}}
</style>
