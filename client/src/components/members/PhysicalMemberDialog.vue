<script setup lang="ts">
import axios from 'axios'
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { apiData, apiErrorMessage, http } from '../../api/http'
import { businessGeneration, onBusinessSessionClear } from '../../business/state'
import { useRuntimeStore } from '../../stores/runtime'
import type { Member, PhysicalOpenRequest, PhysicalOpenResult } from '../../types'
import CardScanDialog from './CardScanDialog.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  opened: [member: Member]
  pendingChange: [value: boolean]
}>()
const defaults = () => ({ card_uid: '', phone: '', holder_surname: '', surname_confirmed: false,
  membership_type: 'stored' as PhysicalOpenRequest['membership_type'], amount: '', count: '', pass_name: '洗浴次卡', valid_until: '',
  payment_method: 'cash' as PhysicalOpenRequest['payment_method'] })
const form = reactive(defaults()), step = ref<'details' | 'collection'>('details')
const scanOpen = ref(false), error = ref(''), inFlight = ref(false)
const pendingBody = shallowRef<Readonly<PhysicalOpenRequest> | null>(null)
const locked = computed(() => pendingBody.value !== null)
let active = true, ownership = 0
let releaseBusy: (() => Promise<void>) | undefined
watch(locked, value => emit('pendingChange', value), { flush: 'sync' })
function resetForm() { Object.assign(form, defaults()); step.value = 'details'; scanOpen.value = false; error.value = '' }
watch(() => props.modelValue, () => {
  ownership++; scanOpen.value = false
  if (!pendingBody.value) resetForm()
}, { flush: 'sync' })
watch(() => form.holder_surname, () => { form.surname_confirmed = false })
function close() {
  if (locked.value || inFlight.value) return
  ownership++; resetForm(); emit('update:modelValue', false)
}
function beforeClose(done: () => void) { if (!locked.value && !inFlight.value) { close(); done() } }
onBusinessSessionClear(() => {
  ownership++; pendingBody.value = null; inFlight.value = false; releaseBusy = undefined
  resetForm(); emit('update:modelValue', false)
})
onBeforeUnmount(() => { active = false; ownership++; scanOpen.value = false })
function readCard(uid: string) { if (!locked.value) { form.card_uid = uid; scanOpen.value = false } }
function next() {
  if (locked.value) return
  error.value = ''
  if (!form.card_uid) { error.value = '请先读取实体卡'; return }
  if (form.phone && !/^[0-9]{11}$/.test(form.phone)) { error.value = '请输入 11 位手机号，或留空'; return }
  if (form.holder_surname.trim() && !form.surname_confirmed) { error.value = '请核实确认持卡人姓氏'; return }
  if (!/^(?:0\.(?:0[1-9]|[1-9]\d?)|[1-9]\d*(?:\.\d{1,2})?)$/.test(form.amount)) { error.value = '请输入大于 0、最多两位小数的实际收款金额'; return }
  if (form.membership_type === 'pass' && (!/^[1-9][0-9]*$/.test(form.count) || !Number.isSafeInteger(Number(form.count)))) {
    error.value = '请输入大于 0 的整数次数'; return
  }
  step.value = 'collection'
}
function body(): Readonly<PhysicalOpenRequest> {
  return Object.freeze({ card_uid: form.card_uid, phone: form.phone || null, holder_surname: form.holder_surname.trim() || null,
    surname_confirmed: form.surname_confirmed, membership_type: form.membership_type, amount: form.amount,
    ...(form.membership_type === 'pass' ? { count: Number(form.count), pass_name: form.pass_name.trim() || '洗浴次卡', valid_until: form.valid_until || null } : {}),
    payment_method: form.payment_method, idempotency_key: crypto.randomUUID() })
}
async function submit(retry = false) {
  if (!props.modelValue || inFlight.value || step.value !== 'collection' || (locked.value && !retry)) return
  const generation = businessGeneration.capture(), owned = ++ownership
  const current = () => active && props.modelValue && ownership === owned && businessGeneration.isCurrent(generation)
  if (!pendingBody.value) pendingBody.value = body()
  const submitted = pendingBody.value
  inFlight.value = true; error.value = ''
  let definitive = false
  try {
    if (!releaseBusy) {
      const release = await useRuntimeStore().setBusinessBusy('实体卡开户收款结果待确认')
      // A session clear can happen while the desktop acknowledges its busy state.
      if (!businessGeneration.isCurrent(generation)) { await release(); return }
      releaseBusy = release
    }
    if (!businessGeneration.isCurrent(generation)) return
    const response = await http.post('/members/physical-open', submitted)
    const data = apiData<PhysicalOpenResult>(response)
    if (![200, 201].includes(response.status) || !data?.member?.id || !data.card_binding?.id
      || data.card_binding.card_uid !== submitted.card_uid || data.card_binding.member_id !== data.member.id
      || (submitted.membership_type === 'pass' && !data.member_pass?.id)) throw new Error('开户结果无法确认，请重试原请求')
    definitive = true
    if (!current()) return
    inFlight.value = false; pendingBody.value = null; resetForm(); emit('opened', data.member); emit('update:modelValue', false)
  } catch (cause) {
    definitive = axios.isAxiosError(cause) && !!cause.response && cause.response.status >= 400
      && cause.response.status < 500 && cause.response.status !== 408
    if (current()) {
      error.value = definitive ? apiErrorMessage(cause) : `${apiErrorMessage(cause)}；收款结果待确认，请重试原请求`
      if (definitive) pendingBody.value = null
    }
  } finally {
    // Definitive responses release only this operation, even if its UI has closed.
    if (definitive) { const release = releaseBusy; releaseBusy = undefined; await release?.() }
    if (pendingBody.value === submitted || current()) inFlight.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="实体卡开通会员" width="520px" :before-close="beforeClose" :show-close="!locked" :close-on-click-modal="false" :close-on-press-escape="!locked" @update:model-value="close">
    <el-form v-if="step === 'details'" label-position="top" @submit.prevent @keydown.enter.stop.prevent>
      <el-form-item label="实体卡号"><span>{{ form.card_uid || '尚未读取' }}</span><el-button data-testid="physical-scan" @click="scanOpen = true">读取实体卡</el-button></el-form-item>
      <el-form-item label="手机号（可选）"><el-input v-model="form.phone" name="phone" inputmode="numeric" maxlength="11" /></el-form-item>
      <el-form-item label="持卡人姓氏（可选）"><el-input v-model="form.holder_surname" name="holder_surname" maxlength="40" /><el-checkbox v-if="form.holder_surname.trim()" v-model="form.surname_confirmed" name="surname_confirmed">已当面核实持卡人姓氏</el-checkbox></el-form-item>
      <el-form-item label="会员卡类型"><select v-model="form.membership_type" name="membership_type"><option value="stored">储值卡</option><option value="pass">次卡</option></select></el-form-item>
      <el-form-item v-if="form.membership_type === 'pass'" label="次卡次数"><el-input v-model="form.count" name="count" inputmode="numeric" /></el-form-item>
      <el-form-item :label="form.membership_type === 'pass' ? '次卡实际售价（元）' : '本次储值金额（元）'"><el-input v-model="form.amount" name="amount" inputmode="decimal" /></el-form-item>
      <template v-if="form.membership_type === 'pass'"><el-form-item label="次卡名称"><el-input v-model="form.pass_name" name="pass_name" maxlength="100" /></el-form-item><el-form-item label="有效期（可选）"><el-input v-model="form.valid_until" name="valid_until" type="date" /></el-form-item></template>
    </el-form>
    <template v-else>
      <el-descriptions :column="1" border><el-descriptions-item label="实体卡号">{{ form.card_uid }}</el-descriptions-item><el-descriptions-item label="手机号">{{ form.phone || '未留手机号' }}</el-descriptions-item><el-descriptions-item label="持卡人姓氏">{{ form.holder_surname || '未留姓氏' }}</el-descriptions-item><el-descriptions-item label="开户类型">{{ form.membership_type === 'pass' ? `次卡 ${form.count} 次` : '储值卡' }}</el-descriptions-item><el-descriptions-item label="实际收款">¥{{ form.amount }}</el-descriptions-item></el-descriptions>
      <el-form label-position="top" @submit.prevent @keydown.enter.stop.prevent><el-form-item label="收款方式"><select v-model="form.payment_method" name="payment_method" :disabled="locked"><option value="cash">现金</option><option value="wechat">微信</option><option value="alipay">支付宝</option></select></el-form-item></el-form>
      <el-alert title="确认已收到上述款项后，点击确认收款并开户。" type="info" :closable="false" />
      <el-alert v-if="locked" title="原请求收款结果待确认，请保持当前页面，使用原请求重试。" type="warning" :closable="false" />
    </template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template #footer>
      <el-button data-testid="physical-cancel" :disabled="locked" @click="close">取消</el-button>
      <el-button v-if="step === 'details'" data-testid="physical-next" type="primary" @click="next">下一步：收款确认</el-button>
      <template v-else><el-button :disabled="locked" @click="step = 'details'">返回修改</el-button><el-button data-testid="physical-confirm" type="primary" :disabled="locked" :loading="inFlight" @click="submit()">确认收款并开户</el-button><el-button v-if="locked && !inFlight" data-testid="physical-retry" type="primary" @click="submit(true)">重试原请求</el-button></template>
    </template>
  </el-dialog>
  <CardScanDialog v-model="scanOpen" @read="readCard" />
</template>

<style scoped>select { width:100%;min-height:32px;border:1px solid var(--el-border-color);border-radius:4px;padding:0 10px;background:var(--el-bg-color);color:var(--el-text-color-regular) }.el-alert { margin-top:12px }</style>
