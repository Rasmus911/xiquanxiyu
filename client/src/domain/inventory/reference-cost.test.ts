import {expect,it} from 'vitest'
import {referenceCostPreview,costBaseChanged} from './reference-cost'
it.each([
 ['120','package','200','120.00','0.600000'],['0.60','base','200','120.00','0.600000'],
 ['1','package','3','1.00','0.333333'],['0','base','200','0.00','0.000000'],
])('converts %s/%s at %s without rounding the authoritative amount',(amount,basis,factor,packageCost,baseCost)=>{
 expect(referenceCostPreview(amount,basis as 'base'|'package',factor)).toEqual({packageCost,baseCost})
})
it('distinguishes missing cost from zero and rejects negative and over-precision input',()=>{
 for(const value of ['','-1','0.001','NaN','10000000000'])expect(referenceCostPreview(value,'base','200')).toBeNull()
 expect(referenceCostPreview('0','package','0')).toBeNull()
})
it('authenticates factor changes when they alter an existing authoritative box cost',()=>{
 expect(costBaseChanged({reference_cost:'120',cost_basis:'package',unit_cost:'0.60',units_per_package:'200',package_unit:'箱'},'120','package','100',true)).toBe(true)
 expect(costBaseChanged({reference_cost:'120',cost_basis:'package',unit_cost:'0.60',units_per_package:'200',package_unit:'箱'},'0.60','base','200',true)).toBe(false)
 expect(costBaseChanged({unit_cost:null,units_per_package:'200',package_unit:'箱'},'0','base','200',true)).toBe(false)
})
