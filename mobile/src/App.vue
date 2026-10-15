<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Camera } from '@capacitor/camera';
import { Capacitor } from '@capacitor/core';
import mascot from '../../assets/camera-red-panda.png';
import { normalizeBaseUrl, safeSourceUrl } from './connection.mjs';
import { readAnalysis } from './analysis-stream.mjs';
import type { Analysis, CameraLensProfile, CameraProfile, PhoneProfile } from './types';
import DevicePicker from './components/DevicePicker.vue';
import CompositionView from './components/CompositionView.vue';
import { compatibleLenses, deviceSelection, linkedCameraSettings, mountNames, sensorLabel } from './device-selection.mjs';

const page = ref<'shoot' | 'result' | 'history' | 'connect'>('shoot');
const webHosted = ref(false);
const inviteRequired = ref(false);
const accessCode = ref('');
const archiveKey = 'xiaoli-advice-history-v1';
type SavedAdvice = { id: string; date: string; intent: string; analysis: Analysis };
const history = ref<SavedAdvice[]>([]);
try {
  const data = JSON.parse(localStorage.getItem(archiveKey) || '[]');
  if (Array.isArray(data)) history.value = data.filter(v => typeof v?.intent === 'string' && v?.analysis?.result?.recommendation && v?.analysis?.result?.scene).slice(0, 10);
} catch { /* local storage may be unavailable */ }
const exportMessage = ref('');
const mainContent = ref<HTMLElement>();
function scrollToTop() { void nextTick(() => mainContent.value?.scrollTo({ top: 0 })); }
watch(page, scrollToTop);
const storedKey = 'xiaoli-mobile-connection-v1';
let saved: { baseUrl?: string; token?: string } = {};
try { saved = JSON.parse(localStorage.getItem(storedKey) || '{}'); } catch { /* no saved config */ }
const baseUrl = ref(saved.baseUrl || '');
const token = ref(saved.token || '');
const connected = ref(false);
const mode = ref<'cloud' | 'demo'>('demo');
const maxImageMb = ref(15);
const busy = ref(false);
const elapsed = ref(0);
const statusStartedAt = ref(0);
const statusElapsed = computed(() => Math.max(0, elapsed.value - statusStartedAt.value));
const progressMessage = ref('正在上传照片…');
const progressLog = ref<{ message: string; seconds: number }[]>([]);
const received = ref<Record<string, number>>({});
const receivedChars = computed(() => Object.values(received.value).reduce((sum, n) => sum + n, 0));
const partialScene = ref<Analysis['result']['scene'] | null>(null);
const partialParameters = ref<Analysis['result']['recommendation'] | null>(null);
const progressStage = ref(0);
const connecting = ref(false);
const error = ref('');
const connectionMessage = ref('');
const photo = ref<File | null>(null);
const preview = ref('');
const provenance = ref('original_upload');
const cameraInput = ref<HTMLInputElement>();
const intent = ref('');
const motion = ref('不确定');
const tripod = ref(false);
const consent = ref(false);
const deviceType = ref('phone');
const cameraId = ref('generic_unknown');
const phoneId = ref('generic_phone');
const phoneManual = ref(false);
const cameraManual = ref(false);
const phoneModelName = ref('');
const cameraModelName = ref('');
const phoneMode = ref('auto');
const lensId = ref('main');
const proConfirmed = ref(false);
const focalLength = ref<number | undefined>();
const maxAperture = ref<number | undefined>();
const cameraLensId = ref('');
const cameraFormat = ref('不清楚');
const cameraLenses = ref<CameraLensProfile[]>([]);
const cameras = ref<CameraProfile[]>([{ profile_id: 'generic_unknown', display_name: '未知相机' }]);
const phones = ref<PhoneProfile[]>([{ profile_id: 'generic_phone', display_name: '未知手机', modes: ['auto'], lenses: [{ lens_id: 'main', name: '主摄' }], notes: [] }]);
const selectedPhone = computed(() => phones.value.find(p => p.profile_id === (phoneManual.value ? 'generic_phone' : phoneId.value)) || phones.value[0]);
const selectedPhoneLens = computed(() => selectedPhone.value?.lenses.find(l => l.lens_id === lensId.value));
const availablePhoneModes = computed(() => selectedPhone.value?.modes.filter(m => (selectedPhoneLens.value?.modes || ['auto']).includes(m)) || ['auto']);
const selectedCamera = computed(() => cameras.value.find(p => p.profile_id === (cameraManual.value ? 'generic_unknown' : cameraId.value)));
const knownCamera = computed(() => selectedCamera.value && !selectedCamera.value.profile_id.startsWith('generic_') && selectedCamera.value.capability_level !== 'catalog');
const availableCameraLenses = computed(() => compatibleLenses(selectedCamera.value, cameraLenses.value));
const selectedCameraLens = computed(() => availableCameraLenses.value.find(l => l.lens_id === cameraLensId.value));
const linkedSettings = computed(() => selectedCamera.value && selectedCameraLens.value ? linkedCameraSettings(selectedCamera.value, selectedCameraLens.value, focalLength.value) : null);
const selectedMountName = computed(() => (mountNames as Record<string, string>)[selectedCamera.value?.mount || ''] || '卡口未确认');
const modeNames: Record<string, string> = { auto: '照片 / 自动', portrait: '人像', night: '夜间', pro: '专业 / Pro' };
const analysis = ref<Analysis | null>(null);
const result = computed(() => analysis.value?.result);
const lightingText = computed(() => {
  const value = result.value?.scene.lighting || '';
  return ({ 'available light': '现场环境光', natural: '自然光', daylight: '日光',
    'soft light': '柔和光线', 'window light': '窗边光', backlight: '逆光',
    continuous_artificial: '连续人造光', mixed: '混合光' } as Record<string, string>)[value] || value;
});
const resultIntent = ref('');
const chips = ['自然人像，背景柔和', '窗边静物，干净通透', '夜景，保留灯光氛围'];
const statusText = computed(() => !connected.value ? '未连接' : mode.value === 'demo' ? '演示规则' : '云模型');
let activeController: AbortController | null = null;

watch([baseUrl, token], () => { connected.value = false; consent.value = false; connectionMessage.value = ''; });
watch([phoneId, phoneManual, phoneModelName], () => { phoneMode.value = 'auto'; lensId.value = 'main'; proConfirmed.value = false; });
watch(phoneMode, () => { proConfirmed.value = false; });
watch(lensId, () => { phoneMode.value = 'auto'; proConfirmed.value = false; });
watch([cameraId, cameraManual, cameraModelName], () => { cameraLensId.value = ''; focalLength.value = undefined; maxAperture.value = undefined; cameraFormat.value = selectedCamera.value?.sensor_format || '不清楚'; });
watch(cameraLensId, () => { focalLength.value = selectedCameraLens.value?.focal_min_mm; maxAperture.value = undefined; });
watch([deviceType, cameraId, phoneId, cameraManual, phoneManual, cameraModelName, phoneModelName, phoneMode, lensId, proConfirmed, focalLength, maxAperture, cameraLensId, cameraFormat], () => { analysis.value = null; });

async function api(path: string, options: RequestInit = {}, onEvent?: (event: any) => void) {
  const root = webHosted.value ? window.location.origin : normalizeBaseUrl(baseUrl.value);
  const headers = new Headers(options.headers);
  if (webHosted.value) headers.set('X-Xiaoli-Client', 'web');
  else if (path !== '/health') headers.set('Authorization', `Bearer ${token.value.trim()}`);
  const response = await fetch(root + path, { ...options, headers, credentials: webHosted.value ? 'same-origin' : 'omit' });
  if (response.ok && onEvent) return readAnalysis(response, onEvent);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fallback = response.status === 401 ? (webHosted.value ? '体验会话已过期，请重新输入体验码。' : '连接令牌不正确。') : `服务暂不可用（${response.status}），请稍后重试。`;
    if (webHosted.value && response.status === 401) { connected.value = false; consent.value = false; page.value = 'connect'; }
    throw new Error(typeof data.detail === 'string' ? data.detail : fallback);
  }
  return data;
}

async function connect() {
  if (connecting.value || busy.value) return;
  error.value = ''; connectionMessage.value = ''; connecting.value = true; connected.value = false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    if (!webHosted.value && token.value.trim().length < 24) throw new Error('请输入电脑端生成的连接令牌，不是云模型 API Key。');
    if (webHosted.value) await api('/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ access_code: accessCode.value }), signal: controller.signal });
    const health = await api('/health', { signal: controller.signal });
    if (health.service !== 'xiaoli-mobile-api' || health.api_version !== '1') throw new Error('这不是小栗手机服务，请检查端口（默认 8000）。');
    const devices = await api('/api/v1/devices', { signal: controller.signal });
    if (!devices.catalog_summary?.equipment_linkage || !Array.isArray(devices.camera_lenses)) throw new Error('电脑端尚未支持镜头联动，请更新项目并重启手机服务。');
    cameras.value = devices.cameras; phones.value = devices.phones;
    cameraLenses.value = devices.camera_lenses;
    if (!availableCameraLenses.value.some(l => l.lens_id === cameraLensId.value)) cameraLensId.value = '';
    if (!cameras.value.some(p => p.profile_id === cameraId.value)) cameraId.value = 'generic_unknown';
    if (!phones.value.some(p => p.profile_id === phoneId.value)) phoneId.value = 'generic_phone';
    mode.value = health.analysis_mode; maxImageMb.value = health.max_image_mb;
    connected.value = true;
    if (!webHosted.value) localStorage.setItem(storedKey, JSON.stringify({ baseUrl: normalizeBaseUrl(baseUrl.value), token: token.value.trim() }));
    accessCode.value = '';
    connectionMessage.value = mode.value === 'demo' ? '连接成功。当前为规则演示，不是真实多模态识别。' : '连接成功。照片副本将发送给电脑端配置的云模型。';
  } catch (e) {
    error.value = readableError(e, '连接失败：确认同一 Wi-Fi、电脑服务已启动，且防火墙允许 8000 端口。');
  } finally { clearTimeout(timer); connecting.value = false; }
}

onMounted(async () => {
  if (Capacitor.isNativePlatform()) return;
  try {
    const response = await fetch('/web-config', { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return;
    const config = await response.json();
    if (config.web_client !== true) return;
    webHosted.value = true; inviteRequired.value = config.invite_required;
    if (!inviteRequired.value) { await connect(); return; }
    try {
      const [health, devices] = await Promise.all([api('/health'), api('/api/v1/devices')]);
      cameras.value = devices.cameras; phones.value = devices.phones; cameraLenses.value = devices.camera_lenses;
      mode.value = health.analysis_mode; maxImageMb.value = health.max_image_mb; connected.value = true;
    } catch { error.value = ''; page.value = 'connect'; }
  } catch { /* A standalone Android/LAN client has no web gateway. */ }
});

function readableError(e: unknown, fallback: string): string {
  if (e instanceof Error && e.name === 'AbortError') return '请求超时，检查电脑服务和网络后重试。';
  if (e instanceof TypeError) return fallback;
  return e instanceof Error ? e.message : fallback;
}

function setPhoto(file: File, source: string) {
  if (busy.value) return;
  error.value = '';
  if (!/\.(jpe?g|png)$/i.test(file.name) || !['image/jpeg', 'image/png'].includes(file.type)) {
    error.value = '请选择 JPEG / PNG。HEIC、RAW 请先在系统相册中导出。'; return;
  }
  if (file.size > maxImageMb.value * 1024 * 1024) {
    error.value = `照片超过 ${maxImageMb.value} MB，请换一张。`; return;
  }
  if (preview.value) URL.revokeObjectURL(preview.value);
  photo.value = file; preview.value = URL.createObjectURL(file); provenance.value = source;
  consent.value = false; analysis.value = null;
}
function fileChosen(event: Event, source: string) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) setPhoto(file, source);
  input.value = '';
}
function photoDropped(event: DragEvent) {
  if (busy.value) return;
  const file = event.dataTransfer?.files[0];
  if (file) setPhoto(file, 'original_upload');
}
async function takePhoto() {
  if (!Capacitor.isNativePlatform()) { cameraInput.value?.click(); return; }
  error.value = '';
  try {
    const captured = await Camera.takePhoto({ quality: 100, includeMetadata: true, saveToGallery: false });
    if (!captured.webPath) throw new Error('未取得拍照文件，请重试或从相册选择。');
    const response = await fetch(captured.webPath);
    if (!response.ok) throw new Error('无法读取拍照文件，请从相册选择照片。');
    const blob = await response.blob();
    setPhoto(new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }), 'device_camera');
  } catch (e) {
    const code = (e as { code?: string }).code;
    if (code === 'OS-PLUG-CAMR-0006' || code === 'OS-PLUG-CAMR-0007') return;
    error.value = readableError(e, '未完成拍照。请检查系统相机权限，或改用相册。');
  }
}

async function analyze() {
  if (busy.value) return;
  error.value = '';
  if (!connected.value) { page.value = 'connect'; error.value = webHosted.value ? '请输入体验码，开启本次拍摄。' : '先连接电脑端手机服务。'; return; }
  if (!photo.value) { error.value = '先拍照或选择一张现场照片。'; return; }
  if (intent.value.trim().length < 2) { error.value = '写一下想拍的主体和效果，至少两个字。'; return; }
  let selection;
  try {
    selection = deviceType.value === 'phone'
      ? deviceSelection('phone', phoneId.value, phoneManual.value, phoneModelName.value)
      : deviceSelection('camera', cameraId.value, cameraManual.value, cameraModelName.value);
  } catch (e) { error.value = readableError(e, '请核对设备型号。'); return; }
  if (!consent.value) { error.value = '请先勾选照片上传与分析说明。'; return; }
  busy.value = true;
  analysis.value = null; partialScene.value = null; partialParameters.value = null;
  received.value = {}; progressLog.value = []; progressStage.value = 0;
  progressMessage.value = '正在上传照片…'; elapsed.value = 0; statusStartedAt.value = 0;
  const started = performance.now();
  const clock = setInterval(() => { elapsed.value = (performance.now() - started) / 1000; }, 500);
  const submittedIntent = intent.value.trim();
  const controller = new AbortController(); activeController = controller;
  const timer = setTimeout(() => controller.abort(), 540000);
  try {
    const form = new FormData();
    form.append('file', photo.value); form.append('consent', 'true'); form.append('image_provenance', provenance.value);
    form.append('expected_analysis_mode', mode.value);
    form.append('stream_events', 'true');
    form.append('user_request', JSON.stringify({
      intent: intent.value.trim(), device_type: deviceType.value, subject_motion: motion.value,
      handheld: !tripod.value, tripod: tripod.value,
      camera_profile_id: deviceType.value === 'camera' ? selection.profile_id : 'generic_unknown',
      camera_lens_id: deviceType.value === 'camera' && !cameraManual.value ? cameraLensId.value : '',
      device_model_name: selection.device_model_name,
      camera_format: deviceType.value === 'phone' ? '不清楚' : knownCamera.value ? selectedCamera.value!.sensor_format : cameraFormat.value,
      focal_length_mm: deviceType.value === 'camera' ? linkedSettings.value?.focal_length_mm || focalLength.value || null : null,
      max_aperture: deviceType.value === 'camera' ? linkedSettings.value?.max_aperture || maxAperture.value || null : null,
      phone_profile_id: deviceType.value === 'phone' ? selection.profile_id : 'generic_phone',
      phone_capture_mode: phoneManual.value ? 'auto' : phoneMode.value,
      phone_lens_id: phoneManual.value ? 'main' : lensId.value,
      phone_pro_controls_confirmed: !phoneManual.value && proConfirmed.value,
    }));
    analysis.value = await api('/api/v1/analyze', { method: 'POST', body: form, signal: controller.signal }, event => {
      if (event.type === 'progress' && typeof event.message === 'string') {
        if (progressMessage.value !== event.message) statusStartedAt.value = (performance.now() - started) / 1000;
        progressMessage.value = event.message;
        progressLog.value.push({ message: event.message, seconds: event.elapsed_seconds || 0 });
        const stage = /生成|校验/.test(event.message) ? 3 : /查阅|检索/.test(event.message) ? 2 : /识别|定位/.test(event.message) ? 1 : 0;
        progressStage.value = Math.max(progressStage.value, stage);
      } else if (event.type === 'activity' && typeof event.request_id === 'string' && Number.isFinite(event.chars)) {
        received.value[event.request_id] = event.chars;
      } else if (event.type === 'partial') {
        if (event.kind === 'scene') partialScene.value = event.value;
        if (event.kind === 'parameters') {
          partialParameters.value = event.value;
          progressMessage.value = '拍摄参数已校验，正在整理完整方案…';
          statusStartedAt.value = (performance.now() - started) / 1000;
        }
      } else if (event.type === 'result') { progressStage.value = 4; }
    });
    resultIntent.value = submittedIntent;
    try {
      const item = { id: analysis.value!.request_id, date: new Date().toISOString(), intent: submittedIntent, analysis: analysis.value! };
      history.value = [item, ...history.value.filter(v => v.id !== item.id)].slice(0, 10);
      localStorage.setItem(archiveKey, JSON.stringify(history.value));
    } catch { /* Analysis still succeeds when local storage is full. */ }
    page.value = 'result'; scrollToTop();
  } catch (e) {
    error.value = readableError(e, '分析未完成：检查电脑服务及网络。不会自动重复提交照片。');
    if (error.value.includes('分析方式已改变')) { connected.value = false; consent.value = false; page.value = 'connect'; }
  }
  finally { clearTimeout(timer); clearInterval(clock); elapsed.value = (performance.now() - started) / 1000; busy.value = false; activeController = null; }
}
async function clearConnection() {
  if (webHosted.value) {
    try { await api('/session', { method: 'DELETE' }); connected.value = false; consent.value = false; connectionMessage.value = '已退出本次体验。'; } catch (e) { error.value = readableError(e, '退出失败，请重试。'); }
    return;
  }
  localStorage.removeItem(storedKey); baseUrl.value = ''; token.value = ''; connected.value = false;
  connectionMessage.value = '已清除本机连接信息。';
}
function openHistory(item: SavedAdvice) {
  if (busy.value) return;
  if (preview.value) URL.revokeObjectURL(preview.value);
  preview.value = ''; photo.value = null; consent.value = false;
  intent.value = item.intent; resultIntent.value = item.intent; analysis.value = item.analysis; page.value = 'result';
}
function clearHistory() { history.value = []; localStorage.removeItem(archiveKey); }
function exportAdvice() {
  if (!result.value) return;
  const r = result.value;
  const text = [`小栗摄影助手 · 拍摄方案`, resultIntent.value, r.camera_profile.display_name, r.scene.scene_label || r.scene.scene_type,
    `模式：${r.recommendation.shooting_mode}`, `光圈：${r.recommendation.aperture}`, `快门：${r.recommendation.shutter_speed}`, `ISO：${r.recommendation.iso}`,
    ...r.recommendation.reasons, ...r.recommendation.adjustments,
    ...(r.composition?.proposals || []).flatMap(p => [p.goal, ...p.actions]),
    ...r.recommendation.risks, `分析方式：${analysis.value?.analysis_mode === 'demo' ? '规则演示' : '云模型'}；参数是试拍起点。`].join('\n');
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = '小栗拍摄方案.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); exportMessage.value = '拍摄方案已导出。';
}
function navigate(value: 'shoot' | 'result' | 'history' | 'connect') { page.value = value; error.value = ''; exportMessage.value = ''; scrollToTop(); }
onBeforeUnmount(() => { if (preview.value) URL.revokeObjectURL(preview.value); activeController?.abort(); });
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand"><span class="brand-mark" aria-hidden="true">◎</span><div><strong>小栗摄影助手</strong><span>看见值得拍的日常</span></div></div>
      <button class="status" :class="{ online: connected }" @click="navigate('connect')"><i aria-hidden="true"></i>{{ statusText }}</button>
    </header>
    <main ref="mainContent">
      <div v-if="error" class="notice error" role="alert">{{ error }}</div>
      <section v-if="page === 'shoot'" aria-labelledby="shoot-title">
        <div class="intro"><h1 id="shoot-title">把眼前，拍成心里的画面。</h1><p>从一张现场照片开始，找到主体、留白与光的关系。</p></div>
        <div class="shoot-layout"><div class="shoot-visual"><div class="viewfinder" :class="{ 'has-photo': photo }" @dragover.prevent @drop.prevent="photoDropped">
          <img v-if="photo" :src="preview" alt="已选择的现场照片" class="photo-preview" />
          <div v-else class="empty-photo"><img :src="mascot" alt="抱着相机的小熊猫小栗" /><strong>点击这里，选择现场照片</strong><span>也可以把 JPEG / PNG 拖到这里</span></div>
          <span class="frame-corner top-left"></span><span class="frame-corner top-right"></span><span class="frame-corner bottom-left"></span><span class="frame-corner bottom-right"></span>
          <input class="photo-select-input" type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" aria-label="点击取景框选择现场照片" aria-describedby="photo-help" :disabled="busy" @change="fileChosen($event, 'original_upload')" />
        </div>
        <div class="photo-actions"><button class="camera-button" type="button" :disabled="busy" @click="takePhoto">◎ 拍一张</button><label class="secondary file-action" :class="{ disabled: busy }"><span>{{ photo ? '换一张照片' : '从相册选择' }}</span><input class="photo-select-input" type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" aria-label="从相册选择现场照片" aria-describedby="photo-help" :disabled="busy" @change="fileChosen($event, 'original_upload')" /></label></div>
        <input ref="cameraInput" class="file-input" type="file" accept="image/jpeg,image/png" capture="environment" aria-label="使用系统相机" @change="fileChosen($event, 'device_camera')" />
        <p id="photo-help" class="photo-caption" aria-live="polite">{{ photo ? `已选择：${photo.name} · ${(photo.size / 1024 / 1024).toFixed(1)} MB` : `JPEG / PNG，最大 ${maxImageMb} MB。选图后会在上方预览。` }}</p>
        </div><form class="shoot-form" @submit.prevent="analyze">
          <fieldset :disabled="busy">
            <label class="field-label" for="intent">想拍出什么感觉？</label>
            <textarea id="intent" v-model="intent" rows="3" maxlength="500" placeholder="比如：傍晚给朋友拍人像，想要温柔的光线和虚化背景"></textarea>
            <div class="prompt-chips"><button v-for="chip in chips" :key="chip" type="button" @click="intent = chip">{{ chip }}</button></div>
            <details class="equipment-drawer"><summary>拍摄设备与现场设置<span>{{ deviceType === 'phone' ? '手机' : '相机' }} · 点击调整</span></summary><div class="section-heading"><h2>用什么拍</h2><div class="segmented"><button type="button" :class="{ selected: deviceType === 'phone' }" :aria-pressed="deviceType === 'phone'" @click="deviceType = 'phone'">手机</button><button type="button" :class="{ selected: deviceType === 'camera' }" :aria-pressed="deviceType === 'camera'" @click="deviceType = 'camera'">相机</button></div></div>
            <template v-if="deviceType === 'phone'">
              <DevicePicker :profiles="phones" v-model="phoneId" v-model:manual="phoneManual" v-model:manual-model-name="phoneModelName" :catalog-loaded="connected" device-label="手机" generic-id="generic_phone" input-id="phone" />
              <div class="two-fields"><div><label for="lens">当前后置镜头</label><select id="lens" v-model="lensId"><option v-for="l in selectedPhone?.lenses" :key="l.lens_id" :value="l.lens_id">{{ l.name }}</option></select></div><div><label for="phone-mode">拍摄模式</label><select id="phone-mode" v-model="phoneMode"><option v-for="m in availablePhoneModes" :key="m" :value="m">{{ modeNames[m] || m }}</option></select></div></div>
              <div class="equipment-summary" aria-live="polite"><strong>{{ selectedPhoneLens?.name }}</strong><span>{{ selectedPhoneLens?.equivalent_focal_length_mm ? `约 ${selectedPhoneLens.equivalent_focal_length_mm}mm 等效` : '等效焦距待核验' }}</span><span>{{ selectedPhoneLens?.aperture ? `f/${selectedPhoneLens.aperture}${selectedPhoneLens.aperture_max ? `–f/${selectedPhoneLens.aperture_max}` : ''}` : '光圈待核验' }} · {{ selectedPhoneLens?.aperture_control === 'variable' ? '可变物理光圈，按本机界面核对' : selectedPhoneLens?.aperture_control === 'fixed' ? '固定物理光圈，不可手调' : '物理光圈控制待核验' }}</span></div>
              <p class="helper">这里只列已录入的镜头与模式组合；未列出不代表本机不支持。手机显示等效焦距，不套用相机的半画幅或可换镜头。</p>
              <label v-if="phoneMode === 'pro' && selectedPhone?.pro_controls?.length" class="check-row"><input type="checkbox" v-model="proConfirmed" />我已在手机相机中确认专业模式可调参数</label>
              <p v-else-if="phoneMode === 'pro'" class="helper">专业模式已列入型号资料，具体控件尚未录入；暂不输出手动曝光数值。</p>
            </template>
            <template v-else>
              <DevicePicker :profiles="cameras" v-model="cameraId" v-model:manual="cameraManual" v-model:manual-model-name="cameraModelName" :catalog-loaded="connected" device-label="相机" generic-id="generic_unknown" input-id="camera" />
              <div v-if="selectedCamera?.capability_level === 'catalog'" class="equipment-summary" role="status"><strong>基础目录已匹配，硬件能力待核验</strong><span v-if="selectedCamera.catalog_sensor_label">来源传感器记录：{{ selectedCamera.catalog_sensor_label }}（仅供复核）</span><span>不自动套用 ISO、快门、防抖或镜头兼容；下面的画幅可按实际设备手填。</span><a v-for="source in selectedCamera.catalog_sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">资料来源 · {{ source.license }}</a></div>
              <div v-if="knownCamera" class="equipment-summary"><strong>{{ sensorLabel(selectedCamera?.sensor_format) }} · 自动匹配</strong><span>{{ selectedMountName }} 原生卡口</span><span v-if="selectedCamera?.capability_level === 'basic'">本次已核验画幅与卡口；曝光边界仍待补充。</span></div>
              <template v-else><label for="camera-format" class="field-label">相机画幅（可选）</label><select id="camera-format" v-model="cameraFormat"><option>不清楚</option><option>全画幅</option><option value="APS-C">APS-C（半画幅）</option><option>M4/3</option></select></template>
              <label for="camera-lens" class="field-label lens-label">实际安装的镜头</label><select id="camera-lens" v-model="cameraLensId"><option value="">未选择 / 自定义镜头</option><option v-for="lens in availableCameraLenses" :key="lens.lens_id" :value="lens.lens_id">{{ lens.display_name }}</option></select>
              <p class="helper">{{ selectedCamera?.capability_level === 'catalog' ? '此型号的卡口和镜头兼容尚未核验，不自动匹配镜头；可填写实际镜头资料。' : '只列原生卡口、原生画幅兼容镜头。请选实际安装的镜头，不默认套头；转接和裁切模式暂未适配。' }}</p>
              <template v-if="selectedCameraLens && linkedSettings">
                <label for="lens-focal" class="field-label">当前实际焦距 · {{ linkedSettings.focal_length_mm }}mm</label>
                <input v-if="selectedCameraLens.focal_min_mm !== selectedCameraLens.focal_max_mm" id="lens-focal" type="range" v-model.number="focalLength" :min="selectedCameraLens.focal_min_mm" :max="selectedCameraLens.focal_max_mm" step="1" />
                <div class="focal-range"><span>{{ selectedCameraLens.focal_min_mm }}mm</span><span>{{ selectedCameraLens.focal_max_mm }}mm</span></div>
                <div class="equipment-summary" aria-live="polite"><strong>约 {{ linkedSettings.equivalent_focal_length_mm }}mm 全画幅等效视角</strong><span>保守可用光圈起点 f/{{ linkedSettings.max_aperture }}</span></div>
                <p class="helper">焦段与光圈约束会用于建议。变焦中间段未逐档核验最大光圈，非广角端按长焦端值保守处理，不作线性插值。</p>
              </template>
              <div v-else class="two-fields"><div><label for="focal">实际焦距 / mm</label><input id="focal" type="number" v-model="focalLength" min="8" max="1200" placeholder="可不填" /></div><div><label for="aperture">最大光圈 / f</label><input id="aperture" type="number" v-model="maxAperture" min="0.7" max="32" step="0.1" placeholder="可不填" /></div></div>
            </template>
            <div class="two-fields"><div><label for="motion">主体动作</label><select id="motion" v-model="motion"><option>不确定</option><option>静止</option><option>缓慢</option><option>快速</option></select></div><label class="check-row tripod"><input type="checkbox" v-model="tripod" />使用三脚架</label></div>
            </details><div class="upload-consent"><label class="check-row"><input type="checkbox" v-model="consent" />{{ webHosted ? '同意上传这张照片并进行分析' : '同意将这张照片发送到我配置的电脑服务' }}</label><p>{{ !connected ? '连接后会显示当前分析方式。' : mode === 'cloud' ? '云模型分析：照片副本将发送到配置的图像模型服务。' : '演示模式：使用本地规则与图像指标，不向云模型发送照片，也不代表真实识别准确率。' }} 网关不保存照片；相机拍照可能经过系统处理，EXIF 不保证完整。</p></div>
          </fieldset>
          <button class="primary generate" type="submit" :disabled="busy || connecting"><span>{{ busy ? '小栗正在整理拍摄建议…' : connected ? '生成拍摄建议' : webHosted ? '输入体验码，开始拍摄' : '先连接电脑服务' }}</span><span aria-hidden="true">✦</span></button>
          <section v-if="busy" class="analysis-progress" aria-label="分析进度" aria-live="polite">
            <div class="progress-heading"><strong>{{ progressMessage }}</strong><span>总用时 {{ elapsed.toFixed(0) }} 秒</span></div>
            <p class="current-status-time">当前状态已持续 {{ statusElapsed.toFixed(0) }} 秒</p>
            <progress :value="progressStage" max="4" :aria-label="`已完成 ${progressStage}/4 个环节`"></progress>
            <p class="helper">图片与设备 → 识别与定位 → 知识检索 → 方案与校验。进度按环节计算。</p>
            <p v-if="receivedChars" class="helper">已接收 {{ receivedChars.toLocaleString() }} 字符，完整构图校验后显示线稿。</p>
            <p class="progress-log-heading">进度记录 · 左侧为服务处理开始后的记录时刻，不是步骤耗时</p>
            <ol class="progress-log"><li v-for="(item, index) in progressLog" :key="index"><time>开始后 {{ item.seconds.toFixed(1) }} 秒</time>{{ item.message }}</li></ol>
            <div v-if="partialScene" class="partial-result"><span class="result-badge">已完成的画面分析</span><h2>{{ partialScene.scene_label || partialScene.scene_type }}</h2><p>{{ partialScene.subject }} · {{ partialScene.lighting }}</p></div>
            <div v-if="partialParameters" class="partial-result"><span class="result-badge">参数已校验 · 完整方案仍在整理</span><h2>{{ partialParameters.shooting_mode }}</h2><dl class="settings-list"><div v-for="(value, label) in { '光圈': partialParameters.aperture, '快门': partialParameters.shutter_speed, 'ISO': partialParameters.iso, '对焦': partialParameters.focus_mode }" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl><p v-for="step in partialParameters.adjustments" :key="step">{{ step }}</p><details v-if="partialParameters.risks?.length || partialParameters.validation_notes?.length"><summary>适用条件与器材说明</summary><p v-for="note in [...partialParameters.risks, ...partialParameters.validation_notes]" :key="note">{{ note }}</p></details><p class="helper">这是当前已完成的部分，完整方案与构图仍需等待；参数是试拍起点。</p></div>
          </section>
        </form></div>
      </section>
      <section v-else-if="page === 'result'" aria-labelledby="result-title">
        <div class="intro"><h1 id="result-title">你的下一张，已经有了方向。</h1><p>先看构图，再照着走一步，拍一张。</p></div>
        <div v-if="!result" class="empty-result"><img :src="mascot" alt="小栗等待现场照片" /><h2>{{ busy ? '分析正在进行' : '建议还在等你的现场' }}</h2><p>{{ busy ? `${progressMessage} · 已用时 ${elapsed.toFixed(0)} 秒` : '选择照片，写下想要的效果，小栗会给你一个拍摄起点。' }}</p><button class="primary" @click="navigate('shoot')">{{ busy ? '查看当前进度' : '去选照片' }}</button></div>
        <template v-else>
          <div class="notice" :class="{ demo: analysis?.analysis_mode === 'demo' }">{{ analysis?.analysis_mode === 'demo' ? '规则演示结果，不是真实多模态场景识别。' : '云模型分析结果。建议可能有误，以机型能力和试拍为准。' }}</div>
          <div class="scene-summary"><img v-if="preview" :src="preview" alt="本次分析的现场照片" /><div><span>{{ result.camera_profile.display_name }}</span><h2>{{ result.scene.scene_label || result.scene.scene_type }}</h2><p>{{ lightingText }}</p></div></div>
          <div v-if="result.equipment_settings" class="equipment-summary"><strong>{{ sensorLabel(result.camera_profile.sensor_format) }} · {{ result.equipment_settings.camera_lens?.display_name || '未指定镜头' }}</strong><span v-if="result.equipment_settings.focal_length_mm">实际 {{ result.equipment_settings.focal_length_mm }}mm · {{ result.equipment_settings.equivalent_focal_length_mm ? `约 ${result.equipment_settings.equivalent_focal_length_mm}mm 等效` : '等效待核验' }}</span></div>
          <CompositionView :key="analysis?.request_id" :result="result" :preview="preview" />
          <details class="parameter-drawer"><summary>拍摄参数与试拍调整<span>按需要展开</span></summary><div class="shooting-mode"><span>建议拍摄模式</span><strong>{{ result.recommendation.shooting_mode }}</strong></div>
          <dl class="exposure" :class="{ 'phone-exposure': result.camera_profile.device_type === 'phone' }"><div><dt>光圈</dt><dd>{{ result.recommendation.aperture }}</dd></div><div><dt>快门</dt><dd>{{ result.recommendation.shutter_speed }}</dd></div><div><dt>ISO</dt><dd>{{ result.recommendation.iso }}</dd></div></dl>
          <dl class="settings-list"><div v-for="(value, label) in { '曝光补偿': result.recommendation.exposure_compensation, '对焦': result.recommendation.focus_mode, '测光': result.recommendation.metering_mode, '白平衡': result.recommendation.white_balance, '驱动模式': result.recommendation.drive_mode }" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <section class="result-section" v-for="(items, title) in { '为什么这样拍': result.recommendation.reasons, '试拍后怎么调': result.recommendation.adjustments, '注意这些情况': result.recommendation.risks, '器材校验说明': result.recommendation.validation_notes }" :key="title"><h2>{{ title }}</h2><ul v-if="items.length"><li v-for="item in items" :key="item">{{ item }}</li></ul><p v-else>本次没有额外说明。</p></section>
          </details><details class="knowledge"><summary>看看建议依据（{{ result.knowledge_hits.length }} 条）</summary><p>检索模式：{{ result.knowledge_mode }}。相关度不是准确率。</p><p v-for="note in result.knowledge_notes" :key="note">{{ note }}</p><article v-for="hit in result.knowledge_hits" :key="hit.document_id"><h3>{{ hit.title }}</h3><p>{{ hit.content }}</p><a v-if="safeSourceUrl(hit.source)" :href="safeSourceUrl(hit.source)!" target="_blank" rel="noopener noreferrer">查看来源</a><span v-else>{{ hit.source }}</span></article></details>
          <details v-if="result.composition_knowledge_hits?.length" class="knowledge"><summary>构图建议的参考资料</summary><article v-for="hit in result.composition_knowledge_hits" :key="hit.document_id"><h3>{{ hit.title }}</h3><p>{{ hit.content }}</p><a v-if="safeSourceUrl(hit.source)" :href="safeSourceUrl(hit.source)!" target="_blank" rel="noopener noreferrer">查看来源</a></article></details>
          <div class="result-actions"><button class="secondary" @click="exportAdvice">导出拍摄方案</button><button class="primary" @click="navigate('shoot')">调整需求，再试一次</button></div>
          <p v-if="exportMessage" class="helper" role="status">{{ exportMessage }}</p>
        </template>
      </section>
      <section v-else-if="page === 'history'" aria-labelledby="history-title">
        <div class="intro"><h1 id="history-title">留住拍摄的灵感</h1><p>最近 10 次方案保存在这台设备，照片不会存入历史。</p></div>
        <div v-if="!history.length" class="empty-result"><img :src="mascot" alt="小栗等待新的拍摄灵感" /><h2>从你的第一张照片开始</h2><p>生成的方案会出现在这里，下次拍摄时可以再看看。</p><button class="primary" @click="navigate('shoot')">去拍一张</button></div>
        <div v-else class="history-list"><button v-for="item in history" :key="item.id" class="history-item" @click="openHistory(item)"><time>{{ new Date(item.date).toLocaleString('zh-CN') }}</time><strong>{{ item.intent }}</strong><span>{{ item.analysis.result.camera_profile.display_name }} · {{ item.analysis.analysis_mode === 'demo' ? '规则演示' : '云模型' }}</span></button></div>
        <button v-if="history.length" class="text-button" @click="clearHistory">清空本机方案历史</button>
      </section>
      <section v-else-if="webHosted" aria-labelledby="web-connect-title">
        <div class="intro"><h1 id="web-connect-title">让每一次取景，都更有想法。</h1><p>照片、构图手稿、一点拍摄灵感。现在开始。</p></div>
        <div class="web-welcome"><img :src="mascot" alt="小栗摄影助手" /><div><h2>从看见，到拍好</h2><p>读懂现场，用一张构图手稿告诉你，下一张可以怎么拍。</p></div></div>
        <form v-if="!connected" @submit.prevent="connect"><label v-if="inviteRequired" for="access-code" class="field-label">体验码</label><input v-if="inviteRequired" id="access-code" v-model="accessCode" type="password" maxlength="160" placeholder="填写邀请人提供的体验码" autocomplete="off" /><p class="helper">{{ inviteRequired ? '体验码由项目维护者提供。' : '点击下方按钮连接拍摄服务。' }} 你不需要配置模型密钥。</p><button class="primary" :disabled="connecting">{{ connecting ? '正在准备…' : '开启拍摄体验' }}</button></form>
        <div v-else class="notice" role="status">已连接。{{ mode === 'demo' ? '当前为规则演示，可体验完整拍摄流程。' : '已开启云模型照片分析。' }}</div>
        <div v-if="connectionMessage" class="notice" role="status">{{ connectionMessage }}</div><button v-if="connected" class="primary" @click="navigate('shoot')">开始拍摄</button>
        <div class="privacy-note"><h2>关于照片与建议</h2><p>服务不保存上传照片。云模型模式会把照片副本发送给维护者配置的模型提供商；规则演示不会调用云模型。</p><p>方案历史只保存在当前浏览器，最多 10 条且不包含照片。参数与构图建议都需要结合现场试拍。</p><button v-if="connected && inviteRequired" class="text-button" @click="clearConnection">退出本次体验</button></div>
      </section>
      <section v-else aria-labelledby="connect-title">
        <div class="intro"><h1 id="connect-title">让小栗连接你的电脑</h1><p>第一版使用电脑里的模型与知识库。</p></div>
        <div class="connection-illustration" aria-hidden="true"><span>手机</span><span class="connection-line"></span><span>你的电脑</span></div>
        <ol class="setup-steps"><li>电脑上双击 <strong>启动手机服务.cmd</strong>，保持运行。</li><li>手机与电脑连接同一个可信 Wi-Fi。</li><li>填写电脑 IPv4 地址和手机连接令牌。</li></ol>
        <form @submit.prevent="connect">
          <fieldset :disabled="connecting || busy">
            <label for="base-url" class="field-label">电脑服务地址</label><input id="base-url" v-model="baseUrl" type="url" placeholder="http://192.168.1.20:8000" autocomplete="off" autocapitalize="off" spellcheck="false" />
            <p class="helper">不是 8501 / 8502 页面。手机里的 localhost 指向手机自己；电脑 IPv4 可用 ipconfig 查看。</p>
            <label for="token" class="field-label">手机连接令牌</label><input id="token" v-model="token" type="password" placeholder="从电脑的 mobile-access.json 复制" autocomplete="off" />
            <p class="helper">在项目 .launcher/mobile-access.json 中查看。不是云模型的 API Key，请勿填写模型密钥。</p>
          </fieldset>
          <button class="primary" type="submit" :disabled="connecting || busy">{{ connecting ? '正在连接…' : '保存并测试连接' }}</button>
        </form>
        <div v-if="connectionMessage" class="notice" role="status">{{ connectionMessage }}</div>
        <button v-if="connected" class="secondary full-width" @click="navigate('shoot')">连接好了，去拍摄</button>
        <div class="privacy-note"><h2>照片与你的连接信息</h2><p>地址和令牌仅保存在本机 WebView 存储中（演示版未加密），不写进安装包。照片不保存到分析网关；云模型的数据政策取决于你选择的提供商。</p><p>HTTP 连接只适合可信局域网演示，不要开放到公网。正式部署需要 HTTPS 和更完善的登录机制。</p><p>本版提供拍摄建议，不自动设置手机 ISO / 快门；暂不包含实时构图线或自动裁剪。知识库仍在电脑端管理。</p><button class="text-button" @click="clearConnection" :disabled="busy || connecting">清除本机连接信息</button></div>
      </section>
    </main>
    <nav class="bottom-nav" aria-label="主导航"><button :class="{ active: page === 'shoot' }" :aria-current="page === 'shoot' ? 'page' : undefined" @click="navigate('shoot')"><span aria-hidden="true">◎</span>拍摄</button><button :class="{ active: page === 'result' }" :aria-current="page === 'result' ? 'page' : undefined" @click="navigate('result')"><span aria-hidden="true">✦</span>建议</button><button :class="{ active: page === 'history' }" :aria-current="page === 'history' ? 'page' : undefined" @click="navigate('history')"><span aria-hidden="true">▤</span>记录</button><button :class="{ active: page === 'connect' }" :aria-current="page === 'connect' ? 'page' : undefined" @click="navigate('connect')"><span aria-hidden="true">⌁</span>{{ webHosted ? '体验' : '连接' }}</button></nav>
  </div>
</template>
