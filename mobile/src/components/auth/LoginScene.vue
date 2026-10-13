<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
defineProps<{ compact?: boolean }>()
const visible = ref(true)
const reduced = ref(true)
const pointer = ref(false)
const position = ref({ x: 50, y: 50 })
const moving = computed(() => visible.value && !reduced.value)
const scene = ref<HTMLElement>()
let frame = 0
let media: MediaQueryList | undefined
let fine: MediaQueryList | undefined
function updateMotion() {
  reduced.value = !fine?.matches || !!media?.matches || (navigator.hardwareConcurrency > 0 && navigator.hardwareConcurrency <= 2)
  if (!moving.value) clearPointer()
}
function visibility() { visible.value = !document.hidden; if (!visible.value) clearPointer() }
function clearPointer() { pointer.value = false; if (frame) cancelAnimationFrame(frame); frame = 0 }
function move(event: PointerEvent) {
  if (!moving.value || event.pointerType === 'touch' || !scene.value) return
  const bounds = scene.value.getBoundingClientRect()
  if (!bounds.width || !bounds.height) return
  const x = Math.min(100, Math.max(0, (event.clientX - bounds.left) / bounds.width * 100))
  const y = Math.min(100, Math.max(0, (event.clientY - bounds.top) / bounds.height * 100))
  if (frame) cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => { position.value = { x, y }; pointer.value = true; frame = 0 })
}
onMounted(() => {
  media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  fine = window.matchMedia?.('(hover: hover) and (pointer: fine)')
  media?.addEventListener?.('change', updateMotion)
  fine?.addEventListener?.('change', updateMotion)
  document.addEventListener('visibilitychange', visibility)
  visibility(); updateMotion()
})
onBeforeUnmount(() => {
  clearPointer()
  document.removeEventListener('visibilitychange', visibility)
  media?.removeEventListener?.('change', updateMotion)
  fine?.removeEventListener?.('change', updateMotion)
})
</script>
<template>
  <main ref="scene" class="login-scene" :class="{ 'login-scene--compact': compact }"
    :data-motion="moving ? 'active' : 'static'" :data-pointer="pointer ? 'on' : 'off'"
    :style="{ '--pointer-x': position.x + '%', '--pointer-y': position.y + '%',
      '--drift-x': (position.x - 50) * .12 + 'px', '--drift-y': (position.y - 50) * .08 + 'px' }"
    @pointermove="move" @pointerleave="clearPointer">
    <section class="login-scene__brand" aria-label="溪泉洗浴">
      <div class="login-scene__masthead"><span class="login-scene__mark" aria-hidden="true">溪</span><span>溪泉 · 平泉</span></div>
      <div class="login-scene__intro">
        <div class="login-scene__eyebrow" aria-hidden="true">暖木 · 泉境</div>
        <h1>平泉市溪泉洗浴</h1>
        <p class="login-scene__tagline">一方暖泉，卸下一日疲惫。</p>
      </div>
      <div class="login-scene__landscape" aria-hidden="true">
        <svg class="login-scene__water" viewBox="0 0 680 450" fill="none">
          <circle cx="465" cy="130" r="71" fill="#D8BD91" opacity=".35"/>
          <path d="M0 276C120 230 188 188 293 245S461 328 680 222V450H0Z" fill="#D2C1A6" opacity=".65"/>
          <path d="M0 329C160 235 188 305 326 283S526 256 680 315V450H0Z" fill="#BDA587" opacity=".5"/>
          <path d="M0 354C167 316 334 364 478 324S635 336 680 326" stroke="#F6F1E8" stroke-width="2"/>
          <path d="M43 387C211 346 361 401 539 360" stroke="#F6F1E8" opacity=".7"/>
          <ellipse cx="332" cy="302" rx="95" ry="15" stroke="#F6F1E8" opacity=".65"/>
          <ellipse cx="332" cy="302" rx="145" ry="26" stroke="#F6F1E8" opacity=".4"/>
          <path d="M276 251C257 220 306 201 285 170M328 250C308 218 357 199 336 165M379 258C360 229 407 210 385 179" stroke="#F6F1E8" stroke-width="3" stroke-linecap="round" opacity=".6"/>
        </svg>
        <div class="login-scene__mist"></div>
        <div class="login-scene__pointer"></div>
      </div>
      <div class="login-scene__brand-foot"><span>平泉市溪泉洗浴</span><span>日常经营 · 有序从容</span></div>
    </section>
    <section class="login-scene__form"><div class="login-scene__form-inner"><slot /></div></section>
  </main>
</template>
<style scoped>
.login-scene { --el-color-primary: #925a43; --el-color-primary-light-3: #ae7b66; --el-color-primary-light-5: #c39d8b; --el-color-primary-light-7: #ddc8bd; --el-color-primary-light-9: #f7eee9; --el-color-primary-dark-2: #744532; --el-border-radius-base: 8px; --el-text-color-primary: #40332d; --el-text-color-regular: #66574d; --el-border-color: #d9cdbc; --el-fill-color-blank: #fffdf9; min-height: 100vh; min-height: 100dvh; display: grid; grid-template-columns: 55% 45%; color: #40332d; background: #f6f1e8; }
.login-scene__brand { position: relative; min-height: 620px; padding: clamp(30px, 5vw, 72px); overflow: hidden; background: #eee4d4; border-right: 1px solid #dacbb4; display: flex; flex-direction: column; }
.login-scene__brand::after { content: ''; pointer-events: none; position: absolute; inset: 0; opacity: .18; background: repeating-linear-gradient(95deg, transparent 0 49px, #baa287 50px, transparent 51px 98px); }
.login-scene__masthead { display: flex; align-items: center; gap: 14px; font-size: 13px; letter-spacing: .16em; z-index: 1; }
.login-scene__mark { display: grid; place-items: center; width: 48px; height: 48px; background: #72513f; color: #fff9ef; border-radius: 14px 4px 14px 4px; font: 700 29px 'SimSun', 'Songti SC', serif; }
.login-scene__intro { z-index: 1; margin-top: clamp(65px, 10vh, 110px); }
.login-scene__eyebrow { font-size: 12px; color: #8c7254; letter-spacing: .34em; margin-bottom: 24px; }
h1 { font-family: 'SimSun', 'Songti SC', serif; font-size: clamp(28px, 3.2vw, 46px); font-weight: 700; line-height: 1.5; letter-spacing: .05em; margin: 0; }
.login-scene__tagline { margin: 18px 0 0; font-size: 14px; color: #796652; letter-spacing: .1em; }
.login-scene__landscape { position: relative; flex: 1; min-height: 250px; margin: -70px -72px 0; pointer-events: none; }
.login-scene__water { width: 100%; height: 100%; min-height: 340px; transform: translate(var(--drift-x), var(--drift-y)); transition: transform .8s ease-out; }
.login-scene__mist { position: absolute; left: 20%; right: 10%; top: 40%; height: 45%; background: radial-gradient(ellipse at center, #fffaf0 0%, transparent 65%); opacity: .25; animation: spring-mist 16s ease-in-out infinite alternate; }
.login-scene__pointer { position: absolute; inset: 0; opacity: 0; background: radial-gradient(ellipse 140px 90px at var(--pointer-x) var(--pointer-y), #fff5dc, transparent); transition: opacity 1s; }
[data-pointer=on] .login-scene__pointer { opacity: .4; }
.login-scene__brand-foot { z-index: 1; display: flex; justify-content: space-between; gap: 20px; color: #88745e; border-top: 1px solid #cdbda4; padding-top: 16px; font-size: 11px; letter-spacing: .08em; }
.login-scene__form { display: flex; align-items: center; justify-content: center; padding: 48px 32px; min-width: 0; }
.login-scene__form-inner { width: 100%; max-width: 374px; }
[data-motion=static] .login-scene__mist { animation: none; }
[data-motion=static] .login-scene__water { transform: none; transition: none; }
@keyframes spring-mist { from { transform: translateY(15px) scale(.96); opacity: .16; } to { transform: translateY(-15px) scale(1.04); opacity: .32; } }
@media (prefers-reduced-motion: reduce) { .login-scene__mist { animation: none; } .login-scene__water { transform: none; transition: none; } .login-scene__pointer { display: none; } }
@media (max-width: 760px) {
  .login-scene { grid-template-columns: 1fr; }
  .login-scene__brand { min-height: 0; padding: 24px 28px 26px; border-right: 0; border-bottom: 1px solid #dacbb4; }
  .login-scene__masthead { font-size: 11px; gap: 10px; }
  .login-scene__mark { width: 38px; height: 38px; font-size: 24px; }
  .login-scene__intro { margin-top: 22px; }
  .login-scene__eyebrow { display: none; }
  h1 { font-size: 27px; }
  .login-scene__tagline { font-size: 12px; margin-top: 8px; }
  .login-scene__landscape { position: absolute; width: 220px; height: 150px; right: -60px; bottom: -10px; min-height: 0; margin: 0; opacity: .55; }
  .login-scene__water { min-height: 0; }
  .login-scene__brand-foot { display: none; }
  .login-scene__form { align-items: flex-start; padding: 28px 28px max(24px, env(safe-area-inset-bottom)); }
}
.login-scene--compact { grid-template-columns: 1fr; }
.login-scene--compact .login-scene__brand { min-height: 0; padding: 24px 28px 26px; border-right: 0; border-bottom: 1px solid #dacbb4; }
.login-scene--compact .login-scene__intro { margin-top: 22px; }
.login-scene--compact .login-scene__eyebrow, .login-scene--compact .login-scene__brand-foot { display: none; }
.login-scene--compact .login-scene__landscape { position: absolute; width: 220px; height: 150px; right: -60px; bottom: -10px; min-height: 0; margin: 0; opacity: .55; }
.login-scene--compact .login-scene__water { min-height: 0; }
.login-scene--compact h1 { font-size: 27px; }
.login-scene--compact .login-scene__form { align-items: flex-start; padding: 28px; }
</style>

