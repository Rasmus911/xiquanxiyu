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

test('pass checkout preserves consumption and renders face value, monetary due, mixed payment and escaped card text',()=>{
  const html=receiptHtml({settlement:{number:'pass',total_amount:'25.00',paid_amount:'10.00',
    amount_due:'10.00',pass_redemption_count:1,pass_redemption_amount:'15.00',
    member_card:{card_uid:'000315346091<script>',holder_surname:'张<img src=x>'}},
    payments:[{method:'balance',amount:'3.00'},{method:'cash',amount:'7.00'}]})
  assert.match(html,/原消费合计<\/span><span>¥25\.00/)
  assert.match(html,/次卡抵票 1 次<\/span><span>-¥15\.00/)
  assert.match(html,/货币应付<\/span><span>¥10\.00/)
  assert.match(html,/会员储值<\/span><span>¥3\.00/)
  assert.match(html,/现金<\/span><span>¥7\.00/)
  assert.match(html,/000315346091&lt;script&gt;/)
  assert.match(html,/张&lt;img src=x&gt;/)
  assert.doesNotMatch(html,/<script>|<img/)
})

test('fully redeemed ticket prints zero monetary due without inventing a cash payment',()=>{
  const html=receiptHtml({settlement:{total_amount:'15.00',amount_due:'0.00',paid_amount:'0.00',
    pass_redemption_count:1,pass_redemption_amount:'15.00'},payments:[]})
  assert.match(html,/货币应付<\/span><span>¥0\.00/)
  assert.match(html,/次卡抵票 1 次/)
  assert.doesNotMatch(html,/现金/)
})
