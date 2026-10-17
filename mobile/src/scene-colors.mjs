import { outlinePath,silhouetteLayers } from './target-board.mjs';

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

export function subjectIllustrationColor(layer,counts) {
  // Explicit object colour takes priority over incidental shadows inside its mask.
  // Generic role colours (e.g. "rose" as a main-subject tag) are not object evidence.
  /** @type {[RegExp,string][]} */
  const named=[[/^(白色|洁白|纯白|white\b)/i,'#fff9e9'],[/^(红色|鲜红|red\b)/i,'#e9a092'],
    [/^(粉色|粉红|pink\b)/i,'#f1c4d4'],[/^(黄色|金黄|yellow\b)/i,'#f5dc99'],
    [/^(蓝色|blue\b)/i,'#b2d9ef'],[/^(紫色|purple\b)/i,'#d9c6e8'],[/^(绿色|green\b)/i,'#bcdca3']];
  const name=(layer.label||'').trim();
  const declared=named.find(([pattern])=>pattern.test(name));
  return declared?.[1]||[...counts].sort((a,b)=>b[1]-a[1])[0]?.[0]||null;
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
  const paint=raw.map(rgb=>illustrationColor(rgb,woody));
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
  const scale=Math.min(1,360/Math.max(image.naturalWidth,image.naturalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
  const context=canvas.getContext('2d',{willReadFrequently:true});
  if(!context)throw new Error('无法准备场景配色');
  context.drawImage(image,0,0,canvas.width,canvas.height);
  const original=context.getImageData(0,0,canvas.width,canvas.height);
  return {aspect,pixels:{data:original.data,width:original.width,height:original.height}};
}

// The same masks and palette run on either Canvas or OffscreenCanvas.
export function colorizeScenePixels(original,board,createCanvas=()=>document.createElement('canvas')) {
  const woody=board.layers.some(l=>['tree','branch','tree_branch'].includes(l.kind));
  const flat=flatSceneColors(original,6,{woody});
  // Sample only within each observed, closed subject outline, then paint it cleanly.
  // Do not close open environmental lines or infer a new object mask from a bounding box.
  const mask=createCanvas();mask.width=original.width;mask.height=original.height;
  const maskContext=mask.getContext('2d',{willReadFrequently:true});
  if(!maskContext)throw new Error('无法准备主体配色');
  const fills=board.layers.map(layer=>{
    if(layer.representation==='context_lines'||!layer.source_bbox)return [];
    return silhouetteLayers({...layer,bbox:layer.source_bbox}).map(part=>{
      maskContext.clearRect(0,0,mask.width,mask.height);
      maskContext.fillStyle='#fff';maskContext.fill(new Path2D(outlinePath(part,mask.width,mask.height)),'evenodd');
      const pixels=maskContext.getImageData(0,0,mask.width,mask.height).data;
      const counts=new Map();
      for(let p=0;p<pixels.length;p+=4)if(pixels[p+3]>127&&original.data[p+3]) {
        const hex=illustrationColor([original.data[p],original.data[p+1],original.data[p+2]]);
        counts.set(hex,(counts.get(hex)||0)+1);
      }
      return counts.size?subjectIllustrationColor(layer,counts):null;
    });
  });
  return {fills,pixels:{data:flat.data,width:original.width,height:original.height}};
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
  return {...result,aspect,url:scenePixelsUrl(result.pixels)};
}
