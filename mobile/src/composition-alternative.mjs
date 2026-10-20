import {sourceLayout, usableTargetBoard, hasPhotoCut} from './target-board.mjs';
import {frameAspect} from './composition-sketch.mjs';

export const LOCAL_COMPARISON_NOTE='本地取景比较方案：复用已提取轮廓与统一缩放，不是模型重新分析或真实新机位预测。';
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));

// Clip observed strokes only; never connect separate runs or invent scenery.
function clipStroke(path) {
  const result=[];let active=[];
  const finish=()=>{if(active.length>1)result.push(active);active=[];};
  for(let i=1;i<path.length;i++) {
    const a=path[i-1],b=path[i],dx=b[0]-a[0],dy=b[1]-a[1];
    let low=0,high=1,visible=true;
    for(const [p,q] of [[-dx,a[0]],[dx,1-a[0]],[-dy,a[1]],[dy,1-a[1]]]) {
      if(p===0) {if(q<0)visible=false;}
      else if(p<0)low=Math.max(low,q/p);
      else high=Math.min(high,q/p);
    }
    if(!visible||low>high){finish();continue;}
    const [start,end]=[low,high].map(t=>[clamp(a[0]+t*dx,0,1),clamp(a[1]+t*dy,0,1)]);
    if(start.every((n,k)=>Math.abs(n-end[k])<1e-12)){finish();continue;}
    if(active.length&&active.at(-1).some((n,k)=>Math.abs(n-start[k])>1e-8))finish();
    if(!active.length)active.push(start);
    active.push(end);
    if(active.length===64){result.push(active);active=[end];}
  }
  finish();return result;
}

function projectEnvironment(layer, transform) {
  const [sx,sy,tx,ty]=transform,b=layer.bbox;
  let paths=layer.details;
  if(layer.representation!=='context_lines') {
    const perimeters=layer.photo_boundary?.clipped_edges?.length?layer.photo_boundary.visible_paths:
      (layer.contours?.length?layer.contours:[layer.outline]).map(p=>p[0].every((n,k)=>n===p.at(-1)[k])?p:[...p,p[0]]);
    paths=[...perimeters.flatMap(p=>Array.from({length:Math.ceil((p.length-1)/63)},(_,i)=>p.slice(i*63,i*63+64))),...paths].slice(0,96);
  }
  const project=p=>[(b[0]+p[0]*(b[2]-b[0]))*sx+tx,(b[1]+p[1]*(b[3]-b[1]))*sy+ty];
  const lines=paths.flatMap(p=>clipStroke(p.map(project))).slice(0,96);
  if(!lines.length)return null;
  const xs=lines.flat().map(p=>p[0]),ys=lines.flat().map(p=>p[1]);
  const extent=values=>{
    let low=Math.min(...values),high=Math.max(...values);
    if(high-low<.006){low=clamp((low+high)/2-.003,0,.994);high=low+.006;}
    return [low,high];
  };
  const [x1,x2]=extent(xs),[y1,y2]=extent(ys);
  return {...layer,representation:'context_lines',bbox:[x1,y1,x2,y2],outline:[],contours:[],holes:[],
    details:lines.map(p=>p.map(([x,y])=>[clamp((x-x1)/(x2-x1),0,1),clamp((y-y1)/(y2-y1),0,1)])),
    source_details:paths,photo_boundary:null};
}

/** A visible alternative to an unchanged layout, keeping the model plan intact. */
export function enlargedCompositionAlternative(proposal,intent='') {
  const board=usableTargetBoard(proposal?.storyboard),original=board&&sourceLayout(board);
  if(!original||board.layout_mode!=='source_preserving'||proposal.action_type==='crop'
    ||/保留原取景|保持原构图|不要放大|无需放大|全景|广阔|完整环境|倒影|对称/.test(intent)
    ||original.layers.some(layer=>layer.representation==='scene_structure'))return null;
  const mains=original.layers.filter(layer=>layer.role==='main');
  if(mains.some(layer=>hasPhotoCut(layer)))return null;
  const ratio=original.aspect/frameAspect(board.aspect),base=Math.min(1,1/ratio);
  const union=[Math.min(...mains.map(l=>l.bbox[0])),Math.min(...mains.map(l=>l.bbox[1])),
    Math.max(...mains.map(l=>l.bbox[2])),Math.max(...mains.map(l=>l.bbox[3]))];
  const scale=Math.min(base*1.7,.92/((union[2]-union[0])*ratio),.92/(union[3]-union[1]));
  // A small correction is not the distinct comparison the user asked for.
  if(scale/base<1.15)return null;
  const focus=mains.find(layer=>layer.source_object_id===proposal.composition_intent?.focus_object_id)||mains[0];
  const f=focus.bbox,fx=(f[0]+f[2])/2,fy=(f[1]+f[3])/2;
  const sx=scale*ratio,sy=scale;
  const tx=clamp(.5+(fx-.5)*base*ratio-fx*sx,.04-union[0]*sx,.96-union[2]*sx);
  const ty=clamp(.5+(fy-.5)*base-fy*sy,.04-union[1]*sy,.96-union[3]*sy);
  const layers=original.layers.map(layer=>layer.role==='main'?{...layer,
    bbox:[layer.bbox[0]*sx+tx,layer.bbox[1]*sy+ty,layer.bbox[2]*sx+tx,layer.bbox[3]*sy+ty]}:
    projectEnvironment(layer,[sx,sy,tx,ty])).filter(Boolean);
  const main=layers.find(layer=>layer.source_object_id===focus.source_object_id);
  if(!main)return null;
  const from=Math.round((f[2]-f[0])*100),to=Math.round((main.bbox[2]-main.bbox[0])*100);
  if(to-from<5)return null;
  const diagnosis=`主体宽度占比从${from}%增至${to}%，比较突出主体与保留环境的取舍。`;
  const action='保持当前焦段，在对焦和现场空间允许时适当靠近；按右图核对主体占比，保留全部主要主体的关键边缘。';
  const limitations=[LOCAL_COMPARISON_NOTE,'只改变统一取景范围；环境可能被裁去，未拍到的区域仍未知，不补画画外物体。',
    '靠近后的透视、遮挡、最近对焦距离与实际成片效果需现场试拍核对。'];
  const target={...board,intent:'放大主体 · 推荐取景备选',layout_mode:'schematic',observed_frame:null,target_frame:null,
    distance_relation:'unknown',distance_instruction:action,layers,
    changes:[{problem:'本次模型方案保留原取景，没有提供明显变化的对照。',adjustment:diagnosis,benefit:'主体更突出，同时减少环境范围；是否更符合需求需对照和试拍。'}],limitations};
  if(!usableTargetBoard(target))return null;
  return {...proposal,action_type:'camera_position',goal:'放大主体 · 推荐取景备选',storyboard:target,
    composition_intent:proposal.composition_intent?{...proposal.composition_intent,focus_object_id:focus.source_object_id,
      subject_scale:'larger',placement:'keep',vertical_placement:'keep',aspect:'keep',diagnosis}:null,
    sketch:null,crop_bbox:null,knowledge_ids:[],
    actions:[action,'检查主体是否完整、背景干扰是否减少；若环境信息更重要，可切换回原取景方案。'],
    reasons:[diagnosis],conditions:['主体已完整识别，并有足够的边缘余量与安全靠近空间。'],
    tradeoffs:['主体放大后环境范围减少，保留原取景也可能更符合表达目标。'],limitations,
    framing_plan:{diagnosis,visual_priority:`先看${focus.label}，环境与主体共享同一取景变换。`,
      placement:`主体中心横向${Math.round((main.bbox[0]+main.bbox[2])*50)}%、纵向${Math.round((main.bbox[1]+main.bbox[3])*50)}%。`,
      scale:`主体宽约${to}%，原图为${from}%；轮廓比例不变。`,negative_space:'四边预留至少约4%的示意余量；余量可能含其他景物，不等于留白。',
      edge_check:'核对所有主要主体的关键边缘，不能为放大效果切断主体。',background_control:'环境共同缩放并裁去超出画框的部分，不单独搬动背景。',
      success_check:'对照主体占比、全部主体边缘与环境信息，现场试拍确认是否改善。'}};
}

export function compositionComparisonProposals(proposals=[],intent='') {
  if(!proposals.length||proposals.some(p=>usableTargetBoard(p.storyboard)
    &&p.storyboard.layout_mode!=='source_preserving'))return proposals;
  const alternative=enlargedCompositionAlternative(proposals[0],intent);
  return alternative?[alternative,...proposals]:proposals;
}
