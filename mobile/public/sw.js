const CACHE_NAME = 'xiquan-mobile-network-only-v1'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

// 点单数据始终从云端读取，不做离线写入或接口缓存。
self.addEventListener('fetch', () => {})
