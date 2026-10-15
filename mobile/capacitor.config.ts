import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.xiaoli.cameraassistant',
  appName: '小栗摄影助手',
  webDir: 'dist',
  // Local bundled UI; never point server.url at Streamlit. HTTP is for trusted LAN demo only.
  server: { androidScheme: 'http', cleartext: true },
  android: { backgroundColor: '#f2f7f4' },
};
export default config;
