<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sessionEpoch } from './business/state'
import UpdateCenter from './components/update/UpdateCenter.vue'
import WebUpdateBar from './components/update/WebUpdateBar.vue'
const route = useRoute(); const router = useRouter()
const cleared = () => { if (route.path !== '/login') void router.replace('/login') }
onMounted(() => window.addEventListener('xiquan:session-cleared', cleared))
onBeforeUnmount(() => window.removeEventListener('xiquan:session-cleared', cleared))
</script>

<template>
  <router-view :key="route.path === '/login' ? 'login' : sessionEpoch" />
  <UpdateCenter />
  <WebUpdateBar />
</template>

