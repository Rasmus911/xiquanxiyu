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
import LoginScene from '../components/auth/LoginScene.vue'
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
<template><LoginScene compact><form class="login-view" @submit.prevent="login"><span class="eyebrow">员工点单端</span><h2>欢迎回来</h2><p>请使用您的员工账号登录</p><label>员工账号<input v-model="username" autocomplete="username" placeholder="请输入登录账号"/></label><label>密码<input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码"/></label><div v-if="error" class="form-error" role="alert">{{error}}</div><button type="submit" class="primary-button" :disabled="loading">{{loading?'正在登录':'登录'}}</button><button type="button" class="update-button" :disabled="loading" @click="checkUpdate">检查应用更新</button><small>v{{version.version}} · 不保存密码</small></form></LoginScene></template>
<style scoped>
.login-view { width:100%; }
.eyebrow { color:#947d62;font-size:12px;letter-spacing:.14em; }
h2 { color:#40332d;font-size:26px;margin:12px 0 8px; }
p { color:#8b7a68;font-size:13px;margin:0 0 24px; }
label { display:grid;gap:8px;margin-top:18px;color:#66574d;font-size:13px; }
input { width:100%;box-sizing:border-box;min-height:48px;padding:0 14px;border:1px solid #d9cdbc;border-radius:8px;outline:none;background:#fffdf9;color:#40332d;font-size:16px; }
input:focus-visible { border-color:#925a43;box-shadow:0 0 0 3px #925a4315; }
.primary-button { width:100%;min-height:50px;margin-top:24px;border:0;border-radius:8px;color:#fffdf9;background:#925a43;font-weight:700;font-size:16px; }
.primary-button:active { background:#744532; }
.primary-button:disabled { opacity:.5; }
.update-button { width:100%;min-height:44px;margin-top:12px;border:1px solid #d9cdbc;border-radius:8px;color:#925a43;background:transparent;font-weight:600; }
.form-error { margin-top:12px;color:#a23c2c;font-size:13px;line-height:1.6; }
small { display:block;margin-top:20px;color:#9e8f7c;font-size:11px;text-align:center; }
</style>
