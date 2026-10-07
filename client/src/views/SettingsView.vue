<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import BusinessResetPanel from '../components/settings/BusinessResetPanel.vue'
import DesktopCompatibility from '../components/settings/DesktopCompatibility.vue'
import { usePageRefresh } from '../composables/usePageRefresh'

interface PrinterInfo {
  name: string
  displayName?: string
  description?: string
  status?: number
  isDefault?: boolean
}

const auth = useAuthStore()
const isDesktop = Boolean(window.xiquan)
const printers = ref<PrinterInfo[]>([])
const printerLoading = ref(false)
const printerError = ref('')
const form = reactive({
  store_name: '溪泉洗浴',
  lost_wristband_fee: 20,
  printer_name: localStorage.getItem('xiquan_printer_name') || '',
})

async function refreshPrinters(showMessage = true) {
  const isCurrent = guardBusinessOperation('refreshPrinters')
  if (!isCurrent()) return

  printerLoading.value = true
  printerError.value = ''
  try {
    if (!window.xiquan) throw new Error('当前是浏览器模式，只有安装后的桌面版可以读取本机打印机')
    const data = await window.xiquan.getPrinters(); if (!isCurrent()) return; printers.value = data
    if (showMessage) {
      if (printers.value.length) ElMessage.success(`检测到 ${printers.value.length} 台打印机`)
      else ElMessage.warning('未自动检测到打印机，可以直接输入 Windows 中的打印机名称')
    }
  } catch (error) { if (!isCurrent()) return; 
    printerError.value = error instanceof Error ? error.message : '读取打印机失败'
    if (showMessage) ElMessage.error(printerError.value)
  } finally { if (!isCurrent()) return; 
    printerLoading.value = false
  }
}

async function loadSettings() {
  const isCurrent = guardBusinessOperation('loadSettings')
  if (!isCurrent()) return

  try {
    const settings = apiData<Array<{ key: string; value: unknown }>>(await http.get('/settings')); if (!isCurrent()) return;
    for (const row of settings) {
      if (row.key in form) {
        ;(form as Record<string, unknown>)[row.key] = row.key === 'lost_wristband_fee'
          ? Number(row.value)
          : row.value
      }
    }
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
  // 本机打印机扫描必须独立执行，不能因为云端设置读取失败而跳过。
  await refreshPrinters(false); if (!isCurrent()) return;
}

async function save() {
  const isCurrent = guardBusinessOperation('save')
  if (!isCurrent()) return

  try {
    const printerName = form.printer_name.trim()
    form.printer_name = printerName
    await Promise.all([
      http.put('/settings/store_name', { value: form.store_name }),
      http.put('/settings/lost_wristband_fee', { value: form.lost_wristband_fee }),
    ]); if (!isCurrent()) return;
    localStorage.setItem('xiquan_printer_name', printerName)
    if (window.xiquan) {
      const currentConfig = await window.xiquan.getConfig(); if (!isCurrent()) return;
      await window.xiquan.setConfig({ ...currentConfig, printerName }); if (!isCurrent()) return;
    }
    if (auth.terminal) await http.patch(`/terminals/${auth.terminal.id}`, { printer_name: printerName }); if (!isCurrent()) return;
    ElMessage.success(`设置保存成功${printerName ? `，当前打印机：${printerName}` : '，打印时使用 Windows 默认打印机'}`)
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function testPrint() {
  const isCurrent = guardBusinessOperation('testPrint')
  if (!isCurrent()) return

  if (!window.xiquan) return ElMessage.warning('浏览器模式不能静默打印，请打开桌面版 EXE')
  const printerName = form.printer_name.trim()
  const result = await window.xiquan.printReceipt({
    store_name: form.store_name,
    settlement: {
      number: 'TEST-001',
      completed_at: new Date().toLocaleString(),
      total_amount: '20.00',
    },
    visits: [{
      wristband_number: '001',
      amount: '20.00',
      items: [{ name: 'XP-58 打印测试项目', quantity: '1', total_amount: '20.00' }],
    }],
    payments: [{ method: 'cash', amount: '20.00' }],
    print_attempts: 0,
  }, printerName || undefined); if (!isCurrent()) return;
  result.success
    ? ElMessage.success(`测试小票已发送到${printerName || ' Windows 默认打印机'}`)
    : ElMessage.error(`${printerName ? `打印机 ${printerName}` : '默认打印机'}打印失败：${result.error || '未知错误'}`)
}

usePageRefresh(loadSettings)
onMounted(loadSettings)
</script>

<template>
  <div class="page">
    <AppPageHeader title="系统设置" description="营业参数与当前电脑的 58mm 热敏打印机设置。" eyebrow="SYSTEM" />
    <el-alert class="runtime-alert" :type="isDesktop ? 'success' : 'warning'" :closable="false" show-icon :title="isDesktop ? '当前运行在桌面 EXE，可检测并静默打印' : '当前运行在浏览器，只能保存营业参数，不能静默打印'" />
    <el-card shadow="never" style="max-width: 700px">
      <el-form label-position="top">
        <el-form-item label="店铺名称"><el-input v-model="form.store_name" /></el-form-item>
        <el-form-item label="手牌挂失赔偿金额"><el-input-number v-model="form.lost_wristband_fee" :min="0" :precision="2" /></el-form-item>
        <el-alert title="清空账单须由管理员或经理输入自己的登录密码并填写原因，共享清空密码已停用。" type="info" :closable="false" />
        <el-divider>当前终端打印设置</el-divider>
        <el-form-item label="58mm 热敏打印机">
          <div class="printer-row">
            <el-select
              v-model="form.printer_name"
              filterable
              allow-create
              default-first-option
              clearable
              class="full-width"
              placeholder="选择或直接输入打印机名称，例如 XP-58"
            >
              <el-option
                v-for="printer in printers"
                :key="printer.name"
                :label="`${printer.displayName || printer.name}${printer.isDefault ? '（Windows 默认）' : ''}`"
                :value="printer.name"
              />
            </el-select>
            <el-button :loading="printerLoading" @click="refreshPrinters()">重新扫描</el-button>
          </div>
          <div class="printer-help">
            <span v-if="printers.length">桌面端检测到 {{ printers.length }} 台打印机；也可以直接输入准确名称。</span>
            <span v-else>未自动列出时，请直接输入 <strong>XP-58</strong>。留空则使用 Windows 默认打印机。</span>
          </div>
          <el-alert v-if="printerError" :title="printerError" type="warning" :closable="false" show-icon />
        </el-form-item>
        <div class="toolbar"><el-button @click="testPrint">测试打印</el-button><el-button type="primary" @click="save">保存设置</el-button></div>
      </el-form>
    </el-card>
    <DesktopCompatibility v-if="isDesktop" />
    <BusinessResetPanel />
  </div>
</template>

<style scoped>
.printer-row { display: flex; width: 100%; gap: 10px; }
.printer-row .el-button { flex: 0 0 auto; }
.printer-help { width: 100%; margin-top: 7px; color: #8791a5; font-size: 12px; }
.runtime-alert { max-width: 700px; margin-bottom: 14px; }
</style>
