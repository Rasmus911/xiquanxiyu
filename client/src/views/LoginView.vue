<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, getApiBaseUrl, http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useRuntimeStore } from '../stores/runtime'
import { StaleBusinessResponse } from '../business/state'
import { businessState } from '../business/state'
import { landingPath } from '../navigation/access'
import RegistrationDialog from '../components/auth/RegistrationDialog.vue'
import LoginScene from '../components/auth/LoginScene.vue'

const router = useRouter()
const auth = useAuthStore()
const runtime = useRuntimeStore()
const desktopUpdates = !!window.xiquan
const checkingUpdates = ref(false)
async function checkUpdates() {
  if (!window.xiquan || checkingUpdates.value) return
  checkingUpdates.value = true
  runtime.openUpdateCenter()
  try {
    const state = await window.xiquan.checkForUpdates()
    if (active) runtime.setUpdateState(state)
  } catch (error) { if (active) ElMessage.error(apiErrorMessage(error)) }
  finally { if (active) checkingUpdates.value = false }
}
const loading = ref(false)
const loginError = ref('')
let active = true
onBeforeUnmount(() => { active = false })
const setupOpen = ref(false)
const bootstrapOpen = ref(false)
const registrationOpen = ref(false)
function registered(username: string) { form.username = username; form.password = ''; ElMessage.success('注册成功，请登录') }
const form = reactive({ username: '', password: '' })
const config = reactive({
  serverUrl: getApiBaseUrl(),
  terminalCode: localStorage.getItem('xiquan_terminal_code') || `XS-${crypto.randomUUID().slice(0, 8)}`,
  terminalName: localStorage.getItem('xiquan_terminal_name') || '前台收银机',
})
const bootstrap = reactive({ username: 'admin', display_name: '系统管理员', password: '', bootstrap_token: '' })

onMounted(async () => {
  const electronConfig = await window.xiquan?.getConfig()
  if (electronConfig?.serverUrl) config.serverUrl = electronConfig.serverUrl
  if (electronConfig?.terminalCode) config.terminalCode = electronConfig.terminalCode
  if (electronConfig?.terminalName) config.terminalName = electronConfig.terminalName
})

async function saveAndRegister() {
  try {
    const savedConfig = {
      serverUrl: config.serverUrl.trim().replace(/\/$/, ''),
      terminalCode: config.terminalCode.trim(),
      terminalName: config.terminalName.trim(),
    }
    localStorage.setItem('xiquan_server_url', savedConfig.serverUrl)
    localStorage.setItem('xiquan_terminal_code', savedConfig.terminalCode)
    localStorage.setItem('xiquan_terminal_name', savedConfig.terminalName)
    await window.xiquan?.setConfig(savedConfig)
    await http.post('/terminals/register', { code: savedConfig.terminalCode, name: savedConfig.terminalName })
    ElMessage.success('服务器连接和终端注册成功')
    setupOpen.value = false
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

async function submitLogin() {
  if (loading.value) return
  loginError.value = ''
  if (!form.username.trim() || !form.password) { loginError.value = '请输入员工账号和密码'; return }
  loading.value = true
  let obsolete = false
  try {
    const pending = auth.login(form.username, form.password, config.terminalCode)
    form.password = ''
    await pending
    if (!active) return
    await router.replace(landingPath(businessState.value?.ui_pages || []))
  } catch (error) {
    obsolete = error instanceof StaleBusinessResponse
    if (active && !obsolete) loginError.value = apiErrorMessage(error)
  } finally {
    if (active && !obsolete) loading.value = false
  }
}

async function submitBootstrap() {
  try {
    await http.post('/auth/bootstrap', bootstrap)
    ElMessage.success('管理员初始化成功，请登录')
    form.username = bootstrap.username
    bootstrapOpen.value = false
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}
</script>

<template>
  <div class="login-page">
    <LoginScene>
      <div class="login-heading"><span class="login-caption">经营管理系统</span><h2>欢迎回来</h2><p>请使用您的员工账号登录</p></div>
      <el-form label-position="top" @submit.prevent="submitLogin">
        <el-form-item label="员工账号"><el-input v-model="form.username" size="large" autofocus autocomplete="username" @keyup.enter="submitLogin" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password size="large" autocomplete="current-password" @keyup.enter="submitLogin" /></el-form-item>
        <p v-if="loginError" class="login-error" role="alert">{{ loginError }}</p>
        <el-button type="primary" size="large" class="full-width" :loading="loading" @click="submitLogin">登录</el-button>
      </el-form>
      <div v-if="desktopUpdates" class="login-primary-actions" data-testid="login-primary-actions">
        <el-button v-if="desktopUpdates" data-testid="login-register" link @click="registrationOpen = true">注册账号</el-button>
        <el-button v-if="desktopUpdates" data-testid="login-check-updates" link :loading="checkingUpdates" @click="checkUpdates">检查更新</el-button>
      </div>
      <div class="login-setup-actions" data-testid="login-setup-actions">
        <el-button link @click="setupOpen = true">服务器与终端设置</el-button>
        <el-button link @click="bootstrapOpen = true">首次初始化管理员</el-button>
      </div>
      <div class="terminal-info">终端：{{ config.terminalName }}（{{ config.terminalCode }}）</div>
    </LoginScene>
    <RegistrationDialog v-if="desktopUpdates" v-model="registrationOpen" :terminal-code="config.terminalCode" @registered="registered" />

    <el-dialog v-model="setupOpen" title="服务器与终端设置" width="520px">
      <el-form label-position="top">
        <el-form-item label="后端 API 地址"><el-input v-model="config.serverUrl" placeholder="https://api.example.com/api" /></el-form-item>
        <el-form-item label="终端编码"><el-input v-model="config.terminalCode" /></el-form-item>
        <el-form-item label="终端名称"><el-input v-model="config.terminalName" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="setupOpen = false">取消</el-button><el-button type="primary" @click="saveAndRegister">保存并测试连接</el-button></template>
    </el-dialog>

    <el-dialog v-model="bootstrapOpen" title="首次初始化管理员" width="460px">
      <el-alert type="warning" :closable="false" title="只有系统中没有员工时才能执行一次" />
      <el-form label-position="top" style="margin-top: 16px">
        <el-form-item label="管理员账号"><el-input v-model="bootstrap.username" /></el-form-item>
        <el-form-item label="管理员姓名"><el-input v-model="bootstrap.display_name" /></el-form-item>
        <el-form-item label="管理员密码"><el-input v-model="bootstrap.password" type="password" show-password /></el-form-item>
        <el-form-item label="云端首次初始化口令（本地开发可留空）"><el-input v-model="bootstrap.bootstrap_token" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer><el-button @click="bootstrapOpen = false">取消</el-button><el-button type="primary" @click="submitBootstrap">初始化</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.login-page { min-height: 100vh; }
.login-heading { margin-bottom: 32px; }
.login-caption { color: #947d62; font-size: 12px; letter-spacing: .14em; }
h2 { margin: 14px 0 8px; font-size: 28px; color: #40332d; }
.login-heading p { color: #8b7a68; font-size: 13px; margin: 0; }
.login-error { color: #a23c2c; font-size: 13px; margin: -2px 0 16px; line-height: 1.6; }
.full-width { width: 100%; min-height: 48px; transition: background .2s, box-shadow .2s; }
.full-width:hover { box-shadow: 0 4px 12px #925a4320; }
.full-width:active { box-shadow: none; }
.login-primary-actions, .login-setup-actions { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.login-primary-actions { margin-top: 18px; padding-bottom: 16px; border-bottom: 1px solid #e3d9ca; }
.login-setup-actions { margin-top: 14px; }
.login-primary-actions :deep(.el-button), .login-setup-actions :deep(.el-button) { margin-left: 0; min-height: 30px; }
.login-setup-actions :deep(.el-button) { color: #8b7a68; font-size: 12px; white-space: normal; }
.terminal-info { margin-top: 20px; text-align: center; color: #9e8f7c; font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
</style>
