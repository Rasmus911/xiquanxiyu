import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.xiquan.mobileordering',
  appName: '溪泉移动点单',
  webDir: 'dist',
  server: {
    androidScheme: 'https',
  },
}

export default config
