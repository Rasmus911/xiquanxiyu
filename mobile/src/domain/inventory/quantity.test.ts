import { expect, it } from 'vitest'
import { previewStockQuantity, validQuantity } from './quantity'

it('requires exact thousandths in the converted product rather than rounding',()=>{
  expect(previewStockQuantity('1.001','package','1.001')).toBe('—')
  expect(previewStockQuantity('0.001','package','0.001')).toBe('—')
  expect(previewStockQuantity('2','package','1.001')).toBe('2.002')
  expect(previewStockQuantity('4','package','200')).toBe('800.000')
  expect(previewStockQuantity('0','package','1.001')).toBe('0.000')
})

it.each(['1000000000','9999999999','999999999999999999999999999999999999999','1.0001','NaN','Infinity','-1','1e3'])('bounds stock operand %s before conversion', value=>{
  expect(validQuantity(value)).toBe(false)
  expect(previewStockQuantity(value,'base','1')).toBe('—')
  expect(previewStockQuantity('1','package',value)).toBe('—')
})

it('rejects overflow only after exact multiplication, allowing the largest server value',()=>{
  expect(validQuantity('999999999.999')).toBe(true)
  expect(previewStockQuantity('999999999.999','base','1')).toBe('999999999.999')
  expect(previewStockQuantity('500000000','package','2')).toBe('—')
  expect(previewStockQuantity('100000000','package','9.999')).toBe('999900000.000')
})
