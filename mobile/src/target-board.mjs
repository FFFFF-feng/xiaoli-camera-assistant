const roles=new Set(['main','foreground','background','prop']);
const colors=new Set(['slate','blue','ochre','sage','rose']);
const point=p=>Array.isArray(p)&&p.length===2&&p.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1);
const points=(p,min)=>Array.isArray(p)&&p.length>=min&&p.length<=64&&p.every(point);
const text=(s,n)=>typeof s==='string'&&s.trim().length>0&&s.length<=n;
const photo=s=>typeof s==='string'&&/^photo[1-6]$/.test(s);
export const openStructure=layer=>['context_lines','scene_structure'].includes(layer?.representation);

// Illustrative tints, not sampled or reconstructed photo colors. No geometry
// changes: open environmental strokes must never become filled polygons.
export const DEFAULT_TARGET_COLOR=true;
export const DEFAULT_TARGET_GRID=true;
export function thirdsGuide(width,height) {
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw new RangeError('无效画幅');
  return {lines:[[width/3,0,width/3,height],[width*2/3,0,width*2/3,height],
    [0,height/3,width,height/3],[0,height*2/3,width,height*2/3]],
    points:[[width/3,height/3],[width*2/3,height/3],[width/3,height*2/3],[width*2/3,height*2/3]]};
}
const tints={slate:'#c7d4df',blue:'#bcd9e9',ochre:'#e7c38d',sage:'#c2d9b4',rose:'#e8b5b9'};
export function targetLayerPaint(layer,colored=DEFAULT_TARGET_COLOR) {
  const context=openStructure(layer);
  const structure=layer.representation==='scene_structure';
  if(!colored)return {fill:context?'none':'#fff',fillOpacity:context?0:1,
    stroke:structure?'#415970':context?(layer.role==='foreground'?'#71859a':'#96a5b4'):'#415970'};
  const botanical=['tree','branch','tree_branch','leaf','plant'].includes(layer.kind);
  const architecture=['building','tower','wall'].includes(layer.kind);
  const neutral=!layer.color||layer.color==='slate';
  const fill=neutral&&layer.kind==='flower'?'#ead9ae':neutral&&botanical?tints.sage:tints[layer.color]||tints.slate;
  return {fill:context?'none':fill,fillOpacity:context?0:layer.role==='background'?.42:.82,
    stroke:structure?'#415970':context?(botanical?'#4f7b56':architecture?'#967241':'#638697'):'#415970'};
}

export function simpleOutline(points) {
  const ring=points[0].every((v,k)=>v===points.at(-1)[k])?points.slice(0,-1):points;
  if(ring.length<3||new Set(ring.map(p=>p.join(','))).size!==ring.length)return false;
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-10&&[0,1].every(k=>p[k]>=Math.min(a[k],b[k])-1e-10&&p[k]<=Math.max(a[k],b[k])+1e-10);
  for(let i=0;i<ring.length;i++) {
    const a=ring[i],b=ring[(i+1)%ring.length],next=ring[(i+2)%ring.length];
    if(on(a,b,next)||on(b,next,a))return false;
    for(let j=i+1;j<ring.length;j++) {
      if(j===i+1||(i===0&&j===ring.length-1))continue;
      const c=ring[j],d=ring[(j+1)%ring.length];
      if(on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b)
        ||(cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0))return false;
    }
  }
  return true;
}

const openRing=path=>path[0].every((v,k)=>v===path.at(-1)[k])?path.slice(0,-1):path;
function ringsTouch(first,second) {
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-10&&[0,1].every(k=>p[k]>=Math.min(a[k],b[k])-1e-10&&p[k]<=Math.max(a[k],b[k])+1e-10);
  const a=openRing(first),b=openRing(second);
  return a.some((p,i)=>b.some((q,j)=>{
    const r=a[(i+1)%a.length],s=b[(j+1)%b.length];
    return on(p,r,q)||on(p,r,s)||on(q,s,p)||on(q,s,r)
      ||(cross(p,r,q)*cross(p,r,s)<0&&cross(q,s,p)*cross(q,s,r)<0);
  }));
}
function insideRing(point,path) {
  const ring=openRing(path);let inside=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++) {
    const a=ring[i],b=ring[j];
    if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;
  }
  return inside;
}
const ringContains=(outer,inner)=>inner.every(p=>insideRing(p,outer))&&!ringsTouch(outer,inner);

export function usableTargetBoard(value) {
  if(!value||!['portrait','landscape','square'].includes(value.aspect)||!photo(value.reference_photo_id)
    ||!text(value.intent,100)||!text(value.distance_instruction,160)
    ||(value.narration!==undefined&&(typeof value.narration!=='string'||value.narration.length>160))
    ||!['closer','farther','similar','unknown'].includes(value.distance_relation)
    ||!Array.isArray(value.layers)||!value.layers.length||value.layers.length>6
    ||!Array.isArray(value.changes)||!value.changes.length||value.changes.length>3
    ||!Array.isArray(value.limitations)||!value.limitations.length||value.limitations.length>5
    ||!value.limitations.every(s=>text(s,500)))return null;
  if(value.render_basis!==undefined&&!['legacy','source_geometry'].includes(value.render_basis))return null;
  if(value.layout_mode!==undefined&&!['schematic','crop_projection','source_preserving'].includes(value.layout_mode))return null;
  if(value.layout_mode==='source_preserving'&&(value.render_basis!=='source_geometry'
    ||!value.layers.some(layer=>layer?.representation==='scene_structure')))return null;
  if(value.render_basis==='source_geometry'&&(
    typeof value.source_photo_aspect!=='number'||!Number.isFinite(value.source_photo_aspect)
    ||value.source_photo_aspect<=0||value.source_photo_aspect>100))return null;
  const sourceIds=new Set();
  for(const layer of value.layers) {
    const b=layer?.bbox;
    const context=layer?.representation==='context_lines',structure=layer?.representation==='scene_structure';
    const open=context||structure;
    if(!text(layer?.label,30)||!text(layer.kind,30)||!roles.has(layer.role)||!colors.has(layer.color)
      ||(layer.kind==='background'&&layer.role!=='background')
      ||!Number.isInteger(layer.depth)||layer.depth<0||layer.depth>9
      ||!Array.isArray(b)||b.length!==4||!point(b.slice(0,2))||!point(b.slice(2))
      ||b[2]-b[0]<.005||b[3]-b[1]<.005
      ||(layer.representation!==undefined&&!['silhouette','context_lines','scene_structure'].includes(layer.representation))
      ||(open ? (!Array.isArray(layer.outline)||layer.outline.length!==0||(context&&layer.role==='main')) : !points(layer.outline,3))
      ||(structure&&value.render_basis!=='source_geometry')
      ||(layer.outline_style!==undefined&&!['angular','curved'].includes(layer.outline_style))
      ||!Array.isArray(layer.details)||layer.details.length>96||!layer.details.every(p=>points(p,2))
      ||!Array.isArray(layer.evidence_photo_ids)||!layer.evidence_photo_ids.length
      ||layer.evidence_photo_ids.length>6||!layer.evidence_photo_ids.every(photo)
      ||!Array.isArray(layer.identity_features)||layer.identity_features.length>6
      ||!layer.identity_features.every(s=>text(s,160))
      ||!['observed','approximate'].includes(layer.certainty))return null;
    const p=layer.outline;
    const area=Math.abs(p.reduce((a,v,i)=>{const n=p[(i+1)%p.length];return a+v[0]*n[1]-n[0]*v[1]},0))/2;
    if(!open&&(area<.01||!simpleOutline(p)))return null;
    if(open&&(!layer.details.length||layer.contours?.length))return null;
    if(layer.source_details!==undefined&&layer.source_details!==null&&(
      !Array.isArray(layer.source_details)||layer.source_details.length>96||!layer.source_details.every(p=>points(p,2))))return null;
    if(layer.contours!==undefined&&(!Array.isArray(layer.contours)||layer.contours.length>12
      ||!layer.contours.every(path=>points(path,3)&&simpleOutline(path))))return null;
    if(layer.holes!==undefined&&(!Array.isArray(layer.holes)||layer.holes.length>12
      ||!layer.holes.every(path=>points(path,3)&&simpleOutline(path))))return null;
    if(layer.holes?.length) {
      if(open)return null;
      const outlines=layer.contours?.length?layer.contours:[layer.outline];
      if(!layer.holes.every(hole=>outlines.filter(outline=>ringContains(outline,hole)).length===1))return null;
      if(layer.holes.some((hole,i)=>layer.holes.slice(i+1).some(other=>ringsTouch(hole,other)
        ||insideRing(hole[0],other)||insideRing(other[0],hole))))return null;
    }
    if(value.render_basis==='source_geometry') {
      if(open&&(!Array.isArray(layer.source_details)||!layer.source_details.length))return null;
      const b=layer.source_bbox;
      if(!/^object[1-6]$/.test(layer.source_object_id)||sourceIds.has(layer.source_object_id)
        ||!Array.isArray(b)||b.length!==4||!point(b.slice(0,2))||!point(b.slice(2))
        ||b[2]-b[0]<.005||b[3]-b[1]<.005
        ||!['fixed','movable','unknown'].includes(layer.mobility))return null;
      sourceIds.add(layer.source_object_id);
    }
  }
  if(!value.layers.some(l=>l.role==='main')||!value.changes.every(c=>text(c?.problem,140)
    &&text(c?.adjustment,140)&&text(c?.benefit,140)))return null;
  return value;
}

// The very same paths render at observed positions for comparison. This is
// estimated object geometry, not an original-photo edge filter.
export function sourceLayout(board) {
  if(!usableTargetBoard(board)||board.render_basis!=='source_geometry')return null;
  return {aspect:board.source_photo_aspect,
    layers:board.layers.map(layer=>({...layer,bbox:[...layer.source_bbox],
      details:openStructure(layer)?layer.source_details:layer.details}))};
}

export function projectedPoints(layer, path, width, height) {
  const [x1,y1,x2,y2]=layer.bbox;
  return path.map(([x,y])=>`${((x1+x*(x2-x1))*width).toFixed(2)},${((y1+y*(y2-y1))*height).toFixed(2)}`).join(' ');
}

export function silhouetteLayers(layer) {
  if(openStructure(layer))return [];
  return layer.contours?.length ? layer.contours.map(outline=>({...layer,outline,
    holes:(layer.holes||[]).filter(hole=>ringContains(outline,hole))})) : [layer];
}

export function detailPath(layer,path,width,height) {
  if(openStructure(layer)||layer.outline_style!=='curved'||path.length<3)return `M${projectedPoints(layer,path,width,height).replaceAll(' ','L')}`;
  if(path.length>3&&path[0].every((n,k)=>n===path.at(-1)[k]))return outlinePath({...layer,outline:path,holes:[]},width,height);
  const [x1,y1,x2,y2]=layer.bbox;
  const points=path.map(([x,y])=>[(x1+x*(x2-x1))*width,(y1+y*(y2-y1))*height]);
  const fmt=p=>p.map(n=>n.toFixed(2)).join(',');
  const toward=(a,b)=>a.map((n,k)=>n+(b[k]-n)*.18);
  let d=`M${fmt(points[0])}`;
  for(let i=1;i<points.length-1;i++)d+=`L${fmt(toward(points[i],points[i-1]))}Q${fmt(points[i])} ${fmt(toward(points[i],points[i+1]))}`;
  return `${d}L${fmt(points.at(-1))}`;
}

// Round only explicitly curved silhouettes, using bounded quadratic corner
// cuts. Unlike Catmull-Rom splines, control points cannot overshoot the box.
function singleOutlinePath(layer,width,height) {
  if(!layer.outline?.length)return '';
  const ring=layer.outline[0].every((v,k)=>v===layer.outline.at(-1)[k])?layer.outline.slice(0,-1):layer.outline;
  const [x1,y1,x2,y2]=layer.bbox;
  const p=ring.map(([x,y])=>[(x1+x*(x2-x1))*width,(y1+y*(y2-y1))*height]);
  const fmt=p=>p.map(n=>n.toFixed(2)).join(',');
  if(layer.outline_style!=='curved')return `M${p.map(fmt).join('L')}Z`;
  const toward=(a,b)=>a.map((v,k)=>v+(b[k]-v)*.18);
  let d=`M${fmt(toward(p[0],p.at(-1)))}`;
  for(let i=0;i<p.length;i++) {
    const v=p[i],next=p[(i+1)%p.length];
    d+=`Q${fmt(v)} ${fmt(toward(v,next))}L${fmt(toward(next,v))}`;
  }
  return `${d}Z`;
}

// Keep genuine enclosed background gaps transparent. Every part receives only
// its own holes; adding an outside hole to another part would create a filled island.
export function outlinePath(layer,width,height) {
  if(!layer.outline?.length)return '';
  return singleOutlinePath(layer,width,height)+(layer.holes||[]).map(outline=>
    singleOutlinePath({...layer,outline,outline_style:'angular'},width,height)).join('');
}
