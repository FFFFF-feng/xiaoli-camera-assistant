// Infer only short continuations at observed image boundaries. All coordinates
// here are in source pixels; the existing scene and its subject layout are immutable.
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const wood=new Set(['tree','branch','tree_branch','plant','leaf']);
const hard=new Set(['building','wall','tower']);

export function sceneEdgeDirections(board,width,height) {
  const found=[];
  board.layers.forEach((layer,layerIndex)=>{
    if(layer.representation!=='context_lines'||!layer.source_bbox||(!wood.has(layer.kind)&&!hard.has(layer.kind)))return;
    const [x1,y1,x2,y2]=layer.source_bbox;
    for(const path of layer.source_details||[])for(const reversed of [false,true]) {
      const points=(reversed?[...path].reverse():path).slice(0,12).map(([x,y])=>[(x1+x*(x2-x1))*width,(y1+y*(y2-y1))*height]);
      if(points.length<3)continue;
      const p=points[0],distances=[p[1],height-p[1],p[0],width-p[0]],side=distances.indexOf(Math.min(...distances));
      if(distances[side]>4)continue;
      let anchor=1,length=0;
      while(anchor<points.length-1&&Math.hypot(points[anchor][0]-p[0],points[anchor][1]-p[1])<Math.max(7,Math.min(width,height)*.035))anchor++;
      for(let i=1;i<=anchor;i++)length+=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);
      const dx=p[0]-points[anchor][0],dy=p[1]-points[anchor][1],span=Math.hypot(dx,dy);
      if(span<5||!length)continue;
      // Buildings require a genuinely straight observed edge. Jagged nearby foliage is not architectural evidence.
      if(hard.has(layer.kind)&&span/length<.94)continue;
      const normal=[-dy,dy,-dx,dx][side],tangent=side<2?dx:dy;
      if(normal<span*.35)continue;
      const drift=clamp(tangent/normal,-2,2),mid=points[Math.max(1,Math.floor(anchor/2))];
      const nearNormal=[mid[1]-p[1],p[1]-mid[1],mid[0]-p[0],p[0]-mid[0]][side];
      const nearTangent=side<2?p[0]-mid[0]:p[1]-mid[1];
      const curve=wood.has(layer.kind)&&nearNormal>3?clamp((nearTangent/nearNormal-drift)/Math.max(normal,12)*.35,-.008,.008):0;
      const position=side<2?p[0]:p[1];
      if(found.some(d=>d.side===side&&Math.abs(d.position-position)<3&&Math.abs(d.drift-drift)<.35))continue;
      found.push({side,position,drift,curve,point:p,layerIndex,kind:layer.kind});
    }
  });
  return found.slice(0,32);
}

function boundaryProfile(data,width,height,side,depth) {
  const horizontal=side<2,n=horizontal?width:height;
  const radius=Math.max(1,Math.round(Math.min(width,height)*.008));
  const line=Array.from({length:n},(_,i)=>{
    const counts=new Map();
    for(let a=Math.max(0,i-radius);a<=Math.min(n-1,i+radius);a++) {
      const x=horizontal?a:side===2?depth:width-1-depth,y=horizontal?(side===0?depth:height-1-depth):a;
      const p=(y*width+x)*4;if(!data[p+3])continue;
      const key=(data[p]<<16)|(data[p+1]<<8)|data[p+2];counts.set(key,(counts.get(key)||0)+1);
    }
    return [...counts].sort((a,b)=>b[1]-a[1])[0]?.[0];
  });
  const changes=[];
  for(let i=1;i<n;i++)if(line[i]!==line[i-1]&&line[i]!==undefined&&line[i-1]!==undefined)changes.push({position:i,before:line[i-1],after:line[i]});
  return {line,changes};
}

function edgePainter(data,width,height,side,directions,fallback) {
  const n=side<2?width:height,depth=Math.min(Math.min(width,height)-1,Math.max(4,Math.round(Math.min(width,height)*.05)));
  const edge=boundaryProfile(data,width,height,side,0),inner=boundaryProfile(data,width,height,side,depth);
  const bends=edge.changes.map(change=>{
    const nearby=directions.filter(d=>d.side===side&&Math.abs(d.position-change.position)<Math.max(5,n*.025)).sort((a,b)=>Math.abs(a.position-change.position)-Math.abs(b.position-change.position))[0];
    const match=inner.changes.filter(c=>c.before===change.before&&c.after===change.after&&Math.abs(c.position-change.position)<n*.16).sort((a,b)=>Math.abs(a.position-change.position)-Math.abs(b.position-change.position))[0];
    return {...change,drift:nearby?.drift??(match&&depth?clamp((change.position-match.position)/depth,-2,2):0),curve:nearby?.curve||0};
  });
  // Cache each outward row/column: curves follow line tangents or the motion of the
  // same colour boundary in two observed interior slices, rather than edge stretching.
  const rows=new Map();
  return (position,distance)=>{
    const row=clamp(Math.round(distance),0,Math.ceil(Math.min(width,height)*.35));
    if(!rows.has(row)) {
      let previous=-Infinity;
      rows.set(row,bends.map(b=>{
        // Bound curvature away from the observation so it cannot curl back into a new object.
        const bend=b.curve*row*Math.min(row,40);
        const at=Math.max(previous,b.position+b.drift*row+bend);previous=at;
        return {at,color:b.after};
      }));
    }
    let color=edge.line[0]??fallback;
    for(const b of rows.get(row)){if(position<b.at)break;color=b.color;}
    return color;
  };
}

export function extendSceneBackground({data,width,height},transform,outWidth,outHeight,directions=[]) {
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>160000||data.length!==width*height*4
    ||!Number.isInteger(outWidth)||!Number.isInteger(outHeight)||outWidth<1||outHeight<1||outWidth*outHeight>600000
    ||!transform||!['x','y','width','height'].every(k=>Number.isFinite(transform[k]))||transform.width<=0||transform.height<=0)throw new RangeError('背景延伸尺寸无效');
  const t=transform;
  if(t.x<=0&&t.y<=0&&t.x+t.width>=1&&t.y+t.height>=1)return null;
  const colors=new Map();
  for(let p=0;p<width*height;p++)if(data[p*4+3]){const key=(data[p*4]<<16)|(data[p*4+1]<<8)|data[p*4+2];colors.set(key,(colors.get(key)||0)+1);}
  const fallback=[...colors].sort((a,b)=>b[1]-a[1])[0]?.[0];
  if(fallback===undefined)return null;
  if(colors.size>12)throw new RangeError('背景延伸只接受简化配色');
  const painters=[0,1,2,3].map(side=>edgePainter(data,width,height,side,directions,fallback));
  const output=new Uint8ClampedArray(outWidth*outHeight*4);
  for(let y=0;y<outHeight;y++)for(let x=0;x<outWidth;x++) {
    const u=((x+.5)/outWidth-t.x)/t.width,v=((y+.5)/outHeight-t.y)/t.height;
    if(u>=0&&u<=1&&v>=0&&v<=1)continue;
    const dx=Math.max(-u,u-1,0)*t.width,dy=Math.max(-v,v-1,0)*t.height;
    const key=dy>=dx?painters[v<0?0:1](u*width,Math.max(-v,v-1)*height):painters[u<0?2:3](v*height,Math.max(-u,u-1)*width);
    const p=(y*outWidth+x)*4;output[p]=key>>16;output[p+1]=(key>>8)&255;output[p+2]=key&255;output[p+3]=255;
  }
  return {data:output,width:outWidth,height:outHeight};
}

export function sceneContinuationPaths(directions,transform,sourceWidth,sourceHeight,width,height) {
  const project=p=>[(transform.x+p[0]/sourceWidth*transform.width)*width,(transform.y+p[1]/sourceHeight*transform.height)*height];
  const fmt=p=>p.map(n=>n.toFixed(2)).join(',');
  return directions.map(d=>{
    const p=project(d.point),points=[p],horizontal=d.side<2;
    const availableDistance=horizontal?(d.side===0?transform.y:1-transform.y-transform.height)*sourceHeight/transform.height
      :(d.side===2?transform.x:1-transform.x-transform.width)*sourceWidth/transform.width;
    const maxDistance=Math.min(availableDistance,Math.max(sourceWidth,sourceHeight)*.35);
    if(maxDistance<=0)return null;
    for(let n=0;n<=Math.ceil(maxDistance)+4;n+=2) {
      const along=d.position+d.drift*n+d.curve*n*Math.min(n,40);
      const point=horizontal?[along,d.side===0?-n:sourceHeight+n]:[d.side===2?-n:sourceWidth+n,along];
      points.push(project(point));
    }
    return {layerIndex:d.layerIndex,path:`M${points.map(fmt).join('L')}`};
  }).filter(Boolean);
}

export function sceneExtensionImage(pixels,transform,aspect,directions) {
  if(!Number.isFinite(aspect)||aspect<=0)return null;
  const width=Math.max(1,Math.round(720*Math.min(1,aspect))),height=Math.max(1,Math.round(720/Math.max(1,aspect)));
  const extension=extendSceneBackground(pixels,transform,width,height,directions);
  if(!extension)return null;
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const context=canvas.getContext('2d');if(!context)return null;
  context.putImageData(new ImageData(extension.data,width,height),0,0);
  return canvas.toDataURL('image/png');
}
