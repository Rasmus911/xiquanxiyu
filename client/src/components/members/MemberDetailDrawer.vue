<script setup lang="ts">
import type { Member } from '../../types'
import { formatBusinessTime } from '../../format/business-time'

defineProps<{ modelValue: boolean; member: Member | null; activeTab: 'stored' | 'pass' }>()
defineEmits<{
  'update:modelValue': [value: boolean]
  'update:activeTab': [value: 'stored' | 'pass']
  recharge: [member: Member]
  purchasePass: [member: Member]
  consumePass: [passId: string]
}>()
</script>

<template>
  <el-drawer :model-value="modelValue" size="720px" :title="`会员详情：${member?.name || member?.phone || ''}`" @update:model-value="$emit('update:modelValue', $event)">
    <el-descriptions :column="3" border><el-descriptions-item label="手机号">{{ member?.phone }}</el-descriptions-item><el-descriptions-item label="姓名">{{ member?.name || '-' }}</el-descriptions-item><el-descriptions-item label="储值余额"><strong class="money">¥{{ member?.balance }}</strong></el-descriptions-item></el-descriptions>
    <el-tabs :model-value="activeTab" style="margin-top: 16px" @update:model-value="$emit('update:activeTab', $event as 'stored' | 'pass')">
      <el-tab-pane label="储值卡" name="stored">
        <div class="pane-header"><div><strong>储值卡账户</strong><span>充值收款确认后立即到账</span></div><el-button v-if="member" type="success" @click="$emit('recharge', member)">储值充值</el-button></div>
        <el-table :data="member?.ledgers || []" size="small" style="margin-top: 12px"><el-table-column label="时间" min-width="165"><template #default="scope">{{ formatBusinessTime(scope.row.created_at) }}</template></el-table-column><el-table-column prop="entry_type" label="类型" /><el-table-column prop="payment_method" label="支付方式" /><el-table-column prop="amount" label="变动" /><el-table-column prop="balance_after" label="余额" /><el-table-column prop="note" label="备注" /></el-table>
      </el-tab-pane>
      <el-tab-pane label="次卡" name="pass">
        <div class="pane-header"><div><strong>次卡账户</strong><span>新开次卡需要记录实际收款金额和支付方式</span></div><el-button v-if="member" type="primary" @click="$emit('purchasePass', member)">购买次卡</el-button></div>
        <el-table :data="member?.passes || []" style="margin-top: 12px"><el-table-column prop="name" label="卡名" /><el-table-column prop="remaining_count" label="剩余次数" /><el-table-column prop="valid_until" label="有效期" /><el-table-column label="操作"><template #default="scope"><el-button link type="primary" @click="$emit('consumePass', scope.row.id)">核销 1 次</el-button></template></el-table-column></el-table>
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<style scoped>
.pane-header { display: flex; align-items: center; justify-content: space-between; }.pane-header strong,.pane-header span { display:block }.pane-header span { margin-top:4px;color:var(--xq-text-3);font-size:11px }
</style>
