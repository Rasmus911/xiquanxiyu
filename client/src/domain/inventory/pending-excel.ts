import {shallowRef} from 'vue'
import {onBusinessSessionClear} from '../../business/state'
export interface ExcelWrite {url:string;body:Record<string,unknown>;key:string}
// Retain an uncertain exact request across page navigation, never on disk.
export const pendingExcelWrite=shallowRef<ExcelWrite>()
onBusinessSessionClear(()=>{pendingExcelWrite.value=undefined})
