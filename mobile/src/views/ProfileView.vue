<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import version from '../../version.json'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import BusinessResetPanel from '../components/profile/BusinessResetPanel.vue'
import { disconnectRealtime } from '../composables/useRealtime'
import { getOrCreateTerminalCode } from '../session'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const session = useSessionStore()
const business = useBusinessStore()
const connectivity = useConnectivityStore()
const message = ref('')

function logout() {
  disconnectRealtime()
  session.logout()
  business.reset()
  void router.replace('/login')
}

function checkUpdate() {
  window.dispatchEvent(new Event('xiquan:check-update'))
  message.value = '已检查更新；如有新版本会自动显示。'
}
</script>

<template>
  <div>
    <MobileTopbar title="我的" subtitle="账号、终端与同步状态" />
    <main class="mobile-page">
      <section class="profile-card">
        <div class="avatar">{{ (session.employee?.display_name || session.employee?.username || '员').slice(0, 1) }}</div>
        <h2>{{ session.employee?.display_name }}</h2>
        <p>@{{ session.employee?.username }} · {{ session.employee?.role_label }}</p>
      </section>
      <div v-if="message" class="notice">{{ message }}</div>
      <section class="mobile-card info-list">
        <div><span>手机终端</span><strong>{{ getOrCreateTerminalCode() }}</strong></div>
        <div><span>应用版本</span><strong>v{{ version.version }}（{{ version.versionCode }}）</strong></div>
        <div><span>API 状态</span><strong :class="{ ok: connectivity.apiReachable }">{{ connectivity.apiReachable ? '正常' : '不可用' }}</strong></div>
        <div><span>实时同步</span><strong :class="{ ok: connectivity.socketConnected }">{{ connectivity.socketConnected ? '已连接' : '定时同步中' }}</strong></div>
        <div><span>上次同步</span><strong>{{ connectivity.syncLabel }}</strong></div>
      </section>
      <button class="outline-button" @click="business.refreshBootstrap()">立即同步营业数据</button>
      <button class="outline-button" @click="checkUpdate">检查应用更新</button>
      <button v-if="session.employee?.capabilities?.registration_token_view === true" class="outline-button" @click="router.push('/registration-token')">查看注册授权码</button>
      <button class="danger-button" @click="logout">退出登录</button>
      <BusinessResetPanel />
    </main>
  </div>
</template>

<style scoped>
.profile-card{padding:22px;text-align:center}.avatar{display:grid;place-items:center;width:64px;height:64px;margin:auto;border-radius:8px;color:white;background:var(--m-primary);font-size:27px;font-weight:900}.profile-card h2{margin:12px 0 3px}.profile-card p{margin:0;color:var(--m-text-3);font-size:13px}.info-list div{display:flex;justify-content:space-between;gap:12px;padding:13px 0;border-bottom:1px solid var(--m-border)}.info-list div:last-child{border:0}.info-list span{color:var(--m-text-3)}.info-list strong{max-width:70%;overflow-wrap:anywhere;color:var(--m-text-1);font-size:13px;text-align:right}.info-list strong.ok{color:var(--m-accent)}.outline-button,.danger-button{width:100%;min-height:48px;margin-top:12px;border-radius:13px;font-weight:800}.outline-button{color:var(--m-primary);border:1px solid var(--m-primary);background:white}.danger-button{color:var(--m-danger);border:1px solid #f0c6c0;background:#fff3f1}
</style>
