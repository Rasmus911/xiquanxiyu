// @vitest-environment jsdom
import {createApp,h} from 'vue'
import {expect,it} from 'vitest'
import MobileTrendChart from './MobileTrendChart.vue'
it('shows refunded negative inflow below the zero line without negative CSS height',()=>{
  const root=document.createElement('div')
  const app=createApp({render:()=>h(MobileTrendChart,{rows:[{date:'2026-10-06',cash_inflow:'-10.00'},{date:'2026-10-07',cash_inflow:'60.00'}] as any})})
  app.mount(root)
  try {
    const bars=root.querySelectorAll('.bar-track i')
    expect(bars[0]!.getAttribute('style')).toContain('height: 14.285')
    expect(bars[0]!.classList.contains('negative')).toBe(true)
    expect(root.textContent).toContain('¥-10')
    expect(bars[1]!.getAttribute('style')).toContain('height: 85.714')
  } finally {app.unmount()}
})
