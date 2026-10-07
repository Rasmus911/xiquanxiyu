<template>
  <section class="steps-card">
    <div><h2>三步完成覆盖安装</h2></div>
    <ol>
      <li><b>1</b><p><strong>下载 APK</strong><span>等待安装包完整下载</span></p></li>
      <li><b>2</b><p><strong>允许安装</strong><span>按系统提示授权当前来源</span></p></li>
      <li><b>3</b><p><strong>确认覆盖</strong><span>无需卸载，终端信息会保留</span></p></li>
    </ol>
  </section>
</template>

<style scoped>
.steps-card{padding:22px;border:1px solid var(--m-border);border-radius:10px;background:white;box-shadow:var(--m-shadow)}.steps-card>div span{color:var(--m-accent);font-size:12px;font-weight:850;letter-spacing:.14em}h2{margin:5px 0 18px;color:var(--m-text-1);font-size:20px}ol{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:0;padding:0;list-style:none}li{display:flex;gap:11px;padding:12px;border-radius:15px;background:var(--m-surface-soft)}li>b{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;color:var(--m-primary);border-radius:11px;background:var(--m-primary-soft)}p{margin:0}strong,span{display:block}strong{color:var(--m-text-1);font-size:12px}p span{margin-top:4px;color:var(--m-text-3);font-size:12px;line-height:1.45}@media(max-width:600px){ol{grid-template-columns:1fr}}
</style>
