const roles=new Set(['main','foreground','background','prop']);
const colors=new Set(['slate','blue','ochre','sage','rose']);
const kinds=new Set(['person','tree','pet','building','mountain','flower','object','background']);
const point=p=>Array.isArray(p)&&p.length===2&&p.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1);
const points=(p,min)=>Array.isArray(p)&&p.length>=min&&p.length<=32&&p.every(point);
const text=(s,n)=>typeof s==='string'&&s.trim().length>0&&s.length<=n;
const photo=s=>typeof s==='string'&&/^photo[1-6]$/.test(s);

export function usableTargetBoard(value) {
  if(!value||!['portrait','landscape','square'].includes(value.aspect)||!photo(value.reference_photo_id)
    ||!text(value.intent,100)||!text(value.distance_instruction,160)
    ||(value.narration!==undefined&&(typeof value.narration!=='string'||value.narration.length>160))
    ||!['closer','farther','similar','unknown'].includes(value.distance_relation)
    ||!Array.isArray(value.layers)||!value.layers.length||value.layers.length>6
    ||!Array.isArray(value.changes)||!value.changes.length||value.changes.length>3
    ||!Array.isArray(value.limitations)||!value.limitations.length||value.limitations.length>5
    ||!value.limitations.every(s=>text(s,500)))return null;
  for(const layer of value.layers) {
    const b=layer?.bbox;
    if(!text(layer?.label,30)||!kinds.has(layer.kind)||!roles.has(layer.role)||!colors.has(layer.color)
      ||(layer.kind==='background'&&layer.role!=='background')
      ||!Number.isInteger(layer.depth)||layer.depth<0||layer.depth>9
      ||!Array.isArray(b)||b.length!==4||!point(b.slice(0,2))||!point(b.slice(2))
      ||b[2]-b[0]<.005||b[3]-b[1]<.005||!points(layer.outline,3)
      ||!Array.isArray(layer.details)||layer.details.length>10||!layer.details.every(p=>points(p,2))
      ||!Array.isArray(layer.evidence_photo_ids)||!layer.evidence_photo_ids.length
      ||layer.evidence_photo_ids.length>6||!layer.evidence_photo_ids.every(photo)
      ||!Array.isArray(layer.identity_features)||layer.identity_features.length>6
      ||!layer.identity_features.every(s=>text(s,160))
      ||!['observed','approximate'].includes(layer.certainty))return null;
    const p=layer.outline;
    const area=Math.abs(p.reduce((a,v,i)=>{const n=p[(i+1)%p.length];return a+v[0]*n[1]-n[0]*v[1]},0))/2;
    if(area<.01)return null;
  }
  if(!value.layers.some(l=>l.role==='main')||!value.changes.every(c=>text(c?.problem,140)
    &&text(c?.adjustment,140)&&text(c?.benefit,140)))return null;
  return value;
}

export function projectedPoints(layer, path, width, height) {
  const [x1,y1,x2,y2]=layer.bbox;
  return path.map(([x,y])=>`${((x1+x*(x2-x1))*width).toFixed(2)},${((y1+y*(y2-y1))*height).toFixed(2)}`).join(' ');
}
