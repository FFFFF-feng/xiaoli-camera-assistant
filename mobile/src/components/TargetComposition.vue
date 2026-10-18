<script setup lang="ts">
import { computed,onBeforeUnmount,ref,useId,watch } from 'vue';
import type { TargetBoard } from '../types';
import ReportHeading from './ReportHeading.vue';
import { DEFAULT_TARGET_COLOR, DEFAULT_TARGET_GRID, detailPath, outlinePath, sourceLayout, silhouetteLayers, silhouetteStrokePath, hasPhotoCut, unknownFrameRects, targetLayerPaint, targetCompositionCopy, thirdsGuide } from '../target-board.mjs';
import { frameAspect } from '../composition-sketch.mjs';
import { sceneColorTransform } from '../scene-colors.mjs';
import { sceneEdgeDirections,sceneContinuationPaths } from '../scene-extension.mjs';
import { sceneRenderer,createLatestTask } from '../scene-render.mjs';
const props=defineProps<{board:TargetBoard;reference?:string}>();
const sheet=ref<SVGSVGElement>();
const grid=ref(DEFAULT_TARGET_GRID),labels=ref(true),color=ref(DEFAULT_TARGET_COLOR),environment=ref(true),extendBackground=ref(true),saved=ref(''),showSource=ref(false);
watch(()=>props.board,()=>{showSource.value=false;saved.value='';});
const width=720;
const original=computed(()=>sourceLayout(props.board) as {aspect:number;layers:TargetBoard['layers']}|null);
const height=computed(()=>width/(showSource.value&&original.value?original.value.aspect:frameAspect(props.board.aspect)));
const guides=computed(()=>thirdsGuide(width,height.value));
const layers=computed(()=>(showSource.value&&original.value?original.value.layers:props.board.layers).map((layer,index)=>({...layer,index})).sort((a,b)=>a.depth-b.depth));
const markedLayers=computed(()=>layers.value.filter(layer=>layer.kind!=='background'));
const visibleLayers=computed(()=>layers.value.filter(layer=>environment.value||layer.representation!=='context_lines'));
const visibleMarks=computed(()=>markedLayers.value.filter(layer=>environment.value||layer.representation!=='context_lines'));
const distanceNames={closer:'适当靠近',farther:'适当退后',similar:'保持相近距离',unknown:'距离需现场判断'};
const copy=computed(()=>targetCompositionCopy(props.board));
const sourcePreserving=computed(()=>props.board.layout_mode==='source_preserving');
const main=computed(()=>props.board.layers.find(layer=>layer.role==='main')!);
const structureScene=computed(()=>props.board.layers.some(layer=>layer.representation==='scene_structure'));
const clippedScene=computed(()=>props.board.layers.some(hasPhotoCut));
const unknownRects=computed(()=>unknownFrameRects(props.board,showSource.value));
const legacyBoundary=computed(()=>props.board.layers.some(layer=>layer.representation!=='scene_structure'&&layer.role==='main'&&!layer.photo_boundary));
const sceneColor=ref<{key:string;url:string;aspect:number;fills:(string|null)[][];pixels:{data:Uint8ClampedArray;width:number;height:number}}|null>(null),colorBusy=ref(false),colorFailed=ref(false);
const colorClip=`scene-color-${useId()}`;
const colorsTask=createLatestTask(),extensionTask=createLatestTask();
watch([()=>props.reference,()=>props.board],([source,board])=>{
  colorsTask.cancel();sceneColor.value=null;colorFailed.value=false;colorBusy.value=!!source;
  if(!source)return;
  void colorsTask.run(()=>sceneRenderer.colors(source,board),(result:NonNullable<typeof sceneColor.value>)=>{sceneColor.value=result;},
    ()=>{colorFailed.value=true;},()=>{colorBusy.value=false;});
},{immediate:true});
onBeforeUnmount(()=>{colorsTask.cancel();extensionTask.cancel();});
const colorTransform=computed(()=>sceneColorTransform(props.board,showSource.value));
const hasSceneColor=computed(()=>color.value&&sceneColor.value&&colorTransform.value
  &&Math.abs(sceneColor.value.aspect/(props.board.source_photo_aspect||0)-1)<.02);
const edgeDirections=computed(()=>sceneColor.value?sceneEdgeDirections(props.board,sceneColor.value.pixels.width,sceneColor.value.pixels.height):[]);
const extensionImage=ref<string|null>(null);
watch(()=>({enabled:hasSceneColor.value&&extendBackground.value&&!showSource.value&&!structureScene.value&&!clippedScene.value,scene:sceneColor.value,
  transform:colorTransform.value,aspect:frameAspect(props.board.aspect),directions:edgeDirections.value}),state=>{
  extensionTask.cancel();extensionImage.value=null;
  if(!state.enabled||!state.scene||!state.transform)return;
  void extensionTask.run(()=>sceneRenderer.extension(state.scene!,state.transform!,state.aspect,state.directions),
    (result:string|null)=>{extensionImage.value=result;});
},{immediate:true});
const continuedLines=computed(()=>extensionImage.value&&colorTransform.value&&sceneColor.value
  ?sceneContinuationPaths(edgeDirections.value,colorTransform.value,sceneColor.value.pixels.width,sceneColor.value.pixels.height,width,height.value):[]);
const mainFills=computed(()=>sceneColor.value?.fills[props.board.layers.indexOf(main.value)]||[]);
const size=computed(()=>({w:Math.round((main.value.bbox[2]!-main.value.bbox[0]!)*100),h:Math.round((main.value.bbox[3]!-main.value.bbox[1]!)*100)}));
const portrait=computed(()=>({layer:{...main.value,bbox:[0,0,1,1]},w:(main.value.bbox[2]!-main.value.bbox[0]!)*width,h:(main.value.bbox[3]!-main.value.bbox[1]!)*width/frameAspect(props.board.aspect)}));
function save() {
  if(!sheet.value)return;
  const copy=sheet.value.cloneNode(true) as SVGSVGElement;
  copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(width));copy.setAttribute('height',String(height.value));
  const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=showSource.value?'小栗-原始布局估计.svg':'小栗-推荐构图示意.svg';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);saved.value='线稿已保存（构图示意，非实拍预测）';
}
</script>
<template>
  <div class="target-composition">
    <div class="target-heading"><ReportHeading :title="board.intent" icon="image" eyebrow="目标画面" /><span>{{ showSource?'原始布局估计':copy.heading }}</span></div>
    <div v-if="original" class="target-mode" role="group" aria-label="轮廓布局对照"><button type="button" :aria-pressed="!showSource" @click="showSource=false">推荐布局</button><button type="button" :aria-pressed="showSource" @click="showSource=true">原始物体布局</button></div>
    <aside v-if="sourcePreserving" class="target-preserving" data-source-preserving>
      <strong>{{ copy.status ? `${copy.status} · ${copy.heading}` : copy.heading }}</strong><p>{{ copy.reason }}</p><p>{{ copy.action }}</p><p>{{ copy.drawing }}</p>
    </aside>
    <figure class="target-sheet">
      <svg ref="sheet" :viewBox="`-18 -18 ${width+36} ${height+36}`" role="img" :aria-label="showSource?'原始布局估计，用于核对轮廓与空间位置':`推荐构图：${board.intent}。使用${structureScene?'真实边界的场景结构线':'物体轮廓'}表达目标布局。${copy.drawing}`" font-family="sans-serif">
        <title>{{ showSource?'原始物体布局估计':board.intent }}</title><desc>物体识别和轮廓提取可能有误，请对照原图。{{ copy.drawing }}{{ color?'插画配色用于区分主体和背景，不代表景物的准确颜色或实际拍摄效果。':'' }}{{ extensionImage?'画框边缘依据可见轮廓与线条方向作推测延伸，未拍到的景物未知。':'' }}</desc>
        <rect x="-18" y="-18" :width="width+36" :height="height+36" fill="#fafcfd"/>
        <rect :width="width" :height="height" :fill="color?'#f5f8f6':'#fff'" stroke="#a5b4c5" stroke-width="1"/>
        <defs><clipPath :id="colorClip"><rect :width="width" :height="height"/></clipPath><pattern :id="`${colorClip}-unknown`" width="9" height="9" patternUnits="userSpaceOnUse"><rect width="9" height="9" fill="#f3f3ef"/><path d="M-2,2L2,-2M0,9L9,0M7,11L11,7" stroke="#c7c9c4" stroke-width="1"/></pattern></defs>
        <g v-if="extensionImage" data-scene-extension :clip-path="`url(#${colorClip})`" pointer-events="none"><image :href="extensionImage" x="0" y="0" :width="width" :height="height" preserveAspectRatio="none"/></g>
        <g v-if="hasSceneColor&&colorTransform&&sceneColor" data-scene-color :clip-path="`url(#${colorClip})`" pointer-events="none">
          <image :href="sceneColor.url" :x="colorTransform.x*width" :y="colorTransform.y*height" :width="colorTransform.width*width" :height="colorTransform.height*height" preserveAspectRatio="none"/>
        </g>
        <g v-for="layer in visibleLayers" :key="layer.index" :data-representation="layer.representation||'silhouette'" :data-source-object-id="layer.source_object_id" :stroke="targetLayerPaint(layer,color).stroke" stroke-linecap="round" stroke-linejoin="round">
          <path v-for="(part,index) in silhouetteLayers(layer)" :key="`shape-${index}`" :d="outlinePath(part,width,height)" fill-rule="evenodd" :fill="hasSceneColor?(sceneColor?.fills[layer.index]?.[Number(index)]||targetLayerPaint(layer,color).fill):targetLayerPaint(layer,color).fill" :fill-opacity="hasSceneColor?1:targetLayerPaint(layer,color).fillOpacity" stroke="none"/>
          <path v-for="(part,index) in silhouetteLayers(layer)" :key="`boundary-${index}`" data-visible-boundary :d="silhouetteStrokePath(part,width,height)" fill="none" :stroke="layer.kind==='background' ? 'none' : undefined" :stroke-dasharray="!layer.photo_boundary?'4 3':undefined" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
          <path v-for="(path,index) in layer.details" :key="`detail-${index}`" class="subject-detail" :d="detailPath(layer,path,width,height)" fill="none" :stroke-width="layer.representation==='scene_structure'?1.4:layer.representation==='context_lines' ? (color?1.1:.85) : layer.details.length>10 ? .72 : 1.1" vector-effect="non-scaling-stroke"/>
        </g>
        <g v-if="unknownRects.length" data-unknown-photo-field pointer-events="none"><rect v-for="(rect,index) in unknownRects" :key="index" :x="rect[0]*width" :y="rect[1]*height" :width="rect[2]*width" :height="rect[3]*height" :fill="`url(#${colorClip}-unknown)`"/></g>
        <g v-if="environment&&continuedLines.length" data-scene-continuations :clip-path="`url(#${colorClip})`" fill="none" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" opacity=".8"><path v-for="(line,index) in continuedLines" :key="index" :d="line!.path" :stroke="targetLayerPaint(board.layers[line!.layerIndex],true).stroke" vector-effect="non-scaling-stroke"/></g>
        <g v-if="grid" data-thirds-guide role="group" aria-label="三分线与四个交点，作为构图位置参考" pointer-events="none">
          <line v-for="(line,index) in guides.lines" :key="`guide-${index}`" :x1="line[0]" :y1="line[1]" :x2="line[2]" :y2="line[3]" stroke="#607e94" stroke-width="1.1" opacity=".8" stroke-dasharray="6 7" vector-effect="non-scaling-stroke"/>
          <circle v-for="(point,index) in guides.points" :key="`point-${index}`" :cx="point[0]" :cy="point[1]" r="4.5" :fill="color?'#fff3d5':'#fff'" :stroke="color?'#a77d36':'#607e94'" stroke-width="1.3" vector-effect="non-scaling-stroke"/>
        </g>
        <g v-if="labels" font-size="16" text-anchor="middle">
          <g v-for="layer in visibleMarks" :key="layer.index"><circle :cx="layer.bbox[0]!*width+14" :cy="layer.bbox[1]!*height+14" r="12" :fill="layer.role==='main' ? '#315b9c' : '#8094a6'"/><text :x="layer.bbox[0]!*width+14" :y="layer.bbox[1]!*height+20" fill="white">{{ layer.index+1 }}</text></g>
        </g>
      </svg>
      <div class="target-controls"><label><input v-model="environment" type="checkbox"/>环境线条</label><label><input v-model="grid" type="checkbox"/>三分线</label><label><input v-model="labels" type="checkbox"/>景物标记</label><label><input v-model="color" type="checkbox"/>场景填色</label><label v-if="hasSceneColor&&!showSource&&!structureScene&&!clippedScene"><input v-model="extendBackground" type="checkbox"/>延伸背景</label><button type="button" @click="save">{{ showSource?'保存原始布局':'保存推荐图' }}</button></div>
      <figcaption>{{ showSource?'同一组物体轮廓放回原图位置，用于核对物体形状与空间关系；不代表精确分割。':sourcePreserving?`以第 ${board.reference_photo_id.slice(5)} 张为参考保留原取景中的空间关系。${copy.drawing}`:`以第 ${board.reference_photo_id.slice(5)} 张为参考规划；主体目标占比：宽 ${size.w}%、高 ${size.h}%。这是构图示意，不是实拍预测。` }}<span v-if="hasSceneColor"> 插画配色帮助区分景物，颜色不作精确还原；未绘制的范围不等于现场留白。</span><span v-else-if="color">{{ colorBusy?' 正在准备场景填色…':colorFailed?' 参考图配色暂时无法读取，保留原有示意色。':' 完整场景填色需要匹配的参考照片，当前保留主体示意色。' }}</span></figcaption>
      <p v-if="extensionImage" class="target-guide-tip">边缘依据可见轮廓与线条方向作推测延伸，新增区域为示意，实际景物需现场确认。</p>
      <p v-if="clippedScene" class="target-guide-tip" data-photo-boundary-note>主体与原照片边界接触，画外形体未知；填色闭合不表示真实物体底边。斜线区域未被原照片覆盖。</p>
      <p v-else-if="legacyBoundary" class="target-guide-tip" data-legacy-boundary-note>这份历史轮廓未记录画幅截断证据，虚线闭合不代表物体已拍完整。</p>
      <p v-if="structureScene" class="target-guide-tip" data-scene-structure-note>场景结构线来自参考照片的可见边界，整体共同变换以保留空间关联；开放路径不代表完整物体分割，未拍到的区域保持未知。<span v-if="sourcePreserving">当前保留原取景，用结构线核对保留依据及现场检查重点。</span><span v-if="hasSceneColor">底层配色仅映射参考照片，结构路径自身不填充。</span></p>
      <p v-if="grid" class="target-guide-tip">两横两竖将画面分为九格，圆点标出四个交点，方便比较主体位置；不必强行把主体放在交点上。</p>
    </figure>
    <figure v-if="reference" class="target-reference">
      <img :src="reference" :alt="`第 ${board.reference_photo_id.slice(5)} 张原图，用于核对物体外形`"/>
      <figcaption><strong>形态对照 · 第 {{ board.reference_photo_id.slice(5) }} 张原图</strong><span>对照主体外形和可见细节；上方是取景示意，不是实际拍摄效果。</span></figcaption>
    </figure>
    <p v-if="board.narration" class="target-narration">{{ board.narration }}</p>
    <details class="subject-study report-disclosure"><summary>放大看主体细节 · {{ main.label }}</summary>
      <svg :viewBox="`-8 -8 ${portrait.w+16} ${portrait.h+16}`" role="img" :aria-label="`${main.label}的推荐形象与结构线条`" stroke="#415970" stroke-linecap="round" stroke-linejoin="round">
        <path v-for="(part,index) in silhouetteLayers(portrait.layer)" :key="index" :d="outlinePath(part,portrait.w,portrait.h)" fill-rule="evenodd" :fill="hasSceneColor?(mainFills[Number(index)]||targetLayerPaint(main,color).fill):targetLayerPaint(main,color).fill" :fill-opacity="hasSceneColor?1:targetLayerPaint(main,color).fillOpacity" stroke="none"/>
        <path v-for="(part,index) in silhouetteLayers(portrait.layer)" :key="`boundary-${index}`" :d="silhouetteStrokePath(part,portrait.w,portrait.h)" fill="none" :stroke-dasharray="!main.photo_boundary?'4 3':undefined" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
        <path v-for="(path,index) in main.details" :key="`detail-${index}`" class="subject-detail" :d="detailPath(portrait.layer,path,portrait.w,portrait.h)" fill="none" :stroke-width="main.details.length>10 ? .9 : 1.1" vector-effect="non-scaling-stroke"/>
      </svg><p>{{ main.identity_features.join('、') }}。{{ sourcePreserving?'保留原取景时的形态与结构线仍需现场核对。':'新机位下的形态仍需现场核对。' }}</p>
    </details>
    <p v-if="board.unrendered_objects?.length" class="target-unrendered" data-unrendered-objects><strong>已识别但未可靠绘出：{{ board.unrendered_objects.join('、') }}</strong><span>下列辨识描述来自视觉识别，不表示这些部件都已画出。</span></p>
    <details class="target-legend report-disclosure"><summary>景物标记说明<small>{{ board.layers.length }} 项 · 对照图中编号</small></summary><div class="target-legend-list"><article v-for="(layer,index) in board.layers" :key="index"><b>{{ layer.kind==='background' ? '景' : index+1 }}</b><div><strong>{{ layer.label }}</strong><p>{{ layer.identity_features?.join('、') }}</p><small>{{ layer.certainty==='approximate' ? '视角近似，需试拍' : '特征依据参考照片' }}</small></div></article></div></details>
    <section class="target-changes" aria-label="构图改善对照"><ReportHeading title="比原图改善在哪里" description="先看推荐调整，再对照原图与预期效果。" icon="sparkles" level="h4" /><template v-if="sourcePreserving"><article><div class="change-row change-original"><span>当前取景</span><p>路牌、路灯与道路环境作为连续场景一起保留。</p></div><div class="change-row change-adjustment"><span>{{ copy.changeLabel }}</span><p>{{ copy.changeText }}</p></div><div class="change-row change-benefit"><span>预期改善</span><p>保持真实空间关系，让灯光、路牌与环境的关联自然成立。</p></div></article></template><template v-else><article v-for="(change,index) in board.changes" :key="index"><div class="change-row change-original"><span>原图问题</span><p>{{ change.problem }}</p></div><div class="change-row change-adjustment"><span>推荐调整</span><p>{{ change.adjustment }}</p></div><div class="change-row change-benefit"><span>预期改善</span><p>{{ change.benefit }}</p></div></article></template></section>
    <aside class="target-distance"><span class="distance-label">机位与距离 · 现场操作</span><strong>{{ distanceNames[board.distance_relation] }}</strong><p>{{ board.distance_instruction }}</p></aside>
    <details v-if="board.limitations.length" class="target-limitations report-disclosure"><summary>线稿说明与识别限制<small>{{ board.limitations.length }} 条 · 使用前了解</small></summary><ul><li v-for="note in board.limitations" :key="note">{{ note }}</li></ul></details><span class="report-save-status" role="status">{{ saved }}</span>
  </div>
</template>
<style scoped>
.target-composition { min-width: 0; word-break: normal; overflow-wrap: break-word; }
.target-heading { display: flex; align-items: flex-start; gap: 16px; justify-content: space-between; margin: 26px 0 16px; }
.target-heading .report-heading { margin-bottom: 0; flex: 1; }
.target-heading > span { font-size: 11px; color: #7a5d44; background: #f5ebdf; border: 1px solid #e8d6c2; border-radius: 6px; padding: 5px 8px; max-width: 40%; }
.target-mode { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.target-mode button { border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--muted); padding: 9px 14px; font-size: 13px; }
.target-mode button[aria-pressed=true] { background: var(--green); color: #fff; border-color: var(--green); }
.target-preserving { margin: 12px 0; padding: 16px 18px; background: #f2f6ef; border: 1px solid #d1ddca; border-left: 4px solid #6d855a; border-radius: 10px; color: #425b36; font-size: 13px; line-height: 1.9; }
.target-preserving strong { font-size: 15px; font-weight: 700; }
.target-preserving p { margin: 6px 0 0; color: #5b6b50; }
.target-sheet { margin: 0; padding: 18px; background: #fafcfd; border: 1px solid #dce4eb; border-radius: 12px; }
.target-sheet svg { display: block; width: 100%; max-height: 520px; }
.target-controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; padding-top: 14px; margin-top: 12px; border-top: 1px solid #dce4eb; }
.target-controls label { display: flex; gap: 5px; align-items: center; font-size: 12px; color: #566a7c; }
.target-controls input { accent-color: var(--green); }
.target-controls button { margin-left: auto; border: 1px solid #dcc8b6; border-radius: 6px; background: #fffdf9; color: var(--green); font-size: 12px; padding: 7px 10px; }
.target-sheet figcaption, .target-guide-tip { font-size: 12px; color: #5e6f7e; line-height: 1.9; margin: 12px 0 0; word-break: normal; overflow-wrap: break-word; }
.target-reference { display: flex; gap: 16px; align-items: center; margin: 16px 0; padding: 14px; background: #f8f5ef; border: 1px solid var(--border); border-radius: 10px; }
.target-reference img { width: 140px; max-height: 120px; object-fit: contain; background: #f5f8fa; border-radius: 5px; }
.target-reference figcaption { display: flex; flex-direction: column; gap: 6px; min-width: 0; font-size: 12px; line-height: 1.8; color: var(--muted); }
.target-reference strong { color: var(--ink); font-size: 13px; font-weight: 650; }
.target-narration { color: var(--ink); font-size: 15px; line-height: 2; margin: 20px 0; padding-left: 16px; border-left: 3px solid #d6b290; }
.subject-study svg { display: block; max-width: 320px; width: 100%; height: 260px; margin: 18px auto; }
.subject-study > p { color: var(--muted); }
.target-unrendered { padding: 14px 16px; border: 1px solid #e6d5b5; border-radius: 10px; background: #fff6e5; font-size: 13px; line-height: 1.9; }
.target-unrendered strong, .target-unrendered span { display: block; }
.target-unrendered span { font-size: 12px; color: #725d3d; margin-top: 4px; }
.target-legend-list > article { display: grid; grid-template-columns: 28px minmax(0,1fr); gap: 12px; padding: 14px 0; border-top: 1px solid var(--border); }
.target-legend-list > article:first-child { border: 0; padding-top: 0; }
.target-legend-list b { display: grid; place-items: center; height: 28px; font-size: 12px; background: #ede4d7; color: #79553b; border-radius: 8px; }
.target-legend-list strong { color: var(--ink); font-size: 14px; font-weight: 650; }
.target-legend-list p { margin: 4px 0 7px; font-size: 13px; color: var(--muted); line-height: 1.9; }
.target-legend-list small { display: inline-block; padding: 2px 7px; border: 1px solid #dfd6c9; border-radius: 4px; font-size: 11px; color: #796952; background: #f4efe7; }
.target-changes { border: 1px solid #e7d8c7; border-radius: 14px; margin: 24px 0; padding: 20px; background: #fffcf7; }
.target-changes article { overflow: hidden; border: 1px solid #e8dfd4; border-radius: 10px; margin-top: 12px; }
.change-row { display: grid; grid-template-columns: 104px minmax(0,1fr); gap: 16px; padding: 16px; background: #f6f3ee; }
.change-row + .change-row { border-top: 1px solid #e8dfd4; }
.change-row > span { align-self: start; display: inline-block; width: fit-content; padding: 3px 8px; border-radius: 5px; font-size: 12px; font-weight: 650; color: #5f5a53; background: #e9e5de; }
.change-row p { margin: 1px 0 0; color: var(--ink); font-size: 14px; line-height: 1.95; min-width: 0; }
.change-adjustment { background: #fcf0e5; border-left: 3px solid #be6435; padding-left: 13px; }
.change-adjustment > span { background: #f0d6bd; color: #843e21; }
.change-adjustment p { font-weight: 600; color: #743e27; }
.change-benefit { background: #f2f6ee; }
.change-benefit > span { background: #dfe8d7; color: #46603d; }
.change-benefit p { color: #43583b; }
.target-distance { padding: 18px 20px; margin: 20px 0; border: 1px solid #e7cfa2; border-left: 4px solid #be9245; border-radius: 12px; background: #fff7e8; }
.distance-label { display: block; font-size: 11px; color: #826228; font-weight: 650; letter-spacing: .04em; margin-bottom: 7px; }
.target-distance strong { font-size: 17px; color: #725021; font-weight: 700; }
.target-distance p { font-size: 14px; line-height: 1.95; color: #6b583d; margin: 8px 0 0; }
.target-limitations ul { padding-left: 19px; margin-bottom: 18px; }
.target-limitations li { padding: 5px 0; font-size: 13px; line-height: 1.9; }
.target-limitations li::marker { color: #ae8964; }
.report-save-status { display: block; font-size: 12px; color: var(--green); margin-top: 12px; }
button:focus-visible { outline: 2px solid var(--green); outline-offset: 3px; }
@media(max-width:600px) {
  .target-heading { flex-direction: column; gap: 10px; }
  .target-heading > span { margin-left: 44px; max-width: calc(100% - 44px); }
  .target-sheet { padding: 12px 8px; }
  .target-controls { gap: 10px; }
  .target-changes { padding: 16px 12px; }
  .change-row { grid-template-columns: minmax(0,1fr); gap: 8px; padding: 14px; }
  .change-adjustment { padding-left: 11px; }
  .target-reference img { width: 100px; }
  .target-reference { gap: 12px; padding: 12px; }
}
@media(max-width:360px) { .target-reference { flex-direction: column; align-items: flex-start; } }
</style>
