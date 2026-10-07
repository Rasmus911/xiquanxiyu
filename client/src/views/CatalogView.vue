<script setup lang="ts">
import { canAccess, canCapability, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import { subscribeRealtime } from '../realtime/events'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import type { CatalogItem } from '../types'

const rows = ref<CatalogItem[]>([])
const drawerOpen = ref(false)
const keyword = ref('')
const kindFilter = ref('')
const includeInactive = ref(false)
const page = ref(1)
const adminManagement = computed(() => canCapability('catalog_write') || canAccess('employee:write'))
const deleting = ref(false)
const saving = ref(false)
const editingId = ref('')
const form = reactive({ kind: 'service', category: '默认', name: '', mobile_scope: 'frontdesk', price: 0, stock_tracked: false, low_stock_threshold: 0, sort_order: 0, is_active: true })
let unsubscribeRealtime: (() => void) | undefined
const kindNames: Record<string, string> = { ticket: '门票', service: '服务', product: '商品', compensation: '赔偿', package: '套票' }
const mobileScopeNames: Record<string, string> = { frontdesk: '仅前台', scrub: '搓澡端', rest: '三层服务端', both: '全部手机端' }
const filteredRows = computed(() => rows.value.filter((row) => {
  if (kindFilter.value && row.kind !== kindFilter.value) return false
  if (!includeInactive.value && !row.is_active) return false
  const query = keyword.value.trim()
  return !query || row.name.includes(query) || row.category.includes(query)
}))
const pagedRows = computed(() => filteredRows.value.slice((page.value-1)*10,page.value*10))
watch([keyword,kindFilter,includeInactive],()=>{page.value=1})
watch(()=>filteredRows.value.length,length=>{page.value=Math.min(page.value,Math.max(1,Math.ceil(length/10)))})

async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  try { const data = apiData<CatalogItem[]>(await http.get('/catalog', {params:{active: !(adminManagement.value && includeInactive.value)}})); if (!isCurrent()) return; rows.value = data } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
}

function createNew() {
  if (!canAccess('catalog:write')) return
  editingId.value = ''
  Object.assign(form, { kind: 'service', category: '默认', name: '', mobile_scope: 'frontdesk', price: 0, stock_tracked: false, low_stock_threshold: 0, sort_order: 0, is_active: true })
  drawerOpen.value = true
}

function edit(row: CatalogItem) {
  if (!canAccess('catalog:write') || row.can_edit !== true) return
  editingId.value = row.id
  Object.assign(form, { kind:row.kind, category:row.category, name:row.name, mobile_scope:row.mobile_scope || 'frontdesk', price:Number(row.price), stock_tracked:row.stock_tracked, low_stock_threshold:Number(row.low_stock_threshold || 0), sort_order:row.sort_order, is_active:row.is_active })
  drawerOpen.value = true
}

async function save() {
  if (saving.value) return
  if (!canAccess('catalog:write') || (editingId.value && !rows.value.some(row => row.id === editingId.value && row.can_edit === true))) return
  const isCurrent = guardBusinessOperation('save')
  if (!isCurrent()) return

  saving.value = true
  try {
    if (editingId.value) await http.patch(`/catalog/${editingId.value}`, form)
    else await http.post('/catalog', form); if (!isCurrent()) return;
    ElMessage.success('保存成功')
    drawerOpen.value = false
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) saving.value = false }
}

async function remove(row: CatalogItem) {
  if (deleting.value || !canCapability('catalog_delete') || !canAccess('catalog:delete')) return
  const isCurrent = guardBusinessOperation('delete')
  if (!isCurrent()) return
  deleting.value = true
  try {
    const { value } = await ElMessageBox.prompt(`确认删除“${row.name}”？历史账单保留。请输入本人登录密码。`, '删除项目', { inputType:'password', inputPattern:/\S+/, inputErrorMessage:'请输入本人登录密码', type:'warning', confirmButtonText:'确认删除' })
    if (!isCurrent()) return
    await http.delete(`/catalog/${row.id}`, {data:{password:value}})
    if (!isCurrent()) return
    rows.value = rows.value.filter(item => item.id !== row.id)
    if (editingId.value === row.id) drawerOpen.value = false
    ElMessage.success('项目已删除')
  } catch(error) { if (isCurrent() && error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) deleting.value = false }
}

onMounted(() => {
  load()
  unsubscribeRealtime = subscribeRealtime(['catalog', 'inventory'], () => load())
})
onBeforeUnmount(() => unsubscribeRealtime?.())
watch(includeInactive, () => load())
</script>

<template>
  <div class="page">
    <AppPageHeader title="服务与商品" description="价格修改会刷新未结账项目，已结账快照保留；手机端只显示其岗位允许销售的项目。" eyebrow="CATALOG"><template #actions><el-button v-if="canAccess('catalog:write')" type="primary" @click="createNew">新增项目</el-button></template></AppPageHeader>
    <div class="catalog-filters"><el-input v-model="keyword" clearable prefix-icon="Search" placeholder="搜索名称或分类" /><el-select v-model="kindFilter" clearable placeholder="全部类型"><el-option v-for="(name, key) in kindNames" :key="key" :label="name" :value="key" /></el-select><el-checkbox v-if="adminManagement" v-model="includeInactive" data-testid="inactive-filter">包含停用项目</el-checkbox></div>
    <el-card shadow="never"><template #header><div class="catalog-table-header"><strong>服务与商品</strong><el-pagination v-model:current-page="page" :page-size="10" :total="filteredRows.length" layout="total, prev, pager, next" background/></div></template><el-table :data="pagedRows">
      <el-table-column label="类型" width="85"><template #default="scope"><el-tag>{{ kindNames[scope.row.kind] }}</el-tag></template></el-table-column>
      <el-table-column prop="category" label="分类" width="120" /><el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="手机端权限" width="130"><template #default="scope"><el-tag type="info">{{ mobileScopeNames[scope.row.mobile_scope] }}</el-tag></template></el-table-column>
      <el-table-column prop="price" label="售价" width="110"><template #default="scope">¥{{ scope.row.price }}</template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="scope"><el-tag :type="scope.row.is_active ? 'success' : 'info'">{{ scope.row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="150"><template #default="scope"><el-button v-if="canAccess('catalog:write') && scope.row.can_edit === true" data-testid="catalog-edit" link type="primary" @click="edit(scope.row)">编辑</el-button><span v-else class="muted">只读</span><el-button v-if="canCapability('catalog_delete') && canAccess('catalog:delete')" data-testid="catalog-delete" link type="danger" :disabled="deleting" @click="remove(scope.row)">删除</el-button></template></el-table-column>
    </el-table></el-card>
    <el-drawer v-model="drawerOpen" :title="editingId ? '编辑项目' : '新增项目'" size="520px">
      <el-form label-position="top">
        <el-row :gutter="12"><el-col :span="12"><el-form-item label="类型"><el-select v-model="form.kind" :disabled="Boolean(editingId)" class="full-width"><el-option v-for="(name, key) in kindNames" v-show="key === 'package' ? form.kind === 'package' && Boolean(editingId) : adminManagement || ['service','product'].includes(key)" :key="key" :label="name" :value="key" /></el-select></el-form-item></el-col><el-col :span="12"><el-form-item label="分类"><el-input v-model="form.category" /></el-form-item></el-col></el-row>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="手机端销售范围"><el-select v-model="form.mobile_scope" class="full-width"><el-option v-for="(name, key) in mobileScopeNames" :key="key" :label="name" :value="key" /></el-select><div class="muted" style="margin-top: 6px">门票、赔偿等请选择“仅前台”；搓澡与三层人员只会看到各自允许的项目。</div></el-form-item>
        <el-row :gutter="12"><el-col :span="12"><el-form-item label="售价"><el-input-number v-model="form.price" :min="0" :precision="2" class="full-width" /></el-form-item></el-col><el-col :span="12"><el-form-item label="排序"><el-input-number v-model="form.sort_order" class="full-width" /></el-form-item></el-col></el-row>
        <el-form-item v-if="editingId" label="状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="drawerOpen = false">取消</el-button><el-button data-testid="catalog-save" type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-drawer>
  </div>
</template>
<style scoped>.catalog-filters{display:flex;gap:9px;margin-bottom:14px}.catalog-filters .el-input{max-width:280px}.catalog-filters .el-select{width:150px}.catalog-table-header{display:flex;align-items:center;justify-content:space-between;gap:12px}</style>
