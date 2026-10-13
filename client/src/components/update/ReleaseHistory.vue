<script setup lang="ts">
import { historyDateLabel, type ReleaseHistoryEntry } from '../../update/release-history'
defineProps<{ entries: ReleaseHistoryEntry[] }>()
</script>

<template>
  <section class="history-section">
    <h3>版本历史</h3>
    <div class="release-history" tabindex="0" role="region" aria-label="版本历史，可滚动查看">
      <article v-for="entry in entries" :key="entry.version">
        <div class="history-heading">
          <strong>{{ entry.version }}</strong>
          <span v-if="entry.source === 'backfilled'" class="backfilled">补录</span>
          <time v-if="entry.state === 'published' && entry.publishedAt" :datetime="entry.publishedAt">{{ historyDateLabel(entry) }}</time>
          <span v-else class="history-date">{{ historyDateLabel(entry) }}</span>
        </div>
        <ol><li v-for="(note, index) in entry.notes" :key="index">{{ note }}</li></ol>
      </article>
    </div>
  </section>
</template>

<style scoped>
.history-section { margin-top: 18px; min-width: 0; }
h3 { margin: 0 0 10px; color: #172942; font-size: 15px; }
.release-history { max-height: min(40vh, 360px); overflow-y: auto; overscroll-behavior: contain; padding: 0 8px 0 0; color: #4b5d73; overflow-wrap: anywhere; }
.release-history:focus-visible { outline: 2px solid var(--xq-primary); outline-offset: 2px; }
article { padding: 12px 0; border-top: 1px solid #e8edf4; }
.history-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
time, .history-date { margin-left: auto; color: #77859a; font-size: 12px; }
.backfilled { color: #77859a; font-size: 12px; }
ol { margin: 8px 0 0; padding-left: 24px; }
li + li { margin-top: 5px; }
</style>
