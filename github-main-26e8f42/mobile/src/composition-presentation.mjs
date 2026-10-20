// Camera directions come from existing instructions, never from silhouette shifts
// (parallax cannot be inferred from a single photograph).
/** @param {import('./types').TargetBoard} board
 * @param {string[]} actions
 * @param {import('./types').FramingPlan|null} framing */
export function fieldActions(board, actions=[], framing=null) {
  const list=[...actions,board.distance_instruction].filter(s=>typeof s==='string'&&s.trim());
  return {problem:board.changes.map(c=>c.problem).join('；')||framing?.diagnosis||'核对当前取景',
    actions:[...new Set(list)],benefit:board.changes.map(c=>c.benefit).join('；'),
    check:framing?.success_check||framing?.edge_check||'试拍后检查主体是否完整、四边余量和背景干扰。'};
}
export function sourceFrameGuide(board, actions=[]) {
  const mains=board.layers.filter(l=>l.role==='main');
  if(!mains.length||mains.some(l=>!l.source_bbox))return null;
  const boxes=mains.map(l=>l.source_bbox);
  const union=[Math.min(...boxes.map(b=>b[0])),Math.min(...boxes.map(b=>b[1])),
    Math.max(...boxes.map(b=>b[2])),Math.max(...boxes.map(b=>b[3]))];
  const names=['左','上','右','下'],edges=['left','top','right','bottom'];
  const margins=[union[0],union[1],1-union[2],1-union[3]].map((value,i)=>({
    edge:edges[i],label:names[i],percent:Math.round(value*100),
    contact:mains.some(l=>l.photo_boundary?.clipped_edges?.includes(edges[i])),near:value<=.01}));
  const text=actions.join('；').split(/[。；，]/).filter(s=>!/(不要|勿|避免|无需|不必)/.test(s)).join('；');
  /** @type {[RegExp,string,number,number,number,number][]} */
  const candidates=[
    [/左移|向左|往左/,'左移',370,760,220,760],
    [/右移|向右|往右/,'右移',630,760,780,760],
    [/后退|退后/,'后退',500,760,500,900],
    [/靠近|向前|前移/,'靠近',500,760,500,620],
    [/降低机位|放低|蹲下/,'降低机位',830,680,830,830],
    [/提高机位|抬高机位|举高/,'提高机位',830,680,830,530],
  ];
  const directions=candidates.filter(([pattern])=>pattern.test(text)).map(([,label,x1,y1,x2,y2])=>({label,x1,y1,x2,y2}));
  return {frame:board.target_frame||[0,0,1,1],margins,directions};
}
