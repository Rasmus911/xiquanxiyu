// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import InventoryAddSheet from './InventoryAddSheet.vue'
let clean = () => {}
afterEach(() => clean())
it('previews four packages as 800 base units and emits the original input unit', async () => {
  const root=document.createElement('div'); document.body.append(root)
  const values: unknown[]=[]
  const app=createApp({render:()=>h(InventoryAddSheet,{item:{id:'s',name:'奶浴袋',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200.000',package_spec:'1*200',stock_quantity:'800.000',low_stock_threshold:'20.000',is_active:true,version:3},saving:false,onSave:v=>values.push({...v})})})
  app.mount(root); clean=()=>{app.unmount();root.remove()}
  const input=root.querySelector('input')!; input.value='4'; input.dispatchEvent(new Event('input'))
  const unit=root.querySelector('select'); expect(unit).not.toBeNull()
  unit!.value='package'; unit!.dispatchEvent(new Event('change')); await nextTick()
  expect(root.textContent).toContain('800.000 袋')
  root.querySelector<HTMLButtonElement>('.primary-button')!.click(); await nextTick()
  expect(values).toEqual([{quantity:'4',input_unit:'package',reason:'采购入库',movement_type:'purchase'}])
})

it.each([['1.001','1.001'],['500000000','2'],['1000000000','1'],['1','1000000000'],['-1','1'],['NaN','1'],['Infinity','1']])('blocks invalid receipt %s × %s then permits exact correction',async(quantity,factor)=>{
  const root=document.createElement('div');document.body.append(root);const values:unknown[]=[]
  const item={id:'s',name:'耗材',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:factor,package_spec:'规格',stock_quantity:'0',low_stock_threshold:'0',is_active:true,version:3}
  const app=createApp({render:()=>h(InventoryAddSheet,{item,saving:false,onSave:value=>values.push({...value})})});app.mount(root);clean=()=>{app.unmount();root.remove()}
  const field=root.querySelector('input')!;field.value=quantity;field.dispatchEvent(new Event('input'))
  const unit=root.querySelector('select')!;unit.value='package';unit.dispatchEvent(new Event('change'));await nextTick()
  const button=root.querySelector<HTMLButtonElement>('.primary-button')!
  expect(button.disabled).toBe(true);expect(root.querySelector('[role="alert"]')?.textContent).toBeTruthy()
  button.click();button.dispatchEvent(new MouseEvent('click',{bubbles:true}));await nextTick();expect(values).toEqual([])
  // Correct in base units so a malformed server factor cannot influence the input.
  unit.value='base';unit.dispatchEvent(new Event('change'));field.value='2.002';field.dispatchEvent(new Event('input'));await nextTick()
  expect(button.disabled).toBe(false);expect(root.querySelector('[role="alert"]')).toBeNull();button.click();await nextTick()
  expect(values).toEqual([{quantity:'2.002',input_unit:'base',reason:'采购入库',movement_type:'purchase'}])
})

it('accepts the fractional package product 2 × 1.001 without changing the original input',async()=>{
  const root=document.createElement('div');document.body.append(root);const values:unknown[]=[]
  const app=createApp({render:()=>h(InventoryAddSheet,{item:{id:'s',name:'耗材',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'1.001',package_spec:'规格',stock_quantity:'0',low_stock_threshold:'0',is_active:true,version:3},saving:false,onSave:value=>values.push({...value})})});app.mount(root);clean=()=>{app.unmount();root.remove()}
  const field=root.querySelector('input')!;field.value='2';field.dispatchEvent(new Event('input'));const unit=root.querySelector('select')!;unit.value='package';unit.dispatchEvent(new Event('change'));await nextTick()
  expect(root.textContent).toContain('2.002 袋');root.querySelector<HTMLButtonElement>('.primary-button')!.click();await nextTick();expect(values).toEqual([{quantity:'2',input_unit:'package',reason:'采购入库',movement_type:'purchase'}])
})
