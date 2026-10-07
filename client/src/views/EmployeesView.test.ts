import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox, ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import EmployeesView from './EmployeesView.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import { getAccessToken, setAccessToken } from '../auth/session'

const existing = { id: 'protected', username: 'fixed-admin', display_name: '原管理员', role: 'admin',
  is_active: true, allowed_channels: [], deleted_at: null, protected_account: true, mobile_full_access: true }
const ordinary = { id: 'ordinary', username: 'worker', display_name: '员工甲', role: 'cashier',
  is_active: true, allowed_channels: ['desktop', 'web'], deleted_at: null, protected_account: false }
const calls: Array<{ method: string; url: string; body: any; deleted?: string }> = []
let denySave = false
beforeEach(() => {
  clearBusinessSession(); setAccessToken('current')
  acceptBusinessState({ period_id: 'fixture', policy_version: 1, business_revision: 0,
    maintenance: false, owner_reset_allowed: true }, ['*'])
  calls.length = 0; denySave = false
  http.defaults.adapter = async config => {
    calls.push({ method: String(config.method), url: String(config.url),
      body: config.data ? JSON.parse(config.data) : undefined, deleted: config.params?.deleted })
    const response = { config, headers: {}, status: 200, statusText: '', data: { data: config.method === 'get' ? [existing, ordinary] : ordinary } }
    if (denySave && config.method !== 'get') throw new AxiosError('denied', '', config, undefined,
      { ...response, status: 403, data: { message: '当前操作没有权限', error: { code: 'PERMISSION_DENIED' } } } as any)
    return response
  }
})
afterEach(() => { vi.restoreAllMocks(); ElMessage.closeAll(); clearBusinessSession() })

it('new inventory employee saves explicit entry grants and actual enabled state', async () => {
  const wrapper = mount(EmployeesView, { global: { plugins: [ElementPlus] } })
  try {
    await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '新增员工')!.trigger('click')
    await wrapper.find('#employee-username').setValue('stock-worker')
    await wrapper.find('#employee-name').setValue('库管甲')
    await wrapper.find('#employee-password').setValue('fixture-stock-2026')
    await wrapper.findComponent(ElSelect).setValue('inventory')
    await flushPromises()
    expect(wrapper.text()).toContain('手机端')
    await wrapper.findAll('button').find(node => node.text() === '保存')!.trigger('click')
    await flushPromises()
    const request = calls.find(row => row.method === 'post')!
    expect(request.body).toMatchObject({ username: 'stock-worker', display_name: '库管甲', role: 'inventory',
      allowed_channels: ['desktop', 'web', 'mobile'], is_active: true })
    expect(request.body).not.toHaveProperty('permission_scope')
    expect(request.body).not.toHaveProperty('mobile_full_access')
  } finally { wrapper.unmount() }
})
it('only ordinary rows can be deleted and cancellation never sends DELETE', async () => {
  const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
  const wrapper = mount(EmployeesView, { global: { plugins: [ElementPlus] } })
  try {
    await flushPromises()
    const rows = wrapper.findAll('.el-table__body tr')
    expect(rows.find(row => row.text().includes('fixed-admin'))!.text()).not.toContain('删除')
    const button = rows.find(row => row.text().includes('worker'))!.findAll('button').find(node => node.text() === '删除')!
    await button.trigger('click'); await flushPromises()
    expect(calls.filter(row => row.method === 'delete')).toEqual([])
    confirm.mockResolvedValue('confirm' as any)
    await button.trigger('click'); await flushPromises()
    expect(calls.filter(row => row.method === 'delete').map(row => row.url)).toEqual(['/employees/ordinary'])
  } finally { wrapper.unmount() }
})
it('deleted filter requests only deleted employees', async () => {
  const wrapper = mount(EmployeesView, { global: { plugins: [ElementPlus] } })
  try {
    await flushPromises()
    await wrapper.findAll('label').find(node => node.text() === '已删除账号')!.find('input').setValue(true)
    await flushPromises()
    expect(calls.at(-1)?.deleted).toBe('only')
  } finally { wrapper.unmount() }
})
it('an action denial leaves the employee form and operator login intact', async () => {
  const wrapper = mount(EmployeesView, { global: { plugins: [ElementPlus] } })
  try {
    await flushPromises()
    const row = wrapper.findAll('.el-table__body tr').find(node => node.text().includes('worker'))!
    await row.findAll('button').find(node => node.text() === '编辑')!.trigger('click')
    denySave = true
    await wrapper.findAll('button').find(node => node.text() === '保存')!.trigger('click'); await flushPromises()
    expect(wrapper.find('#employee-name').exists()).toBe(true)
    expect(getAccessToken()).toBe('current')
    expect(document.body.textContent).toContain('当前操作没有权限')
  } finally { wrapper.unmount() }
})
