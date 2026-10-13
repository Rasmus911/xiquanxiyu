<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiData, apiErrorMessage, http } from '../../api/http'
import { onBusinessSessionClear, useBusinessGuard } from '../../business/state'
import type { CheckoutBenefits, Member, MemberVerification } from '../../types'
import CardScanDialog from '../members/CardScanDialog.vue'

const props = defineProps<{
  visits: Array<{ visit_id: string; wristband_number: string }>
  disabled?: boolean
  resetToken: number
}>()
const emit = defineEmits<{
  selection: [value: { member: Member | null; benefits: CheckoutBenefits }]
  busy: [value: boolean]
  balance: []
}>()
const guard = useBusinessGuard()
const phone = ref(''), member = ref<Member | null>(null), verification = ref<MemberVerification | null>(null)
const passId = ref(''), passVisits = ref<string[]>([]), scanOpen = ref(false), looking = ref(false), error = ref('')
let generation = 0
const busy = computed(() => looking.value || scanOpen.value)
const locked = computed(() => !!props.disabled || looking.value)
const verified = computed(() => !!member.value && (!member.value.holder_surname || verification.value?.surname_confirmed))
watch(busy, value => emit('busy', value), { flush: 'sync' })
function publish() {
  emit('selection', { member: member.value, benefits: {
    pass_use: passId.value && passVisits.value.length ? { member_pass_id: passId.value, visit_ids: [...passVisits.value] } : null,
    member_verification: verification.value ? { ...verification.value } : null,
  } })
}
function clear() {
  generation++; looking.value = false
  member.value = null; verification.value = null; passId.value = ''; passVisits.value = []; error.value = ''
  publish()
}
function reset() { scanOpen.value = false; phone.value = ''; clear() }
watch(phone, clear, { flush: 'sync' })
watch(() => props.resetToken, reset)
onBusinessSessionClear(reset)
onBeforeUnmount(() => { generation++; emit('busy', false) })
function openScanner() {
  if (locked.value) return
  clear(); scanOpen.value = true
}
function closeScanner(open: boolean) {
  if (props.disabled || looking.value) return
  scanOpen.value = open
  if (!open) clear()
}
async function lookup(method: 'phone' | 'card', cardUid?: string) {
  if (locked.value) return
  clear()
  const value = method === 'phone' ? phone.value.replace(/\D/g, '') : cardUid!
  if (method === 'phone' && !/^1\d{10}$/.test(value)) { error.value = '请输入完整的 11 位会员手机号'; return }
  const owned = generation, current = guard('lookup')
  looking.value = true
  try {
    const data = apiData<Member>(await http.get('/members/lookup', { params: method === 'phone' ? { phone: value } : { card_uid: value } }))
    if (owned !== generation || !current() || props.disabled) return
    if (!data.is_active || (method === 'card' && (!data.card_binding?.is_active || data.card_binding.card_uid !== value))) {
      throw new Error('实体卡已撤销或会员已停用，请重新查询')
    }
    member.value = data
    verification.value = { method, ...(method === 'card' ? { card_binding_id: data.card_binding!.id } : {}), surname_confirmed: false }
    scanOpen.value = false
    publish()
  } catch (failure) {
    if (owned === generation && current()) error.value = apiErrorMessage(failure)
  } finally {
    if (owned === generation) looking.value = false
  }
}
function choosePass() {
  passVisits.value = []; publish()
}
</script>

<template>
  <section class="member-payment-selector">
    <strong>会员识别与抵次</strong>
    <div class="toolbar">
      <el-input v-model="phone" :disabled="locked || scanOpen" maxlength="11" placeholder="每次请输入完整的 11 位手机号" @keydown.enter.stop.prevent="lookup('phone')" />
      <el-button :disabled="locked || scanOpen" @click="lookup('phone')">查询会员</el-button>
      <el-button :disabled="locked || scanOpen" @click="openScanner">刷实体卡</el-button>
      <el-button :disabled="locked || !verified" @click="emit('balance')">使用可用余额</el-button>
    </div>
    <el-alert v-if="error && !scanOpen" :title="error" type="error" :closable="false" />
    <template v-if="member">
      <p>{{ member.name || member.holder_surname || '实体卡会员' }} · {{ member.phone || '无手机号' }} · 余额 ¥{{ member.balance }}</p>
      <el-checkbox v-if="member.holder_surname && verification" v-model="verification.surname_confirmed" data-testid="surname-confirm" :disabled="locked" @change="publish">已核实持卡人姓氏：{{ member.holder_surname }}</el-checkbox>
      <label>本次抵票次卡
        <select v-model="passId" data-testid="pass-select" :disabled="locked || !verified" @change="choosePass">
          <option value="">不使用次数</option>
          <option v-for="pass in member.passes || []" :key="pass.id" :value="pass.id" :disabled="!pass.is_active || pass.remaining_count <= 0">{{ pass.name }} · 剩余 {{ pass.remaining_count }} 次{{ pass.valid_until ? ` · 有效至 ${pass.valid_until}` : '' }}</option>
        </select>
      </label>
      <template v-if="passId">
        <p>手动选择本次抵票人员；仅抵独立有效门票，服务、商品及套票已含门票不抵。抵扣金额以服务器核验为准。</p>
        <el-checkbox-group v-model="passVisits" :disabled="locked || !verified" @change="publish">
          <el-checkbox v-for="visit in visits" :key="visit.visit_id" :value="visit.visit_id" :data-testid="`pass-visit-${visit.visit_id}`">{{ visit.wristband_number }} 号</el-checkbox>
        </el-checkbox-group>
      </template>
    </template>
    <CardScanDialog :model-value="scanOpen" :busy="locked" :error="error" @update:model-value="closeScanner" @read="lookup('card', $event)" />
  </section>
</template>

<style scoped>
.member-payment-selector { display: grid; gap: 10px; margin-top: 16px; padding: 14px; border: 1px solid #cfe0ff; border-radius: 11px; background: #f6f9ff; }
.toolbar { justify-content: flex-start; }
.el-input { max-width: 330px; }
p { margin: 0; }
select { margin-left: 10px; padding: 7px; max-width: 100%; }
</style>
