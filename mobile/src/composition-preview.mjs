const short=s=>typeof s==='string'&&s.trim()?s.trim().slice(0,240):'';
export function previewPlan(proposal,referencePhotoId='photo1') {
  if(!proposal||!short(proposal.goal)||!Array.isArray(proposal.actions)
    ||!/^photo[1-6]$/.test(referencePhotoId))return null;
  const actions=proposal.actions.map(short).filter(Boolean).slice(0,8);
  if(!actions.length)return null;
  const board=proposal.storyboard;
  const features=(board?.layers||[]).filter(l=>l.evidence_photo_ids?.includes(referencePhotoId))
    .flatMap(l=>l.identity_features||[]).map(short).filter(Boolean);
  const layout=(board?.layers||[]).filter(l=>short(l.label)&&['main','foreground','background','prop'].includes(l.role)
    &&Array.isArray(l.bbox)&&l.bbox.length===4&&l.bbox.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1)
    &&l.bbox[2]>l.bbox[0]&&l.bbox[3]>l.bbox[1]).slice(0,6).map(l=>({label:short(l.label),role:l.role,bbox:[...l.bbox]}));
  return {goal:short(proposal.goal),actions,preserve_features:[...new Set(features)].slice(0,12),
    aspect:['portrait','landscape','square'].includes(board?.aspect)?board.aspect:'auto',
    reference_photo_id:referencePhotoId,layout};
}
export function safePreviewImage(value) {
  return typeof value==='string'&&value.length<=16*1024*1024+128
    &&/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(value)?value:'';
}
export function localReference(value,origin) {
  try {
    const url=new URL(value,origin);
    return url.protocol==='blob:'||(['http:','https:'].includes(url.protocol)&&url.origin===origin)
      ||/^data:image\/(jpeg|png);base64,/.test(value);
  } catch {return false;}
}
