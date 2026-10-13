<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiErrorMessage, http } from '../api/http'
import { clearBusinessSession, onBusinessSessionClear, useBusinessGuard } from '../business/state'
import { useAuthStore } from '../stores/auth'
import AppPageHeader from '../components/app/AppPageHeader.vue'

const auth = useAuthStore()
const router = useRouter()
const guard = useBusinessGuard()
const saving = ref(false)
const form = reactive({old_password:'',new_password:'',confirm_password:''})
function clearPasswords() { form.old_password = ''; form.new_password = ''; form.confirm_password = '' }
onBusinessSessionClear(clearPasswords)
onBeforeUnmount(clearPasswords)
watch(() => auth.employee?.id, clearPasswords)
async function submit() {
  if (saving.value || !auth.employee) return
  if (!form.old_password) { ElMessage.warning('请输入当前登录密码'); return }
  if (form.new_password !== form.confirm_password) { ElMessage.warning('两次新密码不一致'); return }
  if (form.old_password === form.new_password) { ElMessage.warning('新密码不能与旧密码相同'); return }
  if (form.new_password.length < 8 || form.new_password.length > 128) { ElMessage.warning('新密码需要 8–128 位'); return }
  const isCurrent = guard('password-change')
  if (!isCurrent()) return
  saving.value = true
  try {
    await http.post('/auth/change-password', {...form})
    if (!isCurrent()) return
    clearPasswords()
    ElMessage.success('密码修改成功，请重新登录')
    clearBusinessSession()
    await router.replace('/login')
  } catch (error) { if (isCurrent()) ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) saving.value = false }
}
</script>

<template>
  <div class="page">
    <AppPageHeader title="账号密码修改" description="仅修改本人密码，成功后所有已登录设备需要重新登录。" />
    <el-card class="password-card" shadow="never">
      <div class="account-identity"><strong>{{ auth.employee?.display_name }}</strong><span>登录账号：{{ auth.employee?.username }}</span></div>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="当前密码"><el-input v-model="form.old_password" data-testid="account-old-password" type="password" show-password autocomplete="current-password" :disabled="saving" maxlength="128" /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="form.new_password" data-testid="account-new-password" type="password" show-password autocomplete="new-password" :disabled="saving" maxlength="128" /></el-form-item>
        <el-form-item label="再次输入新密码"><el-input v-model="form.confirm_password" data-testid="account-confirm-password" type="password" show-password autocomplete="new-password" :disabled="saving" maxlength="128" @keyup.enter="submit" /></el-form-item>
        <el-button type="primary" data-testid="account-password-submit" :loading="saving" @click="submit">修改密码并重新登录</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.password-card { max-width: 480px; }
.account-identity { display: grid; gap: 6px; padding-bottom: 20px; }
.account-identity span { color: var(--xq-text-2); font-size: 14px; }
</style>
