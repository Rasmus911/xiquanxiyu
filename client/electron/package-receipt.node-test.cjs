const test=require('node:test')
const assert=require('node:assert/strict')
const {receiptHtml}=require('./receipt.cjs')

test('58mm receipt renders included units and server net totals without gross recomputation',()=>{
  const html=receiptHtml({store_name:'溪泉洗浴',settlement:{number:'fixture',total_amount:'48.00'},
    visits:[{wristband_number:'001',amount:'48.00',items:[
      {name:'套票A',quantity:'1.000',unit_price:'45.00',total_amount:'45.00',covered_quantity:'0.000'},
      {name:'搓澡',quantity:'1.000',unit_price:'10.00',total_amount:'0.00',covered_quantity:'1.000'},
      {name:'水',quantity:'1.000',unit_price:'3.00',total_amount:'3.00',covered_quantity:'0.000'}]}]})
  assert.match(html,/58mm/)
  assert.match(html,/套票包含 1/)
  assert.match(html,/搓澡[^]*?¥0\.00/)
  assert.match(html,/合计<\/span><span>¥48\.00/)
  assert.doesNotMatch(html,/¥10\.00|¥58\.00/)
})
test('receipt inclusion labels do not bypass escaping or turn reprints into new sales',()=>{
  const html=receiptHtml({print_attempts:2,store_name:'<img src=x onerror=alert(1)>',
    settlement:{number:'fixture',total_amount:'14.00'},visits:[{wristband_number:'001',amount:'14.00',
      items:[{name:'备品',quantity:'3.000',unit_price:'7.00',covered_quantity:'1.000',total_amount:'14.00'}]}]})
  assert.match(html,/套票包含 1/)
  assert.match(html,/¥14\.00/)
  assert.match(html,/补打小票 第 3 次/)
  assert.doesNotMatch(html,/<img/)
})
