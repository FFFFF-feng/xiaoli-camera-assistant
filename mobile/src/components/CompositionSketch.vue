<script setup lang="ts">
import { computed, ref, useId, watch, onBeforeUnmount } from 'vue';
import type { CompositionSketchData } from '../types';
import { cameraMove, openSpace, frameAspect } from '../composition-sketch.mjs';
import { tracePhoto, fitPhotoBox, embeddedInMain } from '../sketch-trace.mjs';

const props = withDefaults(defineProps<{ sketch: CompositionSketchData; goal: string; preview?: string }>(), { preview: '' });
const sheet = ref<SVGSVGElement>();
const id = useId().replace(/[^a-zA-Z0-9_-]/g, '');
const innerHeight = computed(() => 360/frameAspect(props.sketch.aspect));
const height = computed(() => innerHeight.value + 40);
const move = computed(() => cameraMove(props.sketch.camera_action));
const sideView = computed(() => ['lower', 'higher'].includes(props.sketch.camera_action));
const movePath = computed(() => {
  const m = move.value, dx = m.x-m.startX, dy = m.y-m.startY;
  const length = Math.hypot(dx, dy) || 1;
  return `M${m.startX} ${m.startY}L${m.x-dx/length*22} ${m.y-dy/length*22}`;
});
const saveMessage = ref('');
const lessonView = ref<'frame' | 'subject' | 'position'>('frame');
const showGrid = ref(true);
const showSpace = ref(true);
const subject = computed(() => props.sketch.elements.find(e => e.role === 'main') || props.sketch.elements[0]!);
type Trace = { ink: string; wash: string; aspect: number; fullFrame: boolean; sourceBox: number[] };
const traces = ref<Record<number,Trace>>({});
const tracing = ref(false), traceError = ref(''), showColor = ref(true), extraMargin = ref(false);
let traceVersion = 0;
onBeforeUnmount(() => { traceVersion++; traces.value = {}; });
const sourceBox = (box: number[] | null | undefined) => box && extraMargin.value
  ? [Math.max(0,box[0]!-.04),Math.max(0,box[1]!-.04),Math.min(1,box[2]!+.04),Math.min(1,box[3]!+.04)] : box;
watch(() => [props.preview,props.sketch,extraMargin.value], async () => {
  const version=++traceVersion;
  traces.value={}; traceError.value=''; tracing.value=false;
  if (!props.preview) return;
  tracing.value=true;
  for (let index=0; index<props.sketch.elements.length; index++) {
    const element=props.sketch.elements[index]!;
    if (embeddedInMain(element,subject.value) || (!element.source_bbox && element !== subject.value)) continue;
    try {
      const trace=await tracePhoto(props.preview,sourceBox(element.source_bbox));
      if (version !== traceVersion) return;
      traces.value={...traces.value,[index]:trace};
    } catch { if (version === traceVersion) traceError.value='照片线稿暂时无法读取，请重新选图分析。'; }
  }
  if (version === traceVersion) tracing.value=false;
}, {immediate:true});
const items = computed(() => props.sketch.elements.map((element,index) => ({
  ...element, index, trace:traces.value[index],
  drawnBox:fitPhotoBox(element.bbox,traces.value[index]?.aspect || 0,360/innerHeight.value),
  embedded:embeddedInMain(element,subject.value),
})));
const main = computed(() => items.value.find(e => e.role === 'main') || items.value[0]!);
const mainTrace = computed(() => main.value.trace);
const placement = computed(() => {
  const [x1,y1,x2,y2]=main.value.drawnBox as [number,number,number,number];
  const x=Math.min(2,Math.floor((x1+x2)/2*3)), y=Math.min(2,Math.floor((y1+y2)/2*3));
  return {cell:['左上','上方中间','右上','左侧中间','中央','右侧中间','左下','下方中间','右下'][y*3+x],width:Math.round((x2-x1)*100),height:Math.round((y2-y1)*100)};
});
const space = computed(() => openSpace(items.value.filter(e=>!e.embedded).map(e=>({bbox:e.drawnBox}))));

function save() {
  if (!sheet.value) return;
  const copy = sheet.value.cloneNode(true) as SVGSVGElement;
  copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  copy.setAttribute('width', '800'); copy.setAttribute('height', String(height.value * 2));
  copy.querySelectorAll('path, circle, line, rect, ellipse, polyline').forEach(node => node.setAttribute('vector-effect', 'non-scaling-stroke'));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = '小栗-构图简笔画.svg'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000); saveMessage.value = '示意图已保存';
}
</script>

<template>
  <div class="sketch-lesson">
    <div class="lesson-title"><span>{{ sketch.theme || goal }}</span><em v-if="sketch.mood">{{ sketch.mood }}</em></div>
    <div class="lesson-tabs" role="group" aria-label="分镜教学视图">
      <button type="button" :aria-pressed="lessonView === 'frame'" @click="lessonView = 'frame'">九宫格构图</button>
      <button type="button" :aria-pressed="lessonView === 'subject'" @click="lessonView = 'subject'">主体画像</button>
      <button type="button" :aria-pressed="lessonView === 'position'" @click="lessonView = 'position'">机位动作</button>
    </div>
    <figure v-show="lessonView === 'frame'" class="sketch-sheet">
      <div class="sketch-sheet-heading"><strong>取景摆位参考</strong><span>{{ sketch.aspect === 'portrait' ? '竖幅' : sketch.aspect === 'landscape' ? '横幅' : '方形' }} · 教学分镜</span></div>
      <svg ref="sheet" :viewBox="`0 0 400 ${height}`" role="img" :aria-label="`${goal}的九宫格构图手稿。${sketch.caption}`" font-family="sans-serif">
        <title>{{ sketch.theme || goal }}</title><desc>{{ sketch.caption }}。{{ sketch.space_note }}。{{ sketch.narration }}。位置与大小为建议示意。</desc>
        <rect width="400" :height="height" fill="#fcfcfa" />
        <rect x="20" y="20" width="360" :height="innerHeight" fill="#fcfcfa" stroke="#8593a4" stroke-width="1" />
        <g v-if="showSpace && space.w * space.h > .08">
          <rect :x="20+space.x*360" :y="20+space.y*innerHeight" :width="space.w*360" :height="space.h*innerHeight" fill="#e5edf6" opacity=".65" />
          <text :x="20+(space.x+space.w/2)*360" :y="20+(space.y+space.h/2)*innerHeight" text-anchor="middle" fill="#748ca9" font-size="10" :writing-mode="space.w < .22 ? 'tb' : 'lr'">留白</text>
        </g>
        <g v-if="showGrid" stroke="#9aaabb" stroke-width=".8" stroke-dasharray="3 5" opacity=".6"><path :d="`M140 20V${height-20}M260 20V${height-20}M20 ${20+innerHeight/3}H380M20 ${20+innerHeight*2/3}H380`" /><circle v-for="point in [[140,20+innerHeight/3],[260,20+innerHeight/3],[140,20+innerHeight*2/3],[260,20+innerHeight*2/3]]" :key="point.join()" :cx="point[0]" :cy="point[1]" r="3" fill="#9aaabb" stroke="none" /></g>
        <path v-if="sketch.horizon_y != null" :d="`M22 ${20+sketch.horizon_y*innerHeight}H378`" fill="none" stroke="#b9b4a6" stroke-width="1.6" />
        <g v-for="element in items.filter(e => !e.embedded)" :key="element.index">
          <svg :x="20+element.drawnBox[0]*360" :y="20+element.drawnBox[1]*innerHeight" :width="(element.drawnBox[2]-element.drawnBox[0])*360" :height="(element.drawnBox[3]-element.drawnBox[1])*innerHeight" :viewBox="`0 0 ${element.trace?.aspect || 1} 1`" preserveAspectRatio="xMidYMid meet">
            <template v-if="element.trace"><image v-if="showColor" :href="element.trace.wash" :width="element.trace.aspect" height="1" /><image :href="element.trace.ink" :width="element.trace.aspect" height="1" :opacity="element.role === 'main' ? 1 : .65" /></template>
            <template v-else><rect width="1" height="1" fill="#eaf0f5" fill-opacity=".4" stroke="#a8b9cc" stroke-width=".005" stroke-dasharray=".02 .02" /></template>
          </svg>
          <circle :cx="Math.max(30,20+element.drawnBox[0]*360)" :cy="Math.max(30,20+element.drawnBox[1]*innerHeight)" r="8" :fill="element.role === 'main' ? '#355d94' : '#9aa5b2'" />
          <text :x="Math.max(30,20+element.drawnBox[0]*360)" :y="Math.max(30,20+element.drawnBox[1]*innerHeight)+3" text-anchor="middle" fill="white" font-size="9">{{ element.index+1 }}</text>
        </g>
      </svg>
      <div class="sketch-controls"><label><input v-model="showGrid" type="checkbox" />九宫格</label><label><input v-model="showSpace" type="checkbox" />留白</label><label><input v-model="showColor" type="checkbox" />浅色</label><button type="button" @click="save">保存手稿</button></div>
      <p v-if="tracing" class="trace-note" role="status">正在保留原照片中的轮廓与细节…</p><p v-else-if="!mainTrace" class="trace-note">{{ traceError || '历史记录不保留照片。重新分析原照片，可生成保留主体特征的线稿。' }}</p><p v-else class="trace-note">{{ mainTrace.fullFrame ? '当前使用原图整体线稿。重新分析可细化主体区域。' : '轮廓取自原照片，保持原始比例。取材区域由模型估计，可对照原图检查。' }}</p><figcaption>{{ sketch.caption }}</figcaption>
    </figure>
    <figure v-if="lessonView === 'subject'" class="subject-study">
      <div class="sketch-sheet-heading"><strong>先看懂你的主角</strong><span>原照片提取线稿</span></div>
      <svg viewBox="0 0 400 360" role="img" :aria-label="`${subject.label}的原图轮廓。${subject.description || ''}`">
        <rect width="400" height="360" fill="#fcfcfa" />
        <svg v-if="mainTrace" x="35" y="20" width="330" height="320" :viewBox="`0 0 ${mainTrace.aspect} 1`" preserveAspectRatio="xMidYMid meet"><image v-if="showColor" :href="mainTrace.wash" :width="mainTrace.aspect" height="1"/><image :href="mainTrace.ink" :width="mainTrace.aspect" height="1"/></svg>
        <text v-else x="200" y="180" text-anchor="middle" font-size="13" fill="#8493a5">{{ tracing ? '正在绘制原图轮廓…' : '重新分析原照片，生成主体线稿' }}</text>
      </svg>
      <div v-if="preview" class="sketch-controls"><label><input v-model="showColor" type="checkbox" />浅色</label><label v-if="subject.source_bbox"><input v-model="extraMargin" type="checkbox" />保留更多边缘</label></div>
      <figcaption><strong>{{ subject.label }}</strong><p>{{ subject.description || '保留主体完整轮廓，照着九宫格中的大小和位置取景。' }}</p></figcaption>
      <p class="study-note">保留当前照片的姿态与特征；改变机位后的透视需现场确认。</p>
    </figure>
    <div v-if="lessonView === 'position'" class="sketch-position">
      <div class="sketch-sheet-heading"><strong>机位这样调整</strong><span>{{ sideView ? '从侧面看' : '从上方看' }}</span></div>
      <svg viewBox="0 0 340 220" role="img" :aria-label="sketch.camera_instruction">
        <defs><marker :id="`move-${id}`" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6" fill="none" stroke="#b56a28" stroke-width="1.5" /></marker></defs>
        <g v-if="!sideView"><ellipse cx="170" cy="44" rx="22" ry="13" fill="#e4eee8" stroke="#254f41" stroke-width="2" /><text x="205" y="49" fill="#39564c" font-size="12">主体</text><path :d="`M${move.x} ${move.y-12}L150 58M${move.x} ${move.y-12}L190 58`" fill="none" stroke="#b7c9c0" stroke-dasharray="4 5" /></g>
        <g v-else><path d="M37 174H305" stroke="#bac9bf" /><rect x="240" y="72" width="27" height="95" rx="10" fill="#e4ebf3" stroke="#8c9fb5" /><text x="243" y="193" fill="#39564c" font-size="12">主体</text><path :d="`M${move.x+17} ${move.y}L243 99`" stroke="#b7c9c0" stroke-dasharray="4 5" /></g>
        <g v-if="sketch.camera_action !== 'stay'" :transform="`translate(${move.startX-12} ${move.startY-9})`" fill="none" stroke="#b6c0b8" stroke-dasharray="3 3"><rect width="24" height="18" rx="3" /></g>
        <path v-if="sketch.camera_action !== 'stay'" :d="movePath" stroke="#b56a28" stroke-width="2.3" :marker-end="`url(#move-${id})`" />
        <g :transform="`translate(${move.x-16} ${move.y-10})`" stroke="#254f41" stroke-width="2" fill="white"><rect width="32" height="22" rx="4" /><circle cx="16" cy="11" r="6" /><path d="M5 0L9 -5H23L27 0" fill="#e4eee8" /></g>
        <text :x="move.x" :y="move.y+32" text-anchor="middle" font-size="12" fill="#254f41">你的相机 / 手机</text>
      </svg>
      <p class="sketch-move-label">{{ move.label }}</p><p class="sketch-instruction">{{ sketch.camera_instruction }}</p>
    </div>
    <div class="composition-reading">
      <p class="placement-line"><span>主体位置<strong>{{ placement.cell }}</strong></span><span>轮廓区域占比<strong>宽 {{ placement.width }}% · 高 {{ placement.height }}%</strong></span></p>
      <div class="sketch-legend"><p v-for="(element, index) in sketch.elements" :key="index"><b>{{ index+1 }}</b><strong>{{ element.label }}</strong><span>{{ element.role === 'main' ? '主角' : '环境' }}</span><small v-if="element.description">{{ element.description }}</small></p></div>
      <div v-if="subject.identity_features?.length" class="identity-features"><span>这些特征要保留</span><ul><li v-for="feature in subject.identity_features" :key="feature">{{ feature }}</li></ul></div><div class="space-reading"><span>留白的用意</span><p>{{ sketch.space_note || `${space.label}是当前示意中较完整的空间。保留多少背景，请结合现场与拍摄意图判断。` }}</p></div>
      <blockquote v-if="sketch.narration" class="shot-narration"><span>这一张，想讲的故事</span><p>{{ sketch.narration }}</p></blockquote>
    </div>
    <div class="sketch-footer"><p>线稿保留原照片的轮廓与姿态，用于理解取景摆位。新机位的透视、遮挡与光线变化需现场试拍确认。</p><span role="status">{{ saveMessage }}</span></div>
  </div>
</template>

<style scoped>
.trace-note { font-size: 11px; line-height: 1.9; color: #8291a3; margin: 12px 0 0; }.identity-features { margin: 22px 0; }.identity-features > span { font-size: 11px; color: #71849b; }.identity-features ul { display: flex; flex-wrap: wrap; gap: 7px; list-style: none; padding: 0; margin: 10px 0; }.identity-features li { background: #f0f3f7; border-radius: 4px; padding: 5px 9px; font-size: 12px; color: #536b87; }

.sketch-lesson { margin: 24px 0; }.lesson-title { display: flex; gap: 14px; align-items: baseline; margin: 20px 0 16px; }.lesson-title > span { font-family: "Songti SC", "SimSun", serif; font-size: 24px; line-height: 1.6; color: #283d56; }.lesson-title em { font-size: 11px; font-style: normal; color: #738399; }
.lesson-tabs { display: flex; gap: 3px; padding: 4px; background: #edf1f6; border-radius: 6px; margin-bottom: 18px; }.lesson-tabs button { flex: 1; padding: 10px 5px; border: 0; background: transparent; color: #78869a; font-size: 12px; border-radius: 4px; }.lesson-tabs button[aria-pressed="true"] { color: #315b9c; background: white; box-shadow: 0 1px 4px #263e5910; }
.sketch-sheet, .subject-study { margin: 0; padding: 20px 22px; border: 1px solid #e0e4e9; background: #fcfcfa; border-radius: 3px; }.sketch-sheet-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; }.sketch-sheet-heading strong { font-size: 12px; font-weight: 500; color: #53677e; }.sketch-sheet-heading > span { font-size: 10px; color: #8b98a7; }.sketch-sheet > svg { display: block; width: 100%; max-height: 520px; }.sketch-sheet figcaption { font-size: 14px; font-weight: 500; line-height: 1.9; color: #354b67; margin: 14px 0 0; }
.sketch-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 15px; border-top: 1px solid #e3e8ec; padding-top: 12px; margin-top: 8px; }.sketch-controls label { font-size: 11px; color: #738399; display: flex; gap: 4px; align-items: center; }.sketch-controls input { accent-color: #315b9c; }.sketch-controls button { margin-left: auto; border: 0; background: transparent; color: #315b9c; font-size: 11px; padding: 5px 0; }
.subject-study { background: #f5f6f5; }.subject-study > svg { width: 100%; max-height: 340px; display: block; }.subject-study figcaption { text-align: center; }.subject-study figcaption > strong { font-family: "Songti SC", "SimSun", serif; font-size: 24px; font-weight: 500; }.subject-study figcaption p, .study-note { font-size: 12px; color: #758398; line-height: 1.8; text-align: center; }
.sketch-position { padding: 25px 20px; background: #f6f8fa; }.sketch-position > svg { width: 100%; max-height: 290px; display: block; }.sketch-move-label { font-size: 17px; color: #9b6838; margin: 4px 0; }.sketch-instruction { font-size: 13px; line-height: 1.9; color: #53677e; }
.composition-reading { padding-top: 22px; }.placement-line { display: flex; flex-wrap: wrap; gap: 20px 40px; margin: 0 0 20px; }.placement-line > span { font-size: 10px; color: #8190a2; }.placement-line strong { display: block; font-size: 15px; font-weight: 500; color: #354b67; margin-top: 5px; }.sketch-legend p { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin: 7px 0; line-height: 1.8; }.sketch-legend b { display: inline-grid; place-items: center; width: 16px; height: 16px; background: #eef2f6; color: #60748e; font-size: 10px; border-radius: 50%; }.sketch-legend strong { font-size: 12px; font-weight: 500; }.sketch-legend span { font-size: 10px; color: #8b98a7; }.sketch-legend small { font-size: 11px; color: #738399; }
.space-reading { margin: 24px 0; padding-left: 14px; border-left: 2px solid #c7d5e6; }.space-reading > span { font-size: 11px; color: #74879d; }.space-reading p { font-size: 13px; color: #53677e; line-height: 1.9; margin: 6px 0; }.shot-narration { margin: 26px 0 12px; padding: 22px 0; border-top: 1px solid #dce2e9; border-bottom: 1px solid #dce2e9; }.shot-narration > span { color: #8a99a9; font-size: 10px; }.shot-narration p { font-family: "Songti SC", "SimSun", serif; font-size: 19px; font-weight: 400; line-height: 2; color: #435973; margin: 10px 0 0; }.sketch-footer p { font-size: 10px; color: #8a99a9; line-height: 1.8; }.sketch-footer [role="status"] { font-size: 11px; color: #315b9c; }
button:focus-visible { outline: 2px solid #315b9c; outline-offset: 3px; }
@media(max-width:600px) { .sketch-sheet, .subject-study { padding: 16px 10px; }.lesson-title { flex-direction: column; gap: 0; }.lesson-title > span { font-size: 22px; }.sketch-sheet > svg { max-height: 430px; }.shot-narration p { font-size: 18px; }.sketch-controls { gap: 10px; } }
</style>
