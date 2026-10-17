import test from 'node:test';
import assert from 'node:assert/strict';
import { flatSceneColors, illustrationColor,sceneColorTransform,subjectIllustrationColor } from '../src/scene-colors.mjs';

const pixels=(width,height,at)=>({width,height,data:Uint8ClampedArray.from(Array.from({length:width*height},(_,p)=>at(p%width,Math.floor(p/width))).flat())});

test('场景色块有界、确定且不改动原始照片像素',()=>{
  const input=pixels(48,32,(x,y)=>[x*5,y*7,(x+y)*3,255]),before=input.data.slice();
  const a=flatSceneColors(input),b=flatSceneColors(input);
  assert.deepEqual(a,b);
  assert.deepEqual(input.data,before);
  assert.ok(a.palette.length<=8&&a.palette.length>1);
  const colours=new Set();
  for(let i=0;i<a.data.length;i+=4)colours.add([...a.data.slice(i,i+3)].join(','));
  assert.ok(colours.size<=8);
});

test('整幅前景与背景均有颜色，大块区域保持可区分',()=>{
  const result=flatSceneColors(pixels(24,12,x=>x<12?[210,230,245,255]:[35,110,50,255]));
  const at=x=>[...result.data.slice((6*24+x)*4,(6*24+x)*4+4)];
  assert.notDeepEqual(at(4),at(20));
  assert.equal(at(4)[3],255);
  assert.equal(at(20)[3],255);
  assert.ok(at(20)[1]>at(20)[0]);
});

test('去除孤立碎色，同时保留透明间隙和原透明度',()=>{
  const input=pixels(9,9,(x,y)=>x===4&&y===4?[255,0,0,255]:x===3&&y===3?[255,0,0,0]:[40,120,55,x===6?127:255]);
  const out=flatSceneColors(input).data;
  const at=(x,y)=>[...out.slice((y*9+x)*4,(y*9+x)*4+4)];
  assert.deepEqual(at(4,4),at(5,5));
  assert.deepEqual(at(3,3),[0,0,0,0]);
  assert.equal(at(6,5)[3],127);
  assert.equal(flatSceneColors(pixels(2,2,()=>[255,10,20,0])).palette.length,0);
});

test('异常图片尺寸和色数被拒绝，避免无界计算',()=>{
  for(const input of [{width:0,height:1,data:[]},{width:1,height:1,data:[]},{width:401,height:400,data:[]}])assert.throws(()=>flatSceneColors(input),RangeError);
  assert.throws(()=>flatSceneColors(pixels(1,1,()=>[0,0,0,255]),20),RangeError);
});

test('插画配色保持绿蓝粉的区别，不把中性色和阴影混成灰色',()=>{
  const channels=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  const green=channels(illustrationColor([75,110,65]));
  const blue=channels(illustrationColor([80,130,190]));
  const pink=channels(illustrationColor([200,80,155]));
  assert.ok(green[1]-green[0]>20);
  assert.ok(blue[2]-blue[0]>20);
  assert.ok(pink[0]-pink[1]>20);
  for(const rgb of [[90,90,90],[170,170,166],[210,215,215]]) {
    const c=channels(illustrationColor(rgb,true));
    assert.ok(Math.max(...c)-Math.min(...c)>20);
  }
});

test('小片背景碎色被合并，大范围前后景仍有区分',()=>{
  const w=100,h=100;
  const image=pixels(w,h,(x,y)=>x<50?((x%10===4&&y%10===4)?[230,180,80,255]:[90,145,80,255]):[75,130,200,255]);
  const out=flatSceneColors(image).data;
  const at=(x,y)=>[...out.slice((y*w+x)*4,(y*w+x)*4+3)];
  assert.deepEqual(at(4,4),at(5,5));
  assert.notDeepEqual(at(25,50),at(75,50));
});

test('明确的白花不再被局部阴影涂成灰蓝，无颜色依据时采用轮廓内占优色',()=>{
  const shade=new Map([['#a0becd',80],['#fff9e9',20]]);
  assert.equal(subjectIllustrationColor({label:'白色花朵簇',color:'rose'},shade),'#fff9e9');
  assert.equal(subjectIllustrationColor({label:'粉色花朵'},shade),'#f1c4d4');
  assert.equal(subjectIllustrationColor({label:'相机',color:'rose'},shade),'#a0becd');
});

const layer=(source_bbox,bbox)=>({role:'main',source_bbox,bbox});
const board=layers=>({render_basis:'source_geometry',layers});

test('全图颜色与所有主体共享推荐取景变换，支持画面外裁切',()=>{
  const value=board([layer([.2,.2,.4,.6],[.1,.15,.5,.75]),layer([.5,.3,.7,.5],[.7,.3,1.1,.6])]);
  const before=structuredClone(value),t=sceneColorTransform(value);
  assert.ok(t);
  for(const l of value.layers)for(let k=0;k<4;k++)assert.ok(Math.abs(l.source_bbox[k]*(k%2?t.height:t.width)+(k%2?t.y:t.x)-l.bbox[k])<1e-10);
  assert.ok(t.x<0);
  assert.deepEqual(value,before);
  assert.deepEqual(sceneColorTransform(value,true),{x:0,y:0,width:1,height:1});
});

test('独立移动的旧主体或不可靠几何不叠加错误的整图颜色',()=>{
  assert.equal(sceneColorTransform(board([layer([0,0,.3,.4],[.1,0,.4,.4]),layer([.5,.5,1,1],[.5,.5,1,1])])),null);
  assert.equal(sceneColorTransform(board([])),null);
  assert.equal(sceneColorTransform(board([layer([0,0,0,.4],[0,0,.3,.4])])),null);
  assert.equal(sceneColorTransform({render_basis:'model',layers:[]}),null);
});
