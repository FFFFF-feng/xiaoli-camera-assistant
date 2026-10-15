import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lineArtPixels, fitPhotoBox, embeddedInMain } from '../src/sketch-trace.mjs';

test('主体以原始比例完整放入目标框，宽高都不溢出', () => {
  for (const aspect of [.35,1,3.2]) for (const frame of [.75,1,1.6]) {
    const box=[.12,.16,.88,.92], fitted=fitPhotoBox(box,aspect,frame);
    assert.ok(fitted[0]>=box[0]-1e-10 && fitted[1]>=box[1]-1e-10);
    assert.ok(fitted[2]<=box[2]+1e-10 && fitted[3]<=box[3]+1e-10);
    assert.ok(Math.abs((fitted[2]-fitted[0])*frame/(fitted[3]-fitted[1])-aspect)<1e-10);
  }
});

test('主体已经包含手持道具时不再画第二份，独立环境物体保留', () => {
  const main={role:'main',source_bbox:[.2,.1,.8,.9]};
  assert.equal(embeddedInMain({role:'context',source_bbox:[.3,.3,.5,.5]},main),true);
  assert.equal(embeddedInMain({role:'context',source_bbox:[.05,.3,.15,.5]},main),false);
  assert.equal(embeddedInMain(main,main),false);
  assert.equal(embeddedInMain({role:'context'},main),false);
});

test('透明或均匀照片不凭空产生轮廓，透明颜色不泄漏到淡彩层', () => {
  for (const alpha of [0,255]) {
    const pixels=new Uint8ClampedArray(32*32*4);
    for (let p=0;p<pixels.length;p+=4) pixels.set([200,30,40,alpha],p);
    const {ink,wash}=lineArtPixels(pixels,32,32);
    assert.equal(ink.filter((_,i)=>i%4===3).some(a=>a!==0),false);
    if (!alpha) assert.equal(wash.filter((_,i)=>i%4===3).some(a=>a!==0),false);
    else assert.ok(wash.filter((_,i)=>i%4===3).every(a=>a>0 && a<80));
  }
});

test('保留外轮廓和内部辨识线条，不把实心区域填成深色块', () => {
  const width=64, pixels=new Uint8ClampedArray(width*width*4).fill(255);
  const rectangle=(x1,y1,x2,y2,color)=>{
    for(let y=y1;y<y2;y++) for(let x=x1;x<x2;x++) pixels.set([...color,255],(y*width+x)*4);
  };
  rectangle(12,8,52,58,[150,110,90]);
  rectangle(23,24,29,30,[20,20,20]);
  rectangle(36,24,42,30,[20,20,20]);
  const {ink}=lineArtPixels(pixels,width,width);
  const edges=(x1,y1,x2,y2)=>{
    let n=0;for(let y=y1;y<y2;y++)for(let x=x1;x<x2;x++)if(ink[(y*width+x)*4+3])n++;
    return n;
  };
  assert.ok(edges(10,6,54,11)>0,'头部外轮廓');
  assert.ok(edges(21,22,31,32)>0,'内部五官边缘');
  assert.ok(edges(34,22,44,32)>0,'另一侧五官边缘');
  assert.equal(edges(18,38,46,50),0,'平坦区域保持透明');
});
