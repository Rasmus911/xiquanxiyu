<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage } from '../api'
import { loginAndLoad } from '../login-flow'
import { useBusinessStore } from '../stores/business'
import { useSessionStore } from '../stores/session'
import { StaleBusinessResponse } from '../business/state'
import { mobileLanding } from '../router/access'
import version from '../../version.json'
const router=useRouter();const session=useSessionStore();const business=useBusinessStore();const username=ref('');const password=ref('');const loading=ref(false);const error=ref('')
let active = true
onBeforeUnmount(() => { active = false })
function checkUpdate() { window.dispatchEvent(new Event('xiquan:check-update')) }
async function login() {
  if (loading.value) return
  if (!username.value.trim() || !password.value) { error.value = '请输入账号和密码'; return }
  loading.value = true; error.value = ''; let obsolete = false
  try {
    const pending = loginAndLoad(session, business, username.value, password.value)
    password.value = ''
    await pending
    if (active) await router.replace(mobileLanding(session.employee?.capabilities))
  } catch (cause) {
    obsolete = cause instanceof StaleBusinessResponse
    if (active && !obsolete) error.value = errorMessage(cause)
  } finally { if (active && !obsolete) loading.value = false }
}
</script>
<style scoped>
.update-button { width: 100%; min-height: 44px; margin-top: 10px; border: 1px solid var(--m-border); border-radius: 7px; color: var(--m-primary); background: white; font-weight: 650; }
.update-button:disabled { opacity: .5; }
</style>
<template><main class="login-view"><section><div class="brand-mark">溪</div><h1>员工点单端</h1><p>仅显示已开牌客人和当前岗位可售项目</p><label>员工账号<input v-model="username" autocomplete="username" placeholder="请输入登录账号"/></label><label>密码<input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" @keyup.enter="login"/></label><div v-if="error" class="form-error">{{error}}</div><button class="primary-button" :disabled="loading" @click="login">{{loading?'正在登录':'登录'}}</button><button class="update-button" :disabled="loading" @click="checkUpdate">检查应用更新</button><small>v{{version.version}} · 管理员会话最长 8 小时，点单员工最长 7 天。不保存密码。</small></section></main></template>
<style scoped>.login-view{min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--m-bg)}section{width:min(100%,390px);padding:28px 22px;border:1px solid var(--m-border);border-radius:10px;background:white;box-shadow:none}.brand-mark{display:grid;place-items:center;width:58px;height:58px;margin-bottom:16px;border-radius:8px;color:white;background:var(--m-primary);font-size:28px;font-weight:900}.eyebrow{color:var(--m-primary);font-size:10px;font-weight:850;letter-spacing:.15em}h1{margin:6px 0 4px;color:var(--m-text-1)}p{margin:0 0 20px;color:var(--m-text-3);font-size:12px}label{display:grid;gap:6px;margin-top:13px;color:var(--m-text-2);font-size:12px}input{min-height:48px;padding:0 14px;border:1px solid var(--m-border);border-radius:7px;outline:none}.primary-button{width:100%;min-height:50px;margin-top:18px;border:0;border-radius:7px;color:white;background:var(--m-primary);font-weight:850}.primary-button:disabled{opacity:.5}.form-error{margin-top:12px;padding:10px;color:#a63f32;border-radius:10px;background:#fff0ec;font-size:12px}small{display:block;margin-top:12px;color:var(--m-text-3);text-align:center}</style>
