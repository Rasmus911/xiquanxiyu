import {Capacitor,registerPlugin} from '@capacitor/core'
const documents=registerPlugin<{save(body:{source_base64:string}):Promise<{saved:boolean;cancelled?:boolean}>}>('InventoryExcel')
export async function saveWorkbook(blob:Blob){
 if(blob.size>10*1024*1024)throw new Error('导出表格超过10MB，请缩小范围')
 if(Capacitor.isNativePlatform()){
  const bytes=new Uint8Array(await blob.arrayBuffer());let binary=''
  for(let index=0;index<bytes.length;index+=8192)binary+=String.fromCharCode(...bytes.subarray(index,index+8192))
  return (await documents.save({source_base64:btoa(binary)})).saved
 }
 const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download='溪泉库存盘点表.xlsx';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return true
}
