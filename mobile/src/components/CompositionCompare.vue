<script setup lang="ts">
import {computed,useId} from 'vue';
import type {TargetBoard} from '../types';
import {sourceLayout,detailPath,silhouetteLayers,outlinePath,silhouetteStrokePath,targetLayerPaint,thirdsGuide,unknownFrameRects} from '../target-board.mjs';
import {sceneColorTransform,lineartPaint,OBJECT_COLOR_VERSION} from '../scene-colors.mjs';
import {frameAspect} from '../composition-sketch.mjs';
import {compositionDifference} from '../composition-difference.mjs';
const props=withDefaults(defineProps<{board:TargetBoard;colors?:{url:string;contextUrl:string|null;aspect:number;version:string;background:string;fills:(string|null)[][]}|null;environment?:boolean;grid?:boolean;colored?:boolean}>(),{environment:true,grid:true,colored:true});
const id=useId(),width=720;
const difference=computed(()=>compositionDifference(props.board));
const frames=computed(()=>{
  const original=sourceLayout(props.board) as {aspect:number;layers:TargetBoard['layers']}|null;if(!original)return [];
  return [
    {name:'原始布局',source:true,aspect:original.aspect,layers:original.layers},
    {name:props.board.layout_mode==='source_preserving'?'保留原取景':'推荐构图',source:false,aspect:frameAspect(props.board.aspect),layers:props.board.layers},
  ].map((frame,index)=>({...frame,index,height:width/frame.aspect,
    layers:frame.layers.map((layer,i)=>({...layer,index:i})).filter(layer=>props.environment||layer.representation!=='context_lines').sort((a,b)=>a.depth-b.depth),
    transform:sceneColorTransform(props.board,frame.source),
    unknown:unknownFrameRects(props.board,frame.source),guides:thirdsGuide(width,width/frame.aspect)}));
});
const matchingColor=computed(()=>props.colors?.version===OBJECT_COLOR_VERSION&&Math.abs(props.colors.aspect/(props.board.source_photo_aspect||0)-1)<.02
  &&sceneColorTransform(props.board));
</script>
<template>
  <section class="composition-compare" aria-label="大幅构图前后对照">
    <div v-if="difference" class="comparison-summary" role="status"><strong>{{ difference.summary }}</strong><span>{{ difference.position }}</span></div>
    <div class="comparison-frames">
      <figure v-for="frame in frames" :key="frame.name" :data-comparison-frame="frame.source?'source':'target'">
        <figcaption><strong>{{ frame.name }}</strong><span>{{ frame.source?'同一组已提取轮廓，放回原图位置':'同一组轮廓，比较取景与主体占比' }}</span></figcaption>
        <svg :viewBox="`0 0 ${width} ${frame.height}`" role="img" :aria-label="`${frame.name}构图对照，非实拍效果`">
          <defs><clipPath :id="`${id}-${frame.index}`"><rect :width="width" :height="frame.height"/></clipPath><pattern :id="`${id}-${frame.index}-unknown`" width="9" height="9" patternUnits="userSpaceOnUse"><rect width="9" height="9" fill="#f3f3ef"/><path d="M0,9L9,0" stroke="#c7c9c4"/></pattern></defs>
          <rect :width="width" :height="frame.height" :fill="matchingColor?colors?.background:'#faf9f5'"/>
          <g :clip-path="`url(#${id}-${frame.index})`">
            <image v-if="environment&&matchingColor&&colors?.contextUrl&&frame.transform" data-environment-wash :href="colors.contextUrl" :x="frame.transform.x*width" :y="frame.transform.y*frame.height" :width="frame.transform.width*width" :height="frame.transform.height*frame.height" preserveAspectRatio="none"/>
            <image v-if="matchingColor&&colors&&frame.transform" :href="colors.url" :x="frame.transform.x*width" :y="frame.transform.y*frame.height" :width="frame.transform.width*width" :height="frame.transform.height*frame.height" preserveAspectRatio="none"/>
            <g v-for="layer in frame.layers" :key="layer.index" fill="none" :stroke="lineartPaint(layer).stroke" :opacity="lineartPaint(layer).opacity" stroke-linecap="round" stroke-linejoin="round">
              <path v-for="(part,i) in silhouetteLayers(layer)" :key="`fill-${i}`" :d="outlinePath(part,width,frame.height)" fill-rule="evenodd" :fill="matchingColor?'none':targetLayerPaint(layer,colored).fill" stroke="none"/>
              <path v-for="(part,i) in silhouetteLayers(layer)" :key="`line-${i}`" :d="silhouetteStrokePath(part,width,frame.height)" :stroke-dasharray="!layer.photo_boundary?'4 3':undefined" stroke-width="1.2" vector-effect="non-scaling-stroke"/>
              <path v-for="(path,i) in layer.details" :key="`detail-${i}`" :d="detailPath(layer,path,width,frame.height)" :opacity="layer.representation==='scene_structure'?.85:lineartPaint(layer).detailOpacity" :stroke-width="layer.representation==='scene_structure'?1.2:.8" vector-effect="non-scaling-stroke"/>
            </g>
            <rect v-for="(rect,i) in frame.unknown" :key="i" :x="rect[0]*width" :y="rect[1]*frame.height" :width="rect[2]*width" :height="rect[3]*frame.height" :fill="`url(#${id}-${frame.index}-unknown)`"/>
          </g>
          <g v-if="grid" fill="none" stroke="#59758b" stroke-dasharray="6 7" opacity=".75" pointer-events="none"><line v-for="(line,i) in frame.guides.lines" :key="i" :x1="line[0]" :y1="line[1]" :x2="line[2]" :y2="line[3]" stroke-width="1" vector-effect="non-scaling-stroke"/></g>
        </svg>
      </figure>
    </div>
    <p>{{ !colored?'纯线稿模式。':matchingColor?'轮廓内按原图分区取色，颜色适度提亮；环境仅作模糊淡色参考，不是物体分割。':'当前为示意色，尚未读取到匹配原图的颜色。' }}对照图不是实拍效果。</p>
  </section>
</template>
<style scoped>
.composition-compare {min-width:0;margin:16px 0 24px}
.comparison-summary {display:flex;flex-direction:column;gap:6px;padding:16px 18px;border-left:3px solid var(--coral);background:#fbf1e8;margin-bottom:16px;line-height:1.7}
.comparison-summary strong {font-size:17px;color:var(--ink)}
.comparison-summary span {font-size:13px;color:var(--muted)}
.comparison-frames {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:start}
figure {min-width:0;margin:0;padding:12px;border:1px solid var(--border);border-radius:12px;background:#fffefa}
figure[data-comparison-frame=target] {border-color:#cba27c}
figcaption {display:flex;flex-direction:column;gap:4px;padding:3px 2px 12px;line-height:1.7}
figcaption strong {font-size:16px;color:var(--ink)}
figcaption span,p {font-size:12px;color:var(--muted)}
svg {display:block;width:100%;height:auto;border:1px solid #c4cbd0}
p {line-height:1.8;margin:12px 0 0}
@media(max-width:700px) {.comparison-frames {grid-template-columns:minmax(0,1fr);gap:16px}.comparison-summary{padding:13px}.comparison-summary strong{font-size:16px}figure{padding:10px}}
</style>
