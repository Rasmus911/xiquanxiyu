<script setup lang="ts">
import { computed } from 'vue'
import { memberCardKinds } from '../../domain/members/presentation'
import type { Member } from '../../types'

const props = defineProps<{ member: Member }>()
const kinds = computed(() => memberCardKinds(props.member))
</script>
<template><div class="member-badges"><el-tag v-if="kinds.includes('stored')" type="success" effect="light">储值卡</el-tag><el-tag v-if="kinds.includes('pass')" type="warning" effect="light">次卡</el-tag><span v-if="kinds.includes('none')" class="muted">普通会员</span></div></template>
<style scoped>.member-badges { display: flex; gap: 6px; }</style>
