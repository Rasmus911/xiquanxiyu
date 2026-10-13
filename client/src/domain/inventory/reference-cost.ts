export type CostBasis='base'|'package'
interface Reference {reference_cost?:string|null;cost_basis?:CostBasis|null;unit_cost?:string|null;units_per_package:string;package_unit:string}
function scaled(raw:string,digits:number){if(!new RegExp(`^\\d+(?:\\.\\d{1,${digits}})?$`).test(raw.trim())||raw.length>24)return null;const [whole,fraction='']=raw.trim().split('.');return BigInt(whole!)*10n**BigInt(digits)+BigInt(fraction.padEnd(digits,'0'))}
function fixed(raw:bigint,digits:number){const text=raw.toString().padStart(digits+1,'0');return text.slice(0,-digits)+'.'+text.slice(-digits)}
export function referenceCostPreview(amount:string,basis:CostBasis,factor:string){
 const cents=scaled(amount,2),f=scaled(factor,3)
 if(cents===null||f===null||f<=0n||cents>=1000000000000n)return null
 const packageCents=basis==='package'?cents:(cents*f+500n)/1000n
 const baseMicros=basis==='base'?cents*10000n:(cents*10000000n+f/2n)/f
 if(packageCents>=1000000000000n||baseMicros>=10000000000000000n)return null
 return {packageCost:fixed(packageCents,2),baseCost:fixed(baseMicros,6)}
}
export function costBaseChanged(previous:Reference,amount:string,basis:CostBasis,factor:string,hasPackage:boolean){
 const old=previous.reference_cost??previous.unit_cost
 if(old==null)return false
 const oldBasis=previous.reference_cost!=null?previous.cost_basis??'base':'base'
 const a=scaled(old,2),b=scaled(amount,2),oldFactor=scaled(previous.package_unit?previous.units_per_package:'1',3),newFactor=scaled(hasPackage?factor:'1',3)
 if(a===null||b===null||oldFactor===null||newFactor===null)return false
 // Cross multiplication compares exact costs, not rounded six-digit displays.
 const oldDenominator=oldBasis==='package'?oldFactor:1000n,newDenominator=basis==='package'?newFactor:1000n
 return a*newDenominator!==b*oldDenominator
}
