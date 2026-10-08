<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { apiData, apiErrorMessage, http } from '../../api/http'
import { businessGeneration, onBusinessSessionClear } from '../../business/state'
import { registrationIdentity, registrationPayload, registrationRoles, RegistrationRetry } from '../../domain/auth/registration'
const props = defineProps<{ modelValue: boolean; terminalCode: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; registered: [username: string] }>()
const form = reactive({ username: '', display_name: '', role: 'male_scrubber', password: '', confirmation: '', code: '' })
const error = ref(''), pending = ref(false)
const retry = new RegistrationRetry()
let active = true, ownership = 0
function clear() { ownership++; pending.value = false; form.password = ''; form.confirmation = ''; form.code = ''; retry.clear(); error.value = '' }
function close() { clear(); emit('update:modelValue', false) }
watch(() => props.modelValue, value => { if (!value) clear() }, { flush: 'sync' })
watch(() => props.terminalCode, clear, { flush: 'sync' })
onBusinessSessionClear(close)
onBeforeUnmount(() => { active = false; clear() })
async function submit() {
  if (!props.modelValue || pending.value) return
  const owned = ++ownership, generation = businessGeneration.capture()
  const current = () => active && props.modelValue && owned === ownership && businessGeneration.isCurrent(generation)
  error.value = ''
  try {
    const body = registrationPayload(form, props.terminalCode)
    pending.value = true
    const response = await http.post('/auth/register', body, { headers: { 'Idempotency-Key': retry.key(body) } })
    if (!current()) return
    if (response.status !== 201) throw new Error('注册结果无法确认，请使用相同信息重试')
    const username = registrationIdentity(apiData<unknown>(response), body)
    close(); emit('registered', username)
  } catch (cause) { if (current()) error.value = apiErrorMessage(cause) }
  finally { if (current()) pending.value = false }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="注册员工账号" width="460px" @update:model-value="close">
    <el-alert title="授权码由管理员手机端提供，用于批准注册。手机号仅作为登录账号，无需短信。" type="info" :closable="false" />
    <el-form label-position="top" style="margin-top:16px" @submit.prevent="submit">
      <el-form-item label="手机号"><el-input v-model="form.username" name="username" inputmode="numeric" maxlength="11" :disabled="pending" /></el-form-item>
      <el-form-item label="员工姓名"><el-input v-model="form.display_name" name="display_name" maxlength="80" :disabled="pending" /></el-form-item>
      <el-form-item label="岗位"><select v-model="form.role" name="role" :disabled="pending"><option v-for="role in registrationRoles" :key="role.value" :value="role.value">{{ role.label }}</option></select></el-form-item>
      <el-form-item label="密码（8–128 位）"><el-input v-model="form.password" name="password" type="password" autocomplete="new-password" :disabled="pending" /></el-form-item>
      <el-form-item label="确认密码"><el-input v-model="form.confirmation" name="confirmation" type="password" autocomplete="new-password" :disabled="pending" /></el-form-item>
      <el-form-item label="管理员注册授权码"><el-input v-model="form.code" name="code" inputmode="numeric" maxlength="6" autocomplete="off" :disabled="pending" /></el-form-item>
      <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
    </el-form>
    <template #footer><el-button @click="close">取消</el-button><el-button data-testid="registration-submit" type="primary" :loading="pending" @click="submit">注册</el-button></template>
  </el-dialog>
</template>
<style scoped>select { width:100%;min-height:32px;border:1px solid var(--el-border-color);border-radius:4px;padding:0 10px;background:var(--el-bg-color);color:var(--el-text-color-regular) }</style>
