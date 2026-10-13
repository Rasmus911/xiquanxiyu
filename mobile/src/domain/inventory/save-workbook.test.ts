// @vitest-environment jsdom
import {expect,it,vi} from 'vitest'
const {save}=vi.hoisted(()=>({save:vi.fn(async (_body:{source_base64:string})=>({saved:true}))}))
vi.mock('@capacitor/core',()=>({Capacitor:{isNativePlatform:()=>true},registerPlugin:()=>({save})}))
import {saveWorkbook} from './save-workbook'
it('hands authenticated workbook bytes to the Android document picker without opening a browser',async()=>{
 const bytes=Uint8Array.from([80,75,3,4]);const blob=new Blob([bytes]);Object.defineProperty(blob,'arrayBuffer',{value:async()=>bytes.buffer})
 expect(await saveWorkbook(blob)).toBe(true)
 expect(save).toHaveBeenCalledWith({source_base64:'UEsDBA=='})
})
it('rejects oversized exports before entering native storage',async()=>{
 await expect(saveWorkbook({size:10*1024*1024+1} as Blob)).rejects.toThrow('10MB')
})
