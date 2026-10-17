<script setup lang="ts">
import { computed,ref,watch } from 'vue';
import type { TargetBoard } from '../types';
import { DEFAULT_TARGET_COLOR, DEFAULT_TARGET_GRID, detailPath, outlinePath, sourceLayout, silhouetteLayers, targetLayerPaint, thirdsGuide } from '../target-board.mjs';
import { frameAspect } from '../composition-sketch.mjs';
const props=defineProps<{board:TargetBoard;reference?:string}>();
const sheet=ref<SVGSVGElement>();
const grid=ref(DEFAULT_TARGET_GRID),labels=ref(true),color=ref(DEFAULT_TARGET_COLOR),environment=ref(true),saved=ref(''),showSource=ref(false);
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
const main=computed(()=>props.board.layers.find(layer=>layer.role==='main')!);
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
    <div class="target-heading"><h3>{{ board.intent }}</h3><span>{{ showSource?'原始布局估计':'推荐构图线稿' }}</span></div>
    <div v-if="original" class="target-mode" role="group" aria-label="轮廓布局对照"><button type="button" :aria-pressed="!showSource" @click="showSource=false">推荐布局</button><button type="button" :aria-pressed="showSource" @click="showSource=true">原始物体布局</button></div>
    <figure class="target-sheet">
      <svg ref="sheet" :viewBox="`-18 -18 ${width+36} ${height+36}`" role="img" :aria-label="showSource?'原始物体布局估计，用于核对轮廓与空间位置':`推荐构图：${board.intent}。使用物体轮廓表达目标布局，不是实拍预测。`" font-family="sans-serif">
        <title>{{ showSource?'原始物体布局估计':board.intent }}</title><desc>物体识别和轮廓提取可能有误，请对照原图。推荐布局不是新机位的透视、遮挡或实拍效果预测。{{ color?'淡彩为示意配色，不代表原图实际颜色。':'' }}</desc>
        <rect x="-18" y="-18" :width="width+36" :height="height+36" fill="#fafcfd"/>
        <rect :width="width" :height="height" :fill="color?'#f5f8f6':'#fff'" stroke="#a5b4c5" stroke-width="1"/>
        <g v-for="layer in visibleLayers" :key="layer.index" :data-representation="layer.representation||'silhouette'" :stroke="targetLayerPaint(layer,color).stroke" stroke-linecap="round" stroke-linejoin="round">
          <path v-for="(part,index) in silhouetteLayers(layer)" :key="`shape-${index}`" :d="outlinePath(part,width,height)" :fill="targetLayerPaint(layer,color).fill" :fill-opacity="targetLayerPaint(layer,color).fillOpacity" :stroke="layer.kind==='background' ? 'none' : undefined" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
          <path v-for="(path,index) in layer.details" :key="`detail-${index}`" class="subject-detail" :d="detailPath(layer,path,width,height)" fill="none" :stroke-width="layer.representation==='context_lines' ? (color?1.1:.85) : layer.details.length>10 ? .72 : 1.1" vector-effect="non-scaling-stroke"/>
        </g>
        <g v-if="grid" data-thirds-guide role="group" aria-label="三分线与四个交点，作为构图位置参考" pointer-events="none">
          <line v-for="(line,index) in guides.lines" :key="`guide-${index}`" :x1="line[0]" :y1="line[1]" :x2="line[2]" :y2="line[3]" stroke="#607e94" stroke-width="1.1" opacity=".8" stroke-dasharray="6 7" vector-effect="non-scaling-stroke"/>
          <circle v-for="(point,index) in guides.points" :key="`point-${index}`" :cx="point[0]" :cy="point[1]" r="4.5" :fill="color?'#fff3d5':'#fff'" :stroke="color?'#a77d36':'#607e94'" stroke-width="1.3" vector-effect="non-scaling-stroke"/>
        </g>
        <g v-if="labels" font-size="16" text-anchor="middle">
          <g v-for="layer in visibleMarks" :key="layer.index"><circle :cx="layer.bbox[0]!*width+14" :cy="layer.bbox[1]!*height+14" r="12" :fill="layer.role==='main' ? '#315b9c' : '#8094a6'"/><text :x="layer.bbox[0]!*width+14" :y="layer.bbox[1]!*height+20" fill="white">{{ layer.index+1 }}</text></g>
        </g>
      </svg>
      <div class="target-controls"><label><input v-model="environment" type="checkbox"/>环境线索</label><label><input v-model="grid" type="checkbox"/>三分线</label><label><input v-model="labels" type="checkbox"/>景物标记</label><label><input v-model="color" type="checkbox"/>淡彩</label><button type="button" @click="save">{{ showSource?'保存原始布局':'保存推荐图' }}</button></div>
      <figcaption>{{ showSource?'同一组物体轮廓放回原图位置，用于核对物体形状与空间关系；不代表精确分割。':`以第 ${board.reference_photo_id.slice(5)} 张为参考规划；主体目标占比：宽 ${size.w}%、高 ${size.h}%。这是构图示意，不是实拍预测。` }}<span v-if="color"> 淡彩仅作示意配色。</span></figcaption>
      <p v-if="grid" class="target-guide-tip">两横两竖将画面分为九格，圆点标出四个交点，方便比较主体位置；不必强行把主体放在交点上。</p>
    </figure>
    <figure v-if="reference" class="target-reference">
      <img :src="reference" :alt="`第 ${board.reference_photo_id.slice(5)} 张原图，用于核对物体外形`"/>
      <figcaption><strong>形态对照 · 第 {{ board.reference_photo_id.slice(5) }} 张原图</strong><span>对照主体外形和可见细节；上方是取景示意，不是实际拍摄效果。</span></figcaption>
    </figure>
    <p v-if="board.narration" class="target-narration">{{ board.narration }}</p>
    <details class="subject-study" open><summary>放大看主体细节 · {{ main.label }}</summary>
      <svg :viewBox="`-8 -8 ${portrait.w+16} ${portrait.h+16}`" role="img" :aria-label="`${main.label}的推荐形象与结构线条`" stroke="#415970" stroke-linecap="round" stroke-linejoin="round">
        <path v-for="(part,index) in silhouetteLayers(portrait.layer)" :key="index" :d="outlinePath(part,portrait.w,portrait.h)" :fill="targetLayerPaint(main,color).fill" :fill-opacity="targetLayerPaint(main,color).fillOpacity" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
        <path v-for="(path,index) in main.details" :key="`detail-${index}`" class="subject-detail" :d="detailPath(portrait.layer,path,portrait.w,portrait.h)" fill="none" :stroke-width="main.details.length>10 ? .9 : 1.1" vector-effect="non-scaling-stroke"/>
      </svg><p>{{ main.identity_features.join('、') }}。新机位下的形态仍需现场核对。</p>
    </details>
    <div class="target-legend"><p v-for="(layer,index) in board.layers" :key="index"><b>{{ layer.kind==='background' ? '背景' : index+1 }}</b><strong>{{ layer.label }}</strong><span>{{ layer.identity_features?.join('、') }}</span><small>{{ layer.certainty==='approximate' ? '视角近似，需试拍' : '特征依据参考照片' }}</small></p></div>
    <div class="target-changes"><h4>比原图改善在哪里</h4><article v-for="(change,index) in board.changes" :key="index"><p><span>原图问题</span>{{ change.problem }}</p><p><span>推荐调整</span>{{ change.adjustment }}</p><p><span>预期改善</span>{{ change.benefit }}</p></article></div>
    <div class="target-distance"><strong>{{ distanceNames[board.distance_relation] }}</strong><p>{{ board.distance_instruction }}</p></div>
    <p v-for="note in board.limitations" :key="note" class="target-limit">{{ note }}</p><span role="status">{{ saved }}</span>
  </div>
</template>
<style scoped>
.target-guide-tip{margin:8px 0 0;font-size:12px;line-height:1.9;color:#59718a;word-break:normal;overflow-wrap:break-word}
.target-mode{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.target-mode button{border:1px solid #c8d4e0;border-radius:5px;background:#fff;color:#58718a;padding:9px 14px;font-size:13px}.target-mode button[aria-pressed=true]{background:#315b9c;color:#fff;border-color:#315b9c}.target-composition{min-width:0;word-break:normal;overflow-wrap:break-word}.target-changes p{min-width:0}
.target-reference{display:flex;gap:16px;align-items:center;margin:16px 0;padding-bottom:16px;border-bottom:1px solid #e1e8ef}.target-reference img{width:140px;max-height:120px;object-fit:contain;background:#f5f8fa}.target-reference figcaption{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:12px;line-height:1.8;color:#71849b;overflow-wrap:break-word;word-break:normal}.target-reference strong{color:#435d76;font-weight:500}@media(max-width:400px){.target-reference img{width:100px}.target-reference{gap:12px}}
.target-narration{font-family:"Songti SC","SimSun",serif;color:#59718a;font-size:16px;line-height:2;margin:20px 12px}.subject-study{margin:20px 0;padding:12px 0;border-bottom:1px solid #e1e8ef;color:#627e98;font-size:12px}.subject-study summary{cursor:pointer}.subject-study svg{display:block;max-width:320px;width:100%;height:260px;margin:18px auto}.subject-study p{font-size:12px;line-height:1.9;color:#74879b}
.target-heading{display:flex;align-items:baseline;gap:16px;justify-content:space-between;margin:26px 0 16px}.target-heading h3{font-family:"Songti SC","SimSun",serif;font-size:23px;font-weight:400;color:#304962;margin:0;line-height:1.7}.target-heading>span{font-size:11px;color:#71849b;white-space:nowrap}.target-sheet{margin:0;padding:18px;background:#fafcfd;border:1px solid #e0e7ee}.target-sheet svg{display:block;width:100%;max-height:520px}.target-controls{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding-top:14px;margin-top:12px;border-top:1px solid #e1e8ef}.target-controls label{display:flex;gap:4px;align-items:center;font-size:12px;color:#687f95}.target-controls input{accent-color:#315b9c}.target-controls button{margin-left:auto;border:0;background:transparent;color:#315b9c;font-size:12px;padding:8px 0}.target-sheet figcaption{font-size:12px;color:#71849b;line-height:1.9;margin-top:12px}.target-legend{margin:18px 0}.target-legend p{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;font-size:12px;margin:9px 0;line-height:1.8}.target-legend b{color:#315b9c}.target-legend span,.target-legend small{color:#74879b}.target-changes{border-top:1px solid #dfe7ef;margin-top:24px;padding-top:8px}.target-changes h4{font-size:15px;font-weight:500;color:#355675}.target-changes article{padding:8px 0 14px;border-bottom:1px solid #e4eaf0}.target-changes p{display:grid;grid-template-columns:68px 1fr;gap:12px;font-size:13px;line-height:1.9;margin:7px 0;color:#435d76}.target-changes p span{font-size:11px;color:#7b8da0;padding-top:2px}.target-distance{border-left:2px solid #89a9c9;padding:6px 16px;margin:24px 0}.target-distance strong{font-size:14px;color:#365b80;font-weight:500}.target-distance p{font-size:13px;line-height:1.9;color:#58718a;margin:5px 0}.target-limit{font-size:11px;line-height:1.9;color:#8392a3}.target-composition>[role=status]{font-size:12px;color:#315b9c}button:focus-visible{outline:2px solid #315b9c;outline-offset:3px}@media(max-width:600px){.target-heading{align-items:flex-start;flex-direction:column;gap:3px}.target-sheet{padding:12px 8px}.target-heading h3{font-size:22px}}
</style>
