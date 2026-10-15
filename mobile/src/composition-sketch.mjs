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
      || !value.elements.length || value.elements.length > 6) return null;
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
  return value.elements.some(item => item.role === 'main') ? value : null;
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

/** Find an open rectangle without painting over the subject or visible context. */
export function openSpace(elements) {
  let areas = [{ x: 0, y: 0, w: 1, h: 1 }];
  for (const { bbox: [x1, y1, x2, y2] } of elements) {
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
  const best = areas[0] || { x: 0, y: 0, w: 0, h: 0 };
  const side = best.w > best.h ? (best.y < .5 ? '上方' : '下方') : (best.x < .5 ? '左侧' : '右侧');
  return { ...best, label: `${side}留白` };
}
