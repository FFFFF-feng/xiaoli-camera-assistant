/** Photo-derived line work. Nothing leaves the browser or enters saved advice. */
export function lineArtPixels(rgba, width, height) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 3 || height < 3
      || width * height > 700000 || rgba.length !== width * height * 4) {
    throw new Error('线稿图像尺寸无效');
  }
  const count = width * height;
  const gray = new Float32Array(count), blurred = new Float32Array(count);
  const gradient = new Float32Array(count), direction = new Uint8Array(count);
  const ink = new Uint8ClampedArray(count * 4), wash = new Uint8ClampedArray(count * 4);
  const histogram = new Uint32Array(256);
  for (let i = 0; i < count; i++) {
    const p = i * 4, alpha = rgba[p+3] / 255;
    gray[i] = (rgba[p]*.299 + rgba[p+1]*.587 + rgba[p+2]*.114) * alpha + 255*(1-alpha);
    const max = Math.max(rgba[p],rgba[p+1],rgba[p+2]);
    const min = Math.min(rgba[p],rgba[p+1],rgba[p+2]);
    // Low-opacity original hues, with neutral areas kept almost transparent.
    for (let c = 0; c < 3; c++) wash[p+c] = gray[i]*.35 + rgba[p+c]*.65;
    wash[p+3] = Math.round(alpha * (max-min > 22 ? 64 : 18));
  }
  for (let y = 1; y < height-1; y++) for (let x = 1; x < width-1; x++) {
    const i = y*width+x;
    blurred[i] = (gray[i-width-1]+2*gray[i-width]+gray[i-width+1]
      +2*gray[i-1]+4*gray[i]+2*gray[i+1]
      +gray[i+width-1]+2*gray[i+width]+gray[i+width+1])/16;
  }
  for (let y = 2; y < height-2; y++) for (let x = 2; x < width-2; x++) {
    const i = y*width+x;
    const gx = -blurred[i-width-1]+blurred[i-width+1]-2*blurred[i-1]+2*blurred[i+1]
      -blurred[i+width-1]+blurred[i+width+1];
    const gy = -blurred[i-width-1]-2*blurred[i-width]-blurred[i-width+1]
      +blurred[i+width-1]+2*blurred[i+width]+blurred[i+width+1];
    const magnitude = Math.min(255, Math.hypot(gx,gy)/4);
    gradient[i] = magnitude;
    histogram[Math.round(magnitude)]++;
    const angle = (Math.atan2(gy,gx)*180/Math.PI+180)%180;
    direction[i] = angle < 22.5 || angle >= 157.5 ? 0 : angle < 67.5 ? 1 : angle < 112.5 ? 2 : 3;
  }
  let strong = 0, threshold = 14;
  for (let value = 255; value >= 14; value--) {
    strong += histogram[value];
    if (strong >= count*.1) { threshold = Math.max(14,Math.min(38,value)); break; }
  }
  const offsets = [1,width+1,width,width-1];
  for (let y = 2; y < height-2; y++) for (let x = 2; x < width-2; x++) {
    const i = y*width+x, magnitude = gradient[i], offset = offsets[direction[i]];
    if (magnitude < threshold || magnitude < gradient[i-offset] || magnitude < gradient[i+offset]) continue;
    const p = i*4;
    ink[p]=45; ink[p+1]=60; ink[p+2]=74;
    ink[p+3]=Math.min(250,140+(magnitude-threshold)*3);
  }
  // A faint one-pixel shoulder keeps real contours legible after mobile downscaling.
  const core=ink.slice();
  for (let y=2;y<height-2;y++) for (let x=2;x<width-2;x++) {
    const p=(y*width+x)*4;
    if (core[p+3]) continue;
    const alpha=Math.max(core[p-4+3],core[p+4+3],core[p-width*4+3],core[p+width*4+3])*.32;
    if (alpha) ink.set([45,60,74,alpha],p);
  }
  return { ink, wash };
}

/** Fit inside a suggested box without distorting anatomy or clipping its edges. */
export function fitPhotoBox(box, sourceAspect, frameAspect) {
  const [x1,y1,x2,y2] = box;
  if (!Number.isFinite(sourceAspect) || sourceAspect <= 0 || !Number.isFinite(frameAspect)
      || frameAspect <= 0) return box;
  const availableWidth=x2-x1, availableHeight=y2-y1;
  const width=Math.min(availableWidth,availableHeight*sourceAspect/frameAspect);
  const height=width*frameAspect/sourceAspect;
  const x=(x1+x2-width)/2, y=(y1+y2-height)/2;
  return [x,y,x+width,y+height];
}

export function embeddedInMain(element, main) {
  if (element === main || element.role === 'main' || !element.source_bbox || !main.source_bbox) return false;
  const a=element.source_bbox, b=main.source_bbox;
  return a[0]>=b[0] && a[1]>=b[1] && a[2]<=b[2] && a[3]<=b[3];
}

function imageFromUrl(url) {
  const resolved = new URL(url,window.location.href);
  if (!['blob:','data:'].includes(resolved.protocol) && resolved.origin !== window.location.origin) {
    return Promise.reject(new Error('仅处理本页选择的照片'));
  }
  return new Promise((resolve,reject) => {
    const image = new Image();
    image.onload=()=>resolve(image);
    image.onerror=()=>reject(new Error('照片暂时无法读取，请重新选择'));
    image.src=url;
  });
}

/** The two transparent PNG layers are ephemeral and safe to embed in an explicit SVG download. */
export async function tracePhoto(url, sourceBox) {
  const image = await imageFromUrl(url);
  const box = sourceBox || [0,0,1,1];
  const x=box[0]*image.naturalWidth, y=box[1]*image.naturalHeight;
  const cropWidth=(box[2]-box[0])*image.naturalWidth;
  const cropHeight=(box[3]-box[1])*image.naturalHeight;
  const scale=Math.min(1,640/Math.max(cropWidth,cropHeight));
  const width=Math.max(3,Math.round(cropWidth*scale)), height=Math.max(3,Math.round(cropHeight*scale));
  const canvas=document.createElement('canvas'); canvas.width=width; canvas.height=height;
  const context=canvas.getContext('2d',{willReadFrequently:true});
  if (!context) throw new Error('当前浏览器无法生成线稿');
  context.drawImage(image,x,y,cropWidth,cropHeight,0,0,width,height);
  const pixels=context.getImageData(0,0,width,height);
  const layers=lineArtPixels(pixels.data,width,height);
  context.putImageData(new ImageData(layers.ink,width,height),0,0);
  const ink=canvas.toDataURL('image/png');
  context.putImageData(new ImageData(layers.wash,width,height),0,0);
  return { ink, wash:canvas.toDataURL('image/png'), aspect:cropWidth/cropHeight,
    sourceBox:box, fullFrame:!sourceBox };
}
