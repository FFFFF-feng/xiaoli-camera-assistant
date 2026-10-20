import { outlinePath,silhouetteLayers } from './target-board.mjs';

// Legacy palette helpers retained for compatibility tests. Production rendering
// uses colorizeScenePixels below and must not use full-frame quantization.
// Deliberate illustration colours; do not retain the photograph's grey shadow/bokeh noise.
// These are explanatory colours, not a prediction of real exposure or object material.
export function illustrationColor(rgb,woody=false) {
  const [r,g,b]=rgb,hi=Math.max(...rgb),lo=Math.min(...rgb),delta=hi-lo;
  const light=(r*.2126+g*.7152+b*.0722)/255;
  if(delta<16)return light>.82?'#fff9e9':light>.42?(b>r+3?'#dceff7':woody?'#e4efce':'#f7e9cf'):(woody?'#b68a65':'#a0becd');
  let hue=hi===r?((g-b)/delta)%6:hi===g?(b-r)/delta+2:(r-g)/delta+4;
  hue=(hue*60+360)%360;
  if(woody&&light<.34&&delta/hi<.42)return '#b68a65';
  if(hue>=45&&hue<165)return light>.68?'#e4efce':light>.4?'#c6dfae':'#83b6a2';
  if(hue>=165&&hue<265)return light>.65?'#dceff7':'#a2cde4';
  if(hue>=265&&hue<345)return light>.68?'#f1d7e8':'#dfa8c1';
  return light>.73?'#f7e9cf':light>.43?'#e9bd8e':'#c18d70';
}

// Merge tiny connected patches, rather than blurring their edges. Large shapes remain intact.
function mergeSmallPatches(labels,width,height,palette) {
  const minimum=Math.max(5,Math.floor(width*height*.0035));
  const neighbours=p=>[p%width?p-1:-1,p%width<width-1?p+1:-1,p>=width?p-width:-1,p<width*(height-1)?p+width:-1];
  for(let pass=0;pass<2;pass++) {
    const seen=new Uint8Array(labels.length);
    for(let start=0;start<labels.length;start++) {
      if(seen[start]||labels[start]===255)continue;
      const label=labels[start],region=[start];seen[start]=1;
      for(let i=0;i<region.length;i++)for(const n of neighbours(region[i])) {
        if(n>=0&&!seen[n]&&labels[n]===label){seen[n]=1;region.push(n);}
      }
      if(region.length>=minimum)continue;
      const contacts=new Uint32Array(palette.length);
      for(const p of region)for(const n of neighbours(p))if(n>=0&&labels[n]!==255&&labels[n]!==label)contacts[labels[n]]++;
      let best=-1;
      for(let i=0;i<contacts.length;i++)if(contacts[i]&&(best<0||contacts[i]>contacts[best]))best=i;
      if(best>=0)for(const p of region)labels[p]=best;
    }
  }
  return labels;
}

export function referenceColor(rgb) {
  return '#'+rgb.map(n=>Math.round(Math.max(0,Math.min(255,n))).toString(16).padStart(2,'0')).join('');
}

export function referenceOutlineColor(fill,fallback='#415970') {
  if(typeof fill!=='string'||!/^#[a-f\d]{6}$/i.test(fill))return fallback;
  const [r,g,b]=[1,3,5].map(i=>parseInt(fill.slice(i,i+2),16));
  return r*.2126+g*.7152+b*.0722<90?'#dce4e7':fallback;
}

export function subjectIllustrationColor(_layer,counts) {
  // Keep the compatibility name, but labels and role tags must never override sampled pixels.
  return [...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0]?.[0]||null;
}

export function sampledSubjectColor(original,mask) {
  const bins=new Map();
  for(let p=0;p<original.length;p+=4)if(mask[p+3]>127&&original[p+3]) {
    const key=((original[p]>>4)<<8)|((original[p+1]>>4)<<4)|(original[p+2]>>4);
    const bin=bins.get(key)||{n:0,sum:[0,0,0]};
    bin.n++;for(let k=0;k<3;k++)bin.sum[k]+=original[p+k];bins.set(key,bin);
  }
  const dominant=[...bins.entries()].sort((a,b)=>b[1].n-a[1].n||a[0]-b[0])[0]?.[1];
  return dominant?referenceColor(dominant.sum.map(n=>n/dominant.n)):null;
}

// Local, bounded flat colours from the reference. No new scene geometry and no network/model call.
export function flatSceneColors({data,width,height}, limit=6, {woody=false}={}) {
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>160000
    ||data.length!==width*height*4)throw new RangeError('配色图尺寸无效');
  if(!Number.isInteger(limit)||limit<2||limit>12)throw new RangeError('配色数量无效');
  const histogram=new Map();
  const keyAt=i=>((data[i]>>3)<<10)|((data[i+1]>>3)<<5)|(data[i+2]>>3);
  for(let i=0;i<data.length;i+=4) {
    if(!data[i+3])continue;
    const key=keyAt(i),bin=histogram.get(key)||{key,n:0,sum:[0,0,0]};
    bin.n++;for(let k=0;k<3;k++)bin.sum[k]+=data[i+k];histogram.set(key,bin);
  }
  const bins=[...histogram.values()].map(b=>({...b,rgb:b.sum.map(n=>n/b.n)}));
  if(!bins.length)return {data:new Uint8ClampedArray(data.length),palette:[]};
  const measure=items=>{
    const ranges=[0,1,2].map(k=>Math.max(...items.map(b=>b.rgb[k]))-Math.min(...items.map(b=>b.rgb[k])));
    const axis=ranges.indexOf(Math.max(...ranges));
    return {axis,score:ranges[axis]**2*Math.sqrt(items.reduce((s,b)=>s+b.n,0))};
  };
  const boxes=[bins];
  while(boxes.length<limit) {
    let chosen=-1,score=-1;
    boxes.forEach((b,i)=>{if(b.length>1&&measure(b).score>score){chosen=i;score=measure(b).score;}});
    if(chosen<0)break;
    const {axis}=measure(boxes[chosen]);
    const sorted=[...boxes[chosen]].sort((a,b)=>a.rgb[axis]-b.rgb[axis]||a.key-b.key);
    const half=sorted.reduce((s,b)=>s+b.n,0)/2;
    let total=0,split=1;
    for(let i=0;i<sorted.length-1;i++){total+=sorted[i].n;split=i+1;if(total>=half)break;}
    boxes.splice(chosen,1,sorted.slice(0,split),sorted.slice(split));
  }
  const raw=boxes.map(b=>[0,1,2].map(k=>b.reduce((s,p)=>s+p.sum[k],0)/b.reduce((s,p)=>s+p.n,0)));
  // Quantize the photograph itself. Do not remap reds/blacks/whites into a pastel palette.
  const paint=raw.map(referenceColor);
  const unique=[...new Set(paint)];
  const palette=unique.map(hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)));
  const lookup=new Map(bins.map(bin=>{
    let best=0,distance=Infinity;
    raw.forEach((rgb,index)=>{const d=rgb.reduce((s,v,k)=>s+(v-bin.rgb[k])**2,0);if(d<distance){best=index;distance=d;}});
    return [bin.key,unique.indexOf(paint[best])];
  }));
  let labels=new Uint8Array(width*height).fill(255);
  for(let p=0;p<labels.length;p++)if(data[p*4+3])labels[p]=lookup.get(keyAt(p*4));
  // A local majority removes leaf/texture speckles without bridging transparent pixels.
  for(let pass=0;pass<2;pass++) {
    const next=labels.slice();
    const counts=new Uint8Array(palette.length);
    for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++) {
      const p=y*width+x;if(labels[p]===255)continue;
      counts.fill(0);
      for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const n=labels[p+dy*width+dx];if(n!==255)counts[n]++;}
      let best=labels[p];for(let n=0;n<counts.length;n++)if(counts[n]>counts[best])best=n;
      if(counts[best]>=5)next[p]=best;
    }
    labels=next;
  }
  labels=mergeSmallPatches(labels,width,height,palette);
  const output=new Uint8ClampedArray(data.length);
  labels.forEach((label,p)=>{if(label!==255){output.set(palette[label],p*4);output[p*4+3]=data[p*4+3];}});
  return {data:output,palette};
}

export function sceneColorTransform(board,showSource=false) {
  if(board?.render_basis!=='source_geometry')return null;
  const mains=board.layers.filter(l=>l.role==='main');
  const valid=b=>Array.isArray(b)&&b.length===4&&b.every(n=>typeof n==='number'&&Number.isFinite(n))&&b[2]>b[0]&&b[3]>b[1];
  if(!mains.length||!mains.every(l=>valid(l.source_bbox)&&valid(l.bbox)))return null;
  if(showSource)return {x:0,y:0,width:1,height:1};
  const a=mains[0].source_bbox,b=mains[0].bbox;
  const width=(b[2]-b[0])/(a[2]-a[0]),height=(b[3]-b[1])/(a[3]-a[1]);
  const x=b[0]-a[0]*width,y=b[1]-a[1]*height;
  // Older records may have moved main subjects independently: do not colour them with a mismatched scene.
  if(mains.some(l=>l.bbox.some((n,k)=>Math.abs(n-(l.source_bbox[k]*(k%2?height:width)+(k%2?y:x)))>1e-5)))return null;
  return {x,y,width,height};
}

export async function scenePhotoPixels(source) {
  const image=new Image();image.crossOrigin='anonymous';image.src=source;
  await image.decode();
  const aspect=image.naturalWidth/image.naturalHeight;
  if(!Number.isFinite(aspect)||aspect<=0)throw new Error('参考图尺寸无效');
  const scale=Math.min(1,720/Math.max(image.naturalWidth,image.naturalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
  const context=canvas.getContext('2d',{willReadFrequently:true});
  if(!context)throw new Error('无法准备场景配色');
  context.drawImage(image,0,0,canvas.width,canvas.height);
  const original=context.getImageData(0,0,canvas.width,canvas.height);
  return {aspect,pixels:{data:original.data,width:original.width,height:original.height}};
}

const PAPER=[250,249,245];
export const OBJECT_COLOR_VERSION='masked-object-color-v1';

function checkPixels(image) {
  if(!Number.isInteger(image.width)||!Number.isInteger(image.height)||image.width<1||image.height<1
    ||image.width*image.height>720*720||image.data.length!==image.width*image.height*4)
    throw new RangeError('物体取色尺寸无效');
}

// Diagram brightness, not a claim about exposure: retain the original hue while
// lifting dark fills enough to read the dark contour lines on paper.
export function diagramColor(rgb,role='main') {
  const light=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  const mix=role==='background'?.9:role==='foreground'?.58:.12+Math.max(0,100-light)/400;
  return rgb.map((v,k)=>Math.round(v*(1-mix)+PAPER[k]*mix));
}

export function lineartPaint(layer) {
  if(layer.role==='main')return {stroke:'#4b555b',opacity:1,detailOpacity:.65};
  if(layer.role==='background')return {stroke:'#89928e',opacity:.46,detailOpacity:.65};
  return {stroke:'#75847a',opacity:.7,detailOpacity:.7};
}

// Smooth inside one observed silhouette only. No global palette, no cross-mask
// merging, no inferred polygon for environmental/open paths.
export function paintObjectRegion(original,mask,role='main') {
  checkPixels(original);
  if(mask.length!==original.data.length)throw new RangeError('物体掩码尺寸无效');
  const {data,width,height}=original,out=new Uint8ClampedArray(data.length);
  const claimed=[];
  for(let p=0;p<width*height;p++)if(mask[p*4+3]>127&&data[p*4+3])claimed.push(p);
  for(const p of claimed) {
    const x=p%width,y=Math.floor(p/width),at=p*4;
    let count=0;const sum=[0,0,0];
    for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++) {
      const nx=x+dx,ny=y+dy;if(nx<0||ny<0||nx>=width||ny>=height)continue;
      const q=(ny*width+nx)*4;if(mask[q+3]<=127||!data[q+3])continue;
      const distance=(data[q]-data[at])**2+(data[q+1]-data[at+1])**2+(data[q+2]-data[at+2])**2;
      if(distance>3600)continue; // Do not mix a red/blue or petal/leaf boundary.
      const weight=1/(1+(dx*dx+dy*dy)/4+distance/900);
      count+=weight;for(let k=0;k<3;k++)sum[k]+=data[q+k]*weight;
    }
    const rgb=diagramColor(sum.map(v=>v/count),role);
    out.set(rgb,at);out[at+3]=Math.round(data[at+3]*mask[at+3]/255);
  }
  return {data:out,width,height};
}

export function backgroundWash(original,claimed) {
  checkPixels(original);
  if(claimed.length!==original.width*original.height)throw new RangeError('背景掩码尺寸无效');
  const sum=[0,0,0];let count=0;
  for(let p=0;p<original.width*original.height;p++) {
    const at=p*4;if(claimed[p]||!original.data[at+3])continue;
    count++;for(let k=0;k<3;k++)sum[k]+=original.data[at+k];
  }
  // One restrained paper tint, never a full-frame posterized photograph.
  return referenceColor(count?sum.map((n,k)=>PAPER[k]*.94+n/count*.06):PAPER);
}

// A blurred, low-opacity reference wash is NOT an object mask. It keeps the
// broad environment visible without quantizing shadows into solid patches.
export function softContextPixels(original,opacity=.12) {
  checkPixels(original);
  if(!Number.isFinite(opacity)||opacity<0||opacity>.55)throw new RangeError('环境底色浓度无效');
  const {data,width,height}=original,radius=3,horizontal=new Float32Array(data.length);
  for(let y=0;y<height;y++) {
    const sums=[0,0,0,0];
    const add=(x,sign)=>{const i=(y*width+x)*4,a=data[i+3]/255;for(let k=0;k<3;k++)sums[k]+=data[i+k]*a*sign;sums[3]+=a*sign;};
    for(let x=0;x<=Math.min(radius,width-1);x++)add(x,1);
    for(let x=0;x<width;x++) {
      horizontal.set(sums,(y*width+x)*4);
      if(x-radius>=0)add(x-radius,-1);if(x+radius+1<width)add(x+radius+1,1);
    }
  }
  const out=new Uint8ClampedArray(data.length);
  for(let x=0;x<width;x++) {
    const sums=[0,0,0,0];
    const add=(y,sign)=>{const i=(y*width+x)*4;for(let k=0;k<4;k++)sums[k]+=horizontal[i+k]*sign;};
    for(let y=0;y<=Math.min(radius,height-1);y++)add(y,1);
    for(let y=0;y<height;y++) {
      const at=(y*width+x)*4,area=(Math.min(width-1,x+radius)-Math.max(0,x-radius)+1)
        *(Math.min(height-1,y+radius)-Math.max(0,y-radius)+1);
      if(sums[3]>1e-6) {
        for(let k=0;k<3;k++)out[at+k]=sums[k]/sums[3];
        out[at+3]=Math.round(Math.min(1,sums[3]/area)*255*opacity);
      }
      if(y-radius>=0)add(y-radius,-1);if(y+radius+1<height)add(y+radius+1,1);
    }
  }
  return {data:out,width,height};
}

// Canvas and Worker share identical per-object masks and colours.
export function colorizeScenePixels(original,board,createCanvas=()=>document.createElement('canvas')) {
  checkPixels(original);
  if(!Array.isArray(board?.layers)||board.layers.length>6)throw new RangeError('取色对象数量无效');
  const mask=createCanvas();mask.width=original.width;mask.height=original.height;
  const maskContext=mask.getContext('2d',{willReadFrequently:true});
  if(!maskContext)throw new Error('无法准备主体配色');
  const output=new Uint8ClampedArray(original.data.length),claimed=new Uint8Array(original.width*original.height);
  const fills=board.layers.map(()=>[]);
  for(const {layer,index} of board.layers.map((layer,index)=>({layer,index})).sort((a,b)=>a.layer.depth-b.layer.depth)) {
    if(['context_lines','scene_structure'].includes(layer.representation)||!layer.source_bbox)continue;
    for(const part of silhouetteLayers({...layer,bbox:layer.source_bbox})) {
      maskContext.clearRect(0,0,mask.width,mask.height);
      maskContext.fillStyle='#fff';maskContext.fill(new Path2D(outlinePath(part,mask.width,mask.height)),'evenodd');
      const pixels=maskContext.getImageData(0,0,mask.width,mask.height).data;
      const painted=paintObjectRegion(original,pixels,layer.role);
      fills[index].push(sampledSubjectColor(painted.data,pixels));
      for(let p=0;p<claimed.length;p++) {
        const at=p*4,alpha=painted.data[at+3]/255;if(!alpha)continue;
        const behind=output[at+3]/255,total=alpha+behind*(1-alpha);
        for(let k=0;k<3;k++)output[at+k]=(painted.data[at+k]*alpha+output[at+k]*behind*(1-alpha))/total;
        output[at+3]=Math.round(total*255);claimed[p]=1;
      }
    }
  }
  const continuous=board.layers.some(layer=>layer.role==='main'&&layer.representation==='scene_structure');
  return {version:OBJECT_COLOR_VERSION,background:backgroundWash(original,claimed),fills,
    contextPixels:softContextPixels(original,continuous ? .55 : .12),
    pixels:{data:output,width:original.width,height:original.height}};
}

export function scenePixelsUrl(pixels) {
  const canvas=document.createElement('canvas');canvas.width=pixels.width;canvas.height=pixels.height;
  const context=canvas.getContext('2d');
  if(!context)throw new Error('无法准备场景配色');
  context.putImageData(new ImageData(pixels.data,pixels.width,pixels.height),0,0);
  return canvas.toDataURL('image/png');
}

export async function loadSceneColors(source,board) {
  const {aspect,pixels}=await scenePhotoPixels(source);
  const result=colorizeScenePixels(pixels,board);
  return {...result,aspect,url:scenePixelsUrl(result.pixels),contextUrl:scenePixelsUrl(result.contextPixels)};
}
