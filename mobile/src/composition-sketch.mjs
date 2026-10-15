const kinds = new Set(['person', 'tree', 'pet', 'building', 'mountain', 'flower', 'object']);
const moves = new Set(['stay', 'left', 'right', 'closer', 'farther', 'lower', 'higher']);
const appearances = new Set(['default', 'standing', 'seated', 'walking', 'cat', 'dog', 'bird',
  'red_panda', 'pine', 'broadleaf', 'cup', 'bottle', 'book', 'camera']);

export function frameAspect(aspect) {
  return {portrait:3/4,landscape:4/3,square:1}[aspect] || 1;
}

/** Validate stored or older responses before using model coordinates in a drawing. */
export function usableSketch(value) {
  if (!value || !['portrait', 'landscape', 'square'].includes(value.aspect)
      || !moves.has(value.camera_action) || typeof value.caption !== 'string'
      || typeof value.camera_instruction !== 'string' || !Array.isArray(value.elements)
      || value.elements.length > 6) return null;
  if (value.render_mode != null && !['scene','subject'].includes(value.render_mode)) return null;
  if (value.space_side != null && !['left','right','top','bottom','none'].includes(value.space_side)) return null;
  if (value.source_margin != null && (typeof value.source_margin !== 'number'
      || !Number.isFinite(value.source_margin) || value.source_margin < 0 || value.source_margin > .05)) return null;
  if (value.photo_aspect != null && (typeof value.photo_aspect !== 'number'
      || !Number.isFinite(value.photo_aspect) || value.photo_aspect <= 0)) return null;
  for (const [key, max] of Object.entries({ theme: 40, mood: 40, narration: 160, space_note: 100 })) {
    if (value[key] != null && (typeof value[key] !== 'string' || value[key].length > max)) return null;
  }
  if (value.horizon_y != null && (typeof value.horizon_y !== 'number'
      || !Number.isFinite(value.horizon_y) || value.horizon_y < 0 || value.horizon_y > 1)) return null;
  for (const item of value.elements) {
    const b = item?.bbox;
    if ((item?.appearance != null && !appearances.has(item.appearance))
        || (item?.facing != null && !['front', 'left', 'right'].includes(item.facing))
        || (item?.description != null && (typeof item.description !== 'string'
          || item.description.length > 70))) return null;
    if (item?.source_bbox != null && (!Array.isArray(item.source_bbox) || item.source_bbox.length !== 4
        || !item.source_bbox.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1)
        || item.source_bbox[2]-item.source_bbox[0] < .05 || item.source_bbox[3]-item.source_bbox[1] < .05)) return null;
    if (item?.identity_features != null && (!Array.isArray(item.identity_features)
        || item.identity_features.length > 6 || item.identity_features.some(s => typeof s !== 'string'
          || !s.trim() || s.length > 50))) return null;
    if (!kinds.has(item?.kind) || !['main', 'context'].includes(item?.role)
        || typeof item?.label !== 'string' || !item.label.trim() || item.label.length > 18
        || !Array.isArray(b) || b.length !== 4
        || !b.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1)
        || b[2] - b[0] < .05 || b[3] - b[1] < .05) return null;
  }
  return value.render_mode === 'scene' || value.elements.some(item => item.role === 'main') ? value : null;
}

export function usableFramingPlan(value) {
  const keys = ['diagnosis','visual_priority','placement','scale','negative_space',
    'edge_check','background_control','success_check'];
  return value && keys.every(key => typeof value[key] === 'string'
    && value[key].trim() && value[key].length <= 180) ? value : null;
}

export function cameraMove(action) {
  const map = {
    stay: { x: 170, y: 136, startX: 170, startY: 136, label: '先保持机位' },
    left: { x: 90, y: 136, startX: 170, startY: 136, label: '向左调整' },
    right: { x: 250, y: 136, startX: 170, startY: 136, label: '向右调整' },
    closer: { x: 170, y: 105, startX: 170, startY: 157, label: '靠近一些' },
    farther: { x: 170, y: 157, startX: 170, startY: 105, label: '后退一些' },
    lower: { x: 90, y: 145, startX: 90, startY: 95, label: '降低机位' },
    higher: { x: 90, y: 85, startX: 90, startY: 145, label: '抬高机位' },
  };
  return map[action] || map.stay;
}

const spaceLabels = {left:'左侧',right:'右侧',top:'上方',bottom:'下方'};
const emptySpace = () => ({x:0,y:0,w:0,h:0,side:'none',label:'未标记留白'});

/** Old responses may name one side; ambiguous notes must never choose a side for the user. */
export function sketchSpaceSide(sketch) {
  if (sketch.space_side != null) return sketch.space_side;
  const note = sketch.space_note || '';
  if (/上下|左右|两侧|四周|四边|周围/.test(note)) return 'none';
  const matches = [
    ['left',/(左侧|左方|左边|画面左)/],['right',/(右侧|右方|右边|画面右)/],
    ['top',/(上方|上侧|上边|顶部)/],['bottom',/(下方|下侧|下边|底部)/],
  ].filter(([,pattern]) => pattern.test(note));
  return matches.length === 1 ? matches[0][0] : 'none';
}

/** Keep connected structures intact, including older responses that omitted render_mode. */
export function sketchRenderMode(sketch, {extraMargin = false} = {}) {
  const mains = sketch.elements.filter(item => item.role === 'main');
  if (sketch.render_mode === 'scene' || mains.length !== 1 || !mains[0].source_bbox
      || sketch.elements.some(item => ['building','mountain'].includes(item.kind)
        || /瀑布|倒影|waterfall|reflection/i.test(`${item.label} ${item.description || ''}`))) return 'scene';
  const main = mains[0];
  const margin = (sketch.source_margin ?? .02) + (extraMargin ? .04 : 0);
  const regions = sketch.elements.filter(item=>item.source_bbox && !embeddedInMain(item,main))
    .map(item=>expandedSourceBox(item.source_bbox,margin));
  if (regions.some((a,index)=>regions.slice(index+1).some(b=>Math.min(a[2],b[2]) > Math.max(a[0],b[0])
    && Math.min(a[3],b[3]) > Math.max(a[1],b[1])))) return 'scene';
  return 'subject';
}

/** Explicit tracing jobs are shared by the Vue view and offline visual regression tools. */
export function traceRequests(sketch, {extraMargin = false} = {}) {
  if (sketchRenderMode(sketch,{extraMargin}) === 'scene') return [{key:'scene',sourceBox:null}];
  const main = sketch.elements.find(item => item.role === 'main');
  const margin = (sketch.source_margin ?? .02) + (extraMargin ? .04 : 0);
  return sketch.elements.flatMap((element,index) => !element.source_bbox || embeddedInMain(element,main)
    ? [] : [{key:index,sourceBox:expandedSourceBox(element.source_bbox,margin)}]);
}

/** Mark only the requested side of the actual main region; never substitute a larger side. */
export function openSpace(elements, side = 'none', obstacles = []) {
  if (!elements.length || !(side in spaceLabels)) return emptySpace();
  const boxes = elements.map(item => item.drawnBox || item.bbox);
  const left = Math.min(...boxes.map(b=>b[0])), top = Math.min(...boxes.map(b=>b[1]));
  const right = Math.max(...boxes.map(b=>b[2])), bottom = Math.max(...boxes.map(b=>b[3]));
  const strips = {
    left:{x:0,y:0,w:left,h:1}, right:{x:right,y:0,w:1-right,h:1},
    top:{x:0,y:0,w:1,h:top}, bottom:{x:0,y:bottom,w:1,h:1-bottom},
  };
  let areas = [strips[side]];
  for (const item of obstacles) {
    const [x1,y1,x2,y2] = item.drawnBox || item.bbox;
    areas = areas.flatMap(a => {
      const l = Math.max(a.x, x1), r = Math.min(a.x + a.w, x2);
      const t = Math.max(a.y, y1), b = Math.min(a.y + a.h, y2);
      if (l >= r || t >= b) return [a];
      return [
        { x: a.x, y: a.y, w: l - a.x, h: a.h },
        { x: r, y: a.y, w: a.x + a.w - r, h: a.h },
        { x: a.x, y: a.y, w: a.w, h: t - a.y },
        { x: a.x, y: b, w: a.w, h: a.y + a.h - b },
      ].filter(s => s.w > .01 && s.h > .01);
    }).sort((a,b) => b.w*b.h-a.w*a.h).slice(0, 128);
  }
  const best = areas.sort((a,b)=>b.w*b.h-a.w*a.h).find(a=>a.w >= .06 && a.h >= .06 && a.w*a.h >= .04);
  return best ? {...best,side,label:`${spaceLabels[side]}留白`} : emptySpace();
}
import { expandedSourceBox, fitPhotoBox, embeddedInMain } from './sketch-trace.mjs';


/** One geometry source for the drawing, percentages, edge margins, and negative-space labels. */
export function sketchLayout(sketch, traces = {}, {photoAspect = null,extraMargin = false} = {}) {
  const mode = sketchRenderMode(sketch,{extraMargin}), fullTrace = traces.scene;
  const nativeAspect = fullTrace?.aspect || photoAspect || sketch.photo_aspect || frameAspect(sketch.aspect);
  const aspect = mode === 'scene' ? nativeAspect : frameAspect(sketch.aspect);
  const subject = sketch.elements.find(item => item.role === 'main');
  const margin = (sketch.source_margin ?? .02) + (extraMargin ? .04 : 0);
  const items = sketch.elements.map((element,index) => {
    const trace = mode === 'subject' ? traces[index] : null;
    const crop = expandedSourceBox(element.source_bbox,margin);
    const cropAspect = crop ? (crop[2]-crop[0])*nativeAspect/(crop[3]-crop[1]) : 0;
    const drawnBox = mode === 'scene' ? element.source_bbox || null
      : fitPhotoBox(element.bbox,trace?.aspect || cropAspect,aspect);
    const embedded = mode === 'subject' && embeddedInMain(element,subject);
    return {...element,index,trace,drawnBox,embedded,
      visible:!embedded && !!drawnBox && (mode === 'scene' || !!trace)};
  });
  // Background first, subject second; model array order cannot cover a subject with an environment layer.
  const layers = items.filter(item=>item.visible)
    .sort((a,b)=>Number(a.role === 'main')-Number(b.role === 'main') || a.index-b.index);
  const main = items.find(item=>item.role === 'main');
  const mainBoxes = items.filter(item=>item.role === 'main' && item.drawnBox);
  const space = mode === 'scene' || !mainBoxes.every(item=>item.visible) ? emptySpace() : openSpace(mainBoxes,sketchSpaceSide(sketch),
    layers.filter(item=>item.role === 'context'));
  const boxes = mainBoxes.map(item=>item.drawnBox);
  const box = boxes.length ? [Math.min(...boxes.map(b=>b[0])),Math.min(...boxes.map(b=>b[1])),
    Math.max(...boxes.map(b=>b[2])),Math.max(...boxes.map(b=>b[3]))] : null;
  const cellNames = ['左上','上方中间','右上','左侧中间','中央','右侧中间','左下','下方中间','右下'];
  const placement = box ? {
    cell:cellNames[Math.min(2,Math.floor((box[1]+box[3])/2*3))*3+Math.min(2,Math.floor((box[0]+box[2])/2*3))],
    width:Math.round((box[2]-box[0])*100),height:Math.round((box[3]-box[1])*100),
    left:Math.round(box[0]*100),right:Math.round((1-box[2])*100),
    top:Math.round(box[1]*100),bottom:Math.round((1-box[3])*100),
  } : null;
  return {mode,aspect,items,layers,main,space,placement,fullTrace};
}

/** Read the live drawing after a margin toggle or trace update, including old records. */
export function layoutCaption(layout) {
  if (layout.mode === 'scene') return '整体保留原图的透视与位置；机位调整后的取景以现场为准。';
  const p = layout.placement;
  if (!p) return '对照原照片检查主体完整性与四边余量。';
  return `轮廓取材区域宽约${p.width}%、高约${p.height}%；${layout.space.side === 'none' ? '检查四边余量' : layout.space.label + '保留画面余量'}。`;
}
