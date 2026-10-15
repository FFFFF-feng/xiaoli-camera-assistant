import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lineArtPixels, fitPhotoBox, embeddedInMain, sceneLayout } from '../src/sketch-trace.mjs';

test('建筑、树木和远山始终使用同一幅场景，不因各自建议框而分块移动', () => {
  const elements=[{role:'main',source_bbox:[.1,.3,.6,.85],bbox:[.05,.3,.45,.9]},
    {role:'context',source_bbox:[.3,.5,.95,1],bbox:[.1,.5,.7,.9]},
    {role:'context',source_bbox:[0,.1,1,.4],bbox:[.1,.1,.9,.3]}];
  for(const reframe of [false,true]) {
    const layout=sceneLayout(1.5,4/3,elements,reframe);
    const image=layout.imageBox, w=image[2]-image[0],h=image[3]-image[1];
    assert.ok(Math.abs(w*(4/3)/h-1.5)<1e-10,'整张照片等比');
    for(let i=0;i<elements.length;i++) for(let k=0;k<4;k++) {
      const expected=(k%2 ? image[1] : image[0])+elements[i].source_bbox[k]*(k%2 ? h : w);
      assert.ok(Math.abs(layout.boxes[i][k]-expected)<1e-10,'每个角共用同一变换');
    }
    const changed=elements.map(e=>e.role==='context' ? {...e,bbox:[.05,.05,.95,.95]} : e);
    assert.deepEqual(sceneLayout(1.5,4/3,changed,reframe),layout,'独立环境目标框不搬动实景');
    assert.ok(layout.boxes.every(b=>b.every(v=>v>=-1e-10 && v<=1+1e-10)),'保留所有已标记景物');
  }
});

test('未拍到区域单独记录，不能当作照片里的留白；缺失区域资料时保留完整现场', () => {
  const elements=[{role:'main',source_bbox:[.2,.2,.8,.8],bbox:[.4,.4,.6,.6]}];
  const layout=sceneLayout(2,1,elements,true);
  const area=layout.uncovered.reduce((n,b)=>n+(b[2]-b[0])*(b[3]-b[1]),0);
  assert.ok(area>.5);
  const [x1,y1,x2,y2]=layout.imageBox;
  assert.ok(Math.abs(area+(x2-x1)*(y2-y1)-1)<1e-10);
  const incomplete=[...elements,{role:'context',bbox:[.1,.1,.4,.4]}];
  assert.deepEqual(sceneLayout(2,1,incomplete,true),sceneLayout(2,1,incomplete,false));
  assert.equal(sceneLayout(2,1,incomplete).boxes[1],null);
});

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
