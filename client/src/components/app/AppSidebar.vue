<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Box, DocumentChecked, Goods, HomeFilled, Printer, Setting, TrendCharts, UserFilled, Avatar } from '@element-plus/icons-vue'
import { menuGroupsForPages } from '../../navigation/menu'
import { businessState } from '../../business/state'
import { useAuthStore } from '../../stores/auth'
import { useRuntimeStore } from '../../stores/runtime'

const auth = useAuthStore()
const runtime = useRuntimeStore()
const route = useRoute()
const groups = computed(() => menuGroupsForPages(businessState.value?.ui_pages || [], businessState.value?.capabilities || {}))
const icons = { home: HomeFilled, member: UserFilled, print: Printer, catalog: Goods, inventory: Box, report: TrendCharts, audit: DocumentChecked, employee: Avatar, settings: Setting }
const version = computed(() => runtime.updateState?.currentVersion || 'Web')
</script>

<template>
  <aside class="app-sidebar">
    <div class="brand">
      <div class="brand-mark">溪</div>
      <div><strong>溪泉洗浴</strong><small>经营管理系统</small></div>
    </div>
    <nav class="nav-scroll">
      <section v-for="group in groups" :key="group.label" class="nav-group">
        <div class="group-label">{{ group.label }}</div>
        <router-link v-for="item in group.items" :key="item.path" :to="item.path" class="nav-item" :class="{ active: route.path === item.path || (item.path !== '/' && route.path.startsWith(`${item.path}/`)) }">
          <el-icon><component :is="icons[item.icon]" /></el-icon><span>{{ item.label }}</span>
        </router-link>
      </section>
    </nav>
    <footer>
      <div><span class="status-dot"></span><strong>{{ auth.terminal?.name || '当前终端' }}</strong></div>
      <small>{{ auth.terminal?.code || '未登记编码' }} · v{{ version }}</small>
    </footer>
  </aside>
</template>

<style scoped>
.app-sidebar { width: 210px; flex: 0 0 210px; min-height: 100vh; display: flex; flex-direction: column; color: var(--xq-text-2); background: #fff; border-right: 1px solid var(--xq-border); }
.brand { height: 78px; display: flex; align-items: center; gap: 12px; padding: 0 20px; border-bottom: 1px solid rgba(255, 255, 255, .07); }
.brand-mark { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 7px; color: white; background: var(--xq-primary); font-size: 22px; font-weight: 700; }
.brand strong, .brand small { display: block; }
.brand strong { color: var(--xq-text-1); font-size: 17px; }
.brand small { margin-top: 3px; color: var(--xq-text-3); font-size: 12px; }
.nav-scroll { flex: 1; overflow: auto; padding: 15px 12px; }
.nav-group + .nav-group { margin-top: 18px; }
.group-label { padding: 0 10px 7px; color: var(--xq-text-3); font-size: 12px; }
.nav-item { height: 43px; display: flex; align-items: center; gap: 11px; margin: 3px 0; padding: 0 12px; border-radius: 5px; color: var(--xq-text-2); text-decoration: none; }
.nav-item:hover { color: var(--xq-primary); background: #f5f6f3; }
.nav-item.active { color: var(--xq-primary); background: var(--xq-primary-soft); font-weight: 650; box-shadow: inset 3px 0 var(--xq-primary); }
.nav-item .el-icon { font-size: 18px; }
footer { margin: 12px; padding: 12px 6px; border-top: 1px solid var(--xq-border); }
footer div { display: flex; align-items: center; gap: 7px; }
footer strong { color: var(--xq-text-2); font-size: 12px; }
footer small { display: block; margin-top: 6px; color: var(--xq-text-3); font-size: 11px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--xq-accent); }
</style>
