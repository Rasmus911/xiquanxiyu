import { expect, it } from 'vitest'
import { getReleaseHistory, historyDateLabel } from './release-history'

it('includes the approved 0.5.6 inventory log without inventing publication time', () => {
  const latest = getReleaseHistory()[0]!
  expect(latest.version).toBe('0.5.6')
  expect(latest.notes).toEqual(['给桌面端的图标做出更换', '优化“库存”页面布局'])
  expect(latest.state).toBe('pending')
  expect(historyDateLabel(latest)).toBe('待发布')
})

it('includes every approved log in numeric version order without inventing dates', () => {
  expect(getReleaseHistory().map(row => row.version)).toEqual(['0.5.6', '0.5.5', '0.5.4', '0.5.3', '0.5.2', '0.5.1', '0.5.0', '0.4.9', '0.4.8', '0.4.7'])
  const rows = getReleaseHistory().slice(5)
  expect(rows[0]!.notes).toEqual(['增加实体卡消费功能'])
  expect(historyDateLabel(rows[0]!)).toBe('待发布')
  expect(rows[1]!.notes).toEqual(['优化主登录页面', '新增账号密码修改功能', '新增搓澡师下单打印小票的功能', '新增每天小票补打的功能'])
  expect(rows[2]!.notes).toEqual(['新增 账号注册功能'])
  expect(rows[3]!.source).toBe('backfilled')
  expect(rows[3]!.notes).toEqual(['澡巾、备品、搓泥宝按服务项目下单', '加单后弹窗选择耗材', '库存及项目商品每页十项，右上角换页', '库存成本单价可编辑，首次赋值免密码，后续修改核对本人密码', '手机版同步更新'])
  expect(rows[4]!.notes).toEqual(['给前台收银和库管增补“经营报表”权限', '“经营报表”UI优化', '“库存管理”界面 UI优化', '库存预警值设置为商品入库数量的15%'])
  expect(rows[3]!.publishedAt).toBeNull()
  expect(historyDateLabel(rows[3]!)).toBe('发布日期未核实')
  expect(historyDateLabel(rows[4]!)).toBe('发布日期未核实')
})

it('formats signed historical publication metadata in Shanghai time', () => {
  const rows = getReleaseHistory().slice(5)
  expect(rows[1]!.publishedAt).toBe('2026-10-11T16:23:00.648Z')
  expect(historyDateLabel(rows[1]!)).toBe('2026/10/12 00:23')
  expect(rows[2]!.publishedAt).toBe('2026-10-08T12:21:56.498Z')
  expect(historyDateLabel(rows[2]!)).toBe('2026/10/08 20:21')
})

it('only promotes the matching row when verified metadata has a valid ISO timestamp', () => {
  const rows = getReleaseHistory({ version: '0.5.1', publishedAt: '2026-10-12T01:02:03Z' }).slice(5)
  expect(rows[0]!.state).toBe('published')
  expect(historyDateLabel(rows[0]!)).toBe('2026/10/12 09:02')
  expect(rows[3]!.state).toBe('unverified')
  expect(getReleaseHistory({ version: '9.9.9', publishedAt: '2026-10-12T01:02:03Z' })).toHaveLength(10)
})

it.each(['', 'not-a-date', '2026-10-12', '10/12/2026', '2026-02-30T00:00:00Z', '2026-10-12T25:00:00Z'])('rejects invalid publication metadata %s', publishedAt => {
  expect(getReleaseHistory({ version: '0.5.1', publishedAt }).find(row => row.version === '0.5.1')!.state).toBe('pending')
  expect(historyDateLabel({ version: '0.5.1', publishedAt, state: 'published', source: 'user', notes: [] })).toBe('发布日期未核实')
})

it('returns independent history rows so consumers cannot overwrite offline logs', () => {
  const rows = getReleaseHistory()
  rows[0]!.notes.push('changed')
  rows[0]!.state = 'published'
  expect(getReleaseHistory()[0]!.notes).toEqual(['给桌面端的图标做出更换', '优化“库存”页面布局'])
  expect(getReleaseHistory()[0]!.state).toBe('pending')
})
