<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { availableMobileTabs, scopedMobileCapabilities } from '../../mobile-management'
import { permissions } from '../../business/state'
import { useSessionStore } from '../../stores/session'
const route = useRoute()
const session = useSessionStore()
const tabs = computed(() => availableMobileTabs(scopedMobileCapabilities(session.employee?.capabilities, permissions.value)))
</script>
<template><nav class="bottom-nav"><router-link v-if="tabs.includes('orders')" to="/orders" :class="{active:route.name==='orders'||route.name==='visit-order'}"><b>单</b><span>点单</span></router-link><router-link v-if="tabs.includes('reports')" to="/reports" :class="{active:route.name==='reports'}"><b>表</b><span>报表</span></router-link><router-link v-if="tabs.includes('inventory')" to="/inventory" :class="{active:route.name==='inventory'}"><b>库</b><span>库存</span></router-link><router-link v-if="tabs.includes('catalog')" to="/catalog" :class="{active:route.name==='catalog'}"><b>项</b><span>项目</span></router-link><router-link to="/profile" :class="{active:route.name==='profile'}"><b>我</b><span>我的</span></router-link></nav></template>
<style scoped>.bottom-nav{position:fixed;z-index:35;right:0;bottom:0;left:0;display:flex;justify-content:space-around;min-height:64px;padding:6px 8px;padding-bottom:max(6px,env(safe-area-inset-bottom));border-top:1px solid var(--m-border);background:rgba(255,255,255,.96);backdrop-filter:blur(14px)}a{display:grid;place-items:center;min-width:64px;color:var(--m-text-3);text-decoration:none;font-size:10px}a b{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;font-size:12px}a.active{color:var(--m-primary);font-weight:800}a.active b{color:white;background:var(--m-primary)}</style>
