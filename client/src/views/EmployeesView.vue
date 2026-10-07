<script setup lang="ts">
import { canAccess, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { usePageRefresh } from '../composables/usePageRefresh'
import type { Employee } from '../types'
const rows = ref<Employee[]>([]); const drawerOpen = ref(false); const editingId = ref('')
type Channel = 'desktop' | 'web' | 'mobile'
const form = reactive({ username: '', display_name: '', password: '', role: 'cashier', is_active: true, unlock: false, allowed_channels: ['desktop', 'web'] as Channel[] })
const deletedFilter = ref('exclude')
const saving = ref(false)
const deleting = ref('')
const protectedEditing = ref(false)
let hydrating = false
const roleChannels: Record<string, Channel[]> = {
  cashier: ['desktop', 'web'], inventory: ['desktop', 'web', 'mobile'],
  male_scrubber: ['desktop', 'web', 'mobile'], female_scrubber: ['desktop', 'web', 'mobile'],
  floor_attendant: ['desktop', 'web', 'mobile'], manager: ['desktop', 'web'],
}
const channelNames: Record<Channel, string> = { desktop: '桌面端', web: '网页端', mobile: '手机端' }
watch(() => form.role, role => { if (!hydrating && !protectedEditing.value) form.allowed_channels = [...(roleChannels[role] || [])] }, { flush: 'sync' })
watch(deletedFilter, () => { void load() })
const roleNames: Record<string, string> = { male_scrubber: '男浴搓澡师', female_scrubber: '女浴搓澡师', floor_attendant: '三层服务员', cashier: '收银员', inventory: '库管', manager: '经理', admin: '系统管理员' }
async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return
 try { const data = apiData<Employee[]>(await http.get('/employees', { params: { deleted: deletedFilter.value } })); if (!isCurrent()) return; rows.value = data } catch (error) { if (!isCurrent()) return; ElMessage.error(apiErrorMessage(error)) } }
function createNew() {
  if (saving.value) return
  editingId.value = ''; protectedEditing.value = false
  Object.assign(form, { username: '', display_name: '', password: '', role: 'cashier', is_active: true, unlock: false, allowed_channels: ['desktop', 'web'] })
  drawerOpen.value = true
}
function edit(row: Employee) {
  if (saving.value || row.deleted_at) return
  editingId.value = row.id; protectedEditing.value = row.protected_account === true; hydrating = true
  Object.assign(form, { username: row.username, display_name: row.display_name, password: '', role: row.role,
    is_active: row.is_active, unlock: false, allowed_channels: [...(row.allowed_channels || [])] })
  hydrating = false; drawerOpen.value = true
}
async function save() {
  const isCurrent = guardBusinessOperation('save')
  if (!isCurrent() || saving.value) return
  saving.value = true
  const target = editingId.value
  const payload = protectedEditing.value
    ? { display_name: form.display_name, password: form.password, unlock: form.unlock }
    : { ...form, allowed_channels: [...form.allowed_channels] }
  try {
    if (target) await http.patch(`/employees/${target}`, payload)
    else await http.post('/employees', payload)
    if (!isCurrent()) return
    form.password = ''; ElMessage.success('员工保存成功'); drawerOpen.value = false; await load()
  } catch (error) { if (isCurrent()) ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) saving.value = false }
}
async function remove(row: Employee) {
  if (row.protected_account || row.deleted_at || deleting.value) return
  const isCurrent = guardBusinessOperation('delete')
  deleting.value = row.id
  try {
    await ElMessageBox.confirm(`删除 ${row.display_name}（${row.username}）？将停用并退出该员工，历史操作记录永久保留。`, '删除员工账号', { type: 'warning', confirmButtonText: '删除账号', cancelButtonText: '取消' })
    if (!isCurrent()) return
    await http.delete(`/employees/${row.id}`)
    if (!isCurrent()) return
    ElMessage.success('账号已删除，历史操作记录保留'); await load()
  } catch (error) { if (isCurrent() && error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) deleting.value = '' }
}
usePageRefresh(load)
onMounted(load)
</script>
<template>
  <div class="page">
    <AppPageHeader title="员工账号" description="岗位、可用入口与启用状态一次保存；删除保留历史责任记录。">
      <template #actions><el-button v-if="canAccess('*')" type="primary" @click="createNew">新增员工</el-button></template>
    </AppPageHeader>
    <el-card shadow="never">
      <el-radio-group v-model="deletedFilter" style="margin-bottom: 16px">
        <el-radio-button value="exclude">在职账号</el-radio-button><el-radio-button value="only">已删除账号</el-radio-button>
      </el-radio-group>
      <el-table :data="rows">
        <el-table-column prop="username" label="登录账号" /><el-table-column prop="display_name" label="员工姓名" />
        <el-table-column label="岗位"><template #default="{ row }">{{ roleNames[row.role] }}</template></el-table-column>
        <el-table-column label="可用入口" min-width="180"><template #default="{ row }">
          <el-tag v-if="row.protected_account" type="warning">既有管理员 · 策略绑定</el-tag>
          <span v-else>{{ row.allowed_channels?.map((channel: Channel) => channelNames[channel]).join(' / ') || '待授权' }}</span>
        </template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.deleted_at ? '已删除' : row.is_active ? '启用' : '停用' }}</el-tag>
        </template></el-table-column>
        <el-table-column v-if="canAccess('*')" label="操作" width="150"><template #default="{ row }">
          <el-button v-if="!row.deleted_at" link type="primary" @click="edit(row)">编辑</el-button>
          <el-button v-if="!row.deleted_at && !row.protected_account" link type="danger" :loading="deleting === row.id" @click="remove(row)">删除</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>
    <el-drawer v-model="drawerOpen" :title="editingId ? '编辑员工' : '新增员工'" size="480px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-alert v-if="protectedEditing" type="info" :closable="false" title="此账号受保护，不在普通员工表单中变更角色、入口或启用状态。" style="margin-bottom: 16px" />
      <el-form label-position="top" @submit.prevent="save">
        <el-form-item label="登录账号"><el-input id="employee-username" v-model="form.username" :disabled="Boolean(editingId) || saving" maxlength="50" /></el-form-item>
        <el-form-item label="员工姓名"><el-input id="employee-name" v-model="form.display_name" :disabled="saving" maxlength="80" /></el-form-item>
        <el-form-item :label="editingId ? '新密码（留空不修改）' : '初始密码'"><el-input id="employee-password" v-model="form.password" type="password" show-password :disabled="saving" autocomplete="new-password" /></el-form-item>
        <el-form-item label="岗位">
          <el-tag v-if="protectedEditing">{{ roleNames[form.role] }}</el-tag>
          <el-select v-else v-model="form.role" class="full-width" :disabled="saving"><el-option v-for="(_, role) in roleChannels" :key="role" :label="roleNames[role]" :value="role" /></el-select>
        </el-form-item>
        <template v-if="!protectedEditing">
          <el-form-item label="允许使用的入口"><el-checkbox-group v-model="form.allowed_channels" :disabled="saving">
            <el-checkbox v-for="channel in roleChannels[form.role]" :key="channel" :value="channel">{{ channelNames[channel] }}</el-checkbox>
          </el-checkbox-group></el-form-item>
          <el-form-item><el-switch v-model="form.is_active" active-text="启用账号" :disabled="saving" /></el-form-item>
        </template>
        <el-form-item v-if="editingId"><el-checkbox v-model="form.unlock" :disabled="saving">解除登录锁定（撤销该员工旧会话）</el-checkbox></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="drawerOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-drawer>
  </div>
</template>
