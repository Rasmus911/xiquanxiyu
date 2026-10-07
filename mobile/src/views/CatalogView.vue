<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { canAccess, useBusinessGuard } from '../business/state'
import { dataOf, errorMessage, http } from '../api'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import MobileState from '../components/common/MobileState.vue'
import { useBusinessStore } from '../stores/business'
import type { MobileCatalogItem, StockUsage } from '../types'
const guard=useBusinessGuard();const business=useBusinessStore()
const allowed=computed(()=>canAccess('catalog:read')&&canAccess('catalog:write'))
const catalog=ref<MobileCatalogItem[]>([]);const usage=ref<StockUsage[]>([]);const inactive=ref(false);const search=ref('');const message=ref('');const saving=ref(false);const loading=ref(false)
const editing=ref<MobileCatalogItem|null>(null);const editorOpen=ref(false)
const form=reactive({kind:'service',name:'',category:'',price:'0.00',mobile_scope:'both'})
const rows=computed(()=>catalog.value.filter(row=>(inactive.value?row.is_active===false:row.is_active!==false)&&(!search.value.trim()||row.name.includes(search.value.trim()))))
const page=ref(1)
const paged=computed(()=>rows.value.slice((page.value-1)*10,page.value*10))
watch([search,inactive],()=>{page.value=1})
watch(()=>rows.value.length,count=>{page.value=Math.min(page.value,Math.max(1,Math.ceil(count/10)))})
const editable=(row:MobileCatalogItem)=>allowed.value&&row.can_edit===true
const valid=computed(()=>form.name.trim()&&/^\d+(\.\d{1,2})?$/.test(form.price)&&Number.isFinite(Number(form.price)))
async function load(){if(!allowed.value)return;const current=guard('load');loading.value=true;try{
  const [items,stats]=await Promise.all([http.get('/catalog',{params:inactive.value?{active:'false'}:{}}),http.get('/inventory/usage')]);if(!current())return
  catalog.value=dataOf(items);usage.value=dataOf(stats)
}catch(cause){if(current())message.value=errorMessage(cause)}finally{if(current())loading.value=false}}
function open(row:MobileCatalogItem|null){if(!allowed.value||saving.value||(row&&!editable(row)))return;editing.value=row;Object.assign(form,row?{kind:row.kind,name:row.name,category:row.category,price:row.price,mobile_scope:row.mobile_scope||'both'}:{kind:'service',name:'',category:'',price:'0.00',mobile_scope:'both'});editorOpen.value=true}
async function write(body:Record<string,unknown>,row:MobileCatalogItem|null){
  if(!allowed.value||saving.value||(row&&!editable(row)))return false
  const current=guard('write');saving.value=true
  try{dataOf(await http.request({method:row?'patch':'post',url:row?`/catalog/${row.id}`:'/catalog',data:body}));if(!current())return false;message.value='项目已保存';return true}
  catch(cause){if(current())message.value=errorMessage(cause);return false}finally{if(current())saving.value=false}
}
async function refresh(){await Promise.all([load(),business.refreshBootstrap(true).catch(cause=>{if(allowed.value)message.value=errorMessage(cause)})])}
async function save(){if(!valid.value)return;const row=editing.value;const body={name:form.name.trim(),category:form.category.trim(),price:form.price,mobile_scope:form.mobile_scope,...(!row?{kind:form.kind,stock_tracked:false}:{})};if(await write(body,row)){editorOpen.value=false;await refresh()}}
async function activation(row:MobileCatalogItem){if(!editable(row))return;if(!window.confirm(`${row.is_active===false?'重新启用':'停用'}${row.name}？历史账单保留。`))return;if(await write({is_active:row.is_active===false},row))await refresh()}
function back(event:Event){if(editorOpen.value){event.preventDefault();if(!saving.value)editorOpen.value=false}}
function changed(event:Event){if((event as CustomEvent<string[]>).detail.some(domain=>['orders','inventory'].includes(domain)))void load()}
onMounted(()=>{document.addEventListener('xiquan:back-request',back);window.addEventListener('xiquan:domains-refreshed',changed);void load()})
onBeforeUnmount(()=>{document.removeEventListener('xiquan:back-request',back);window.removeEventListener('xiquan:domains-refreshed',changed)})
</script>
<template><div><MobileTopbar title="项目服务" subtitle="服务与商品名称、对客售价"/><main class="mobile-page">
  <MobileState v-if="!allowed" kind="error" title="无权访问项目管理"/>
  <template v-else><div v-if="message" class="notice">{{message}}</div><button :disabled="saving" data-testid="catalog-create" @click="open(null)">新增服务/商品</button>
    <label><input v-model="inactive" type="checkbox" @change="load"/> 已停用</label><input v-model="search" class="mobile-input" placeholder="搜索项目"/>
    <MobileState v-if="loading&&!rows.length" kind="loading" title="正在读取项目"/>
    <section class="mobile-card catalog-list" data-testid="catalog-list"><div class="list-header"><strong>项目列表</strong><nav class="pagination" aria-label="项目分页"><button :disabled="page===1" @click="page--">上一页</button><span>{{page}} / {{Math.max(1,Math.ceil(rows.length/10))}} · 共{{rows.length}}项</span><button :disabled="page*10>=rows.length" @click="page++">下一页</button></nav></div>
    <section v-for="row in paged" :key="row.id" class="catalog-row"><strong>{{row.name}}</strong><p>{{row.category}} · ¥{{row.price}}</p><p v-for="stat in usage.filter(item=>item.catalog_item_id===row.id&&item.is_most_used)" :key="stat.stock_item_id">最常使用（含并列）：{{stat.stock_name}} · {{stat.usage_count}} 次</p>
      <template v-if="editable(row)"><button :data-testid="`catalog-edit-${row.id}`" :disabled="saving" @click="open(row)">编辑名称/售价</button><button :disabled="saving" @click="activation(row)">{{row.is_active===false?'重新启用':'停用'}}</button></template><span v-else>只读</span>
    </section>
    </section>
  </template></main><div v-if="allowed&&editorOpen" class="sheet-mask"><section class="sheet"><h3>{{editing?'编辑项目':'新增项目'}}</h3><label v-if="!editing">类型<select v-model="form.kind" :disabled="saving"><option value="service">服务</option><option value="product">商品</option></select></label>
    <label>名称<input v-model="form.name" name="name" :disabled="saving"/></label><label>类别<input v-model="form.category" name="category" :disabled="saving"/></label><label>对客售价<input v-model="form.price" name="price" inputmode="decimal" :disabled="saving"/></label><label>手机销售范围<select v-model="form.mobile_scope" :disabled="saving"><option value="both">搓澡及三楼</option><option value="scrub">搓澡</option><option value="rest">三楼</option><option value="frontdesk">前台</option></select></label><p>未结账账单沿用服务器改价规则；已结算快照保留。</p><div v-if="message" class="notice">{{message}}</div><button :disabled="saving||!valid" data-testid="catalog-save" @click="save">保存</button><button :disabled="saving" @click="editorOpen=false">取消</button>
  </section></div></div></template>
<style scoped>.catalog-list{margin-top:12px;padding:12px}.list-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}.pagination{display:flex;align-items:center;justify-content:flex-end;margin-left:auto;gap:4px;font-size:12px}.pagination button{margin:0;padding:6px}.catalog-row{padding:14px;margin-top:12px;border-top:1px solid var(--m-border)}.catalog-row p{font-size:12px;color:var(--m-text-3)}button{min-height:42px;margin:6px;padding:8px;border:1px solid var(--m-border);border-radius:7px;background:white;color:var(--m-primary)}.sheet-mask{position:fixed;inset:0;z-index:70;background:#10203577;display:flex;align-items:end}.sheet{width:100%;max-height:85vh;overflow:auto;padding:18px;background:white;border-radius:22px 22px 0 0}.sheet label{display:grid;gap:5px;margin:10px 0}.sheet input,.sheet select{min-height:44px;padding:8px}</style>
