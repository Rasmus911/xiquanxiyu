<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiData, apiErrorMessage, http } from '../../api/http'
import { businessGeneration, onBusinessSessionClear } from '../../business/state'
import type { CardBindingRequest, Member, MemberCardBinding } from '../../types'
import CardScanDialog from './CardScanDialog.vue'

const props = defineProps<{ modelValue: boolean; member: Member | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; bound: [member: Member] }>()
const scanOpen = ref(false), cardUid = ref(''), password = ref(''), error = ref(''), pending = ref(false)
let active = true, ownership = 0, key = ''
function clear() { ownership++; password.value = ''; scanOpen.value = false; cardUid.value = ''; key = ''; error.value = ''; pending.value = false }
function close() { clear(); emit('update:modelValue', false) }
function beforeClose(done: () => void) { close(); done() }
watch(() => props.modelValue, clear, { flush: 'sync' })
watch(() => props.member?.id, clear, { flush: 'sync' })
onBusinessSessionClear(close)
onBeforeUnmount(() => { active = false; clear() })
function readCard(uid: string) { if (!pending.value) { cardUid.value = uid; key = crypto.randomUUID(); password.value = ''; scanOpen.value = false; error.value = '' } }
async function submit() {
  if (!props.modelValue || pending.value || !props.member || !cardUid.value) return
  if (!password.value) { error.value = '请输入当前操作员工的登录密码'; return }
  const memberId = props.member.id, generation = businessGeneration.capture(), owned = ++ownership
  const current = () => active && props.modelValue && ownership === owned && props.member?.id === memberId && businessGeneration.isCurrent(generation)
  const body: CardBindingRequest = { card_uid: cardUid.value, password: password.value, idempotency_key: key }
  password.value = ''; pending.value = true; error.value = ''
  try {
    const data = apiData<{ member: Member; card_binding: MemberCardBinding }>(await http.post(`/members/${memberId}/physical-card`, body))
    if (!current()) return
    if (data?.member?.id !== memberId || data.card_binding?.card_uid !== body.card_uid) throw new Error('绑定结果无法确认，请使用原卡重试')
    const member = data.member
    close(); emit('bound', member)
  } catch (cause) { if (current()) error.value = apiErrorMessage(cause) }
  finally { if (current()) { password.value = ''; pending.value = false } }
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="member?.card_binding?.is_active ? '补办实体卡' : '绑定实体卡'" width="460px" :before-close="beforeClose" :close-on-click-modal="false" @update:model-value="close">
    <p>会员：{{ member?.name || member?.phone || '未留手机号' }}。{{ member?.card_binding?.is_active ? '补办后原实体卡立即作废，账户余额和次数沿用。' : '读取新卡后，用当前操作员工的登录密码确认。' }}</p>
    <el-button data-testid="binding-scan" :disabled="pending" @click="scanOpen = true">读取新实体卡</el-button>
    <p v-if="cardUid">新实体卡号：{{ cardUid }}</p>
    <el-form label-position="top" @submit.prevent @keydown.enter.stop.prevent><el-form-item label="当前操作员工登录密码"><el-input v-model="password" name="password" type="password" autocomplete="off" :disabled="pending || !cardUid" /></el-form-item></el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template #footer><el-button @click="close">取消</el-button><el-button data-testid="binding-confirm" type="primary" :loading="pending" :disabled="!cardUid" @click="submit">确认{{ member?.card_binding?.is_active ? '补办' : '绑定' }}</el-button></template>
  </el-dialog>
  <CardScanDialog v-model="scanOpen" :busy="pending" @read="readCard" />
</template>
