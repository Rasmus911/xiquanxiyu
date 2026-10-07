<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useRuntimeStore } from '../stores/runtime'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { usePageRefresh } from '../composables/usePageRefresh'
import { formatBusinessTime } from '../format/business-time'

const auth = useAuthStore()
const runtime = useRuntimeStore()
const rows = ref<Array<Record<string, any>>>([])
const loadingId = ref('')

async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  try {
    const data = apiData<Array<Record<string, any>>>(await http.get('/checkout/print-jobs')); if (!isCurrent()) return; rows.value = data
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function reprint(row: Record<string, any>) {
  const isCurrent = guardBusinessOperation('reprint')
  if (!isCurrent()) return

  if (!window.xiquan) return ElMessage.warning('请在桌面客户端中执行打印')
  loadingId.value = row.id
  const releaseBusy = await runtime.setBusinessBusy('正在提交打印结果')
  if (!isCurrent()) { await releaseBusy(); return }
  try {
    const receipt = apiData<Record<string, unknown>>(await http.get(`/checkout/${row.settlement_id}/receipt`)); if (!isCurrent()) return;
    const printerName = auth.terminal?.printer_name || localStorage.getItem('xiquan_printer_name') || undefined
    const result = await window.xiquan.printReceipt(receipt, printerName); if (!isCurrent()) return;
    await http.post(`/checkout/${row.settlement_id}/print-result`, result); if (!isCurrent()) return;
    result.success ? ElMessage.success('小票补打成功') : ElMessage.error(result.error || '打印失败')
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  } finally {
    if (isCurrent()) loadingId.value = ''
    await releaseBusy()
  }
}

usePageRefresh(load)
onMounted(load)
</script>

<template>
  <div class="page">
    <AppPageHeader title="小票补打" description="列表中的订单均已成功收款；这里只重新打印，不会再次扣款。" eyebrow="REPRINT"><template #actions><el-button @click="load">刷新</el-button></template></AppPageHeader>
    <el-card shadow="never"><el-table :data="rows"><el-table-column label="结账时间" min-width="170"><template #default="scope">{{ formatBusinessTime(scope.row.created_at) }}</template></el-table-column><el-table-column prop="settlement_number" label="结算单号" /><el-table-column label="收款状态" width="100"><template #default><el-tag type="success">已收款</el-tag></template></el-table-column><el-table-column prop="amount" label="金额"><template #default="scope">¥{{ scope.row.amount }}</template></el-table-column><el-table-column prop="status" label="打印状态"><template #default="scope"><el-tag :type="scope.row.status === 'failed' ? 'danger' : 'warning'">{{ scope.row.status === 'failed' ? '打印失败' : '待打印' }}</el-tag></template></el-table-column><el-table-column prop="attempts" label="尝试次数" /><el-table-column prop="last_error" label="失败原因" min-width="220" /><el-table-column label="操作"><template #default="scope"><el-button type="primary" :loading="loadingId === scope.row.id" :disabled="Boolean(loadingId) && loadingId !== scope.row.id" @click="reprint(scope.row)">重新打印</el-button></template></el-table-column></el-table><el-empty v-if="!rows.length" description="没有待补打小票" /></el-card>
  </div>
</template>

