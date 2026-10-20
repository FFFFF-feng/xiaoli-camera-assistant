import test from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryTasks, createSceneRenderer, createSceneWorkerClient, createLatestTask } from '../src/scene-render.mjs';
import { runSceneRenderJob } from '../src/scene-render-job.mjs';
import { extendSceneBackground } from '../src/scene-extension.mjs';

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const pixels=()=>({width:4,height:4,data:Uint8ClampedArray.from(Array.from({length:16},(_,i)=>[i<8?200:40,i<8?220:100,80,255]).flat())});
const board=()=>({layers:[{kind:'flower',label:'白色花朵',representation:'silhouette',source_bbox:[0,0,1,1],outline:[[0,0],[1,0],[1,1],[0,1]],outline_style:'curved',contours:[]}],intent:'建议'});
const transform={x:.1,y:.1,width:.8,height:.8};

test('内存任务合并同键并发，失败可以重试，成功结果保留到有界LRU中',async()=>{
  const cache=createMemoryTasks({maxEntries:2,maxBytes:10,weight:value=>value.length});
  const pending=deferred();let calls=0;
  const a=cache.get('a',()=>{calls++;return pending.promise;}),b=cache.get('a',()=>{calls++;return 'bad';});
  pending.resolve('aaa');assert.deepEqual(await Promise.all([a,b]),['aaa','aaa']);assert.equal(calls,1);
  await cache.get('b',()=> 'bbb');await cache.get('a',()=> 'bad');await cache.get('c',()=> 'ccc');
  assert.equal(await cache.get('b',()=> 'new'), 'new', '最少使用的b已被淘汰');
  await assert.rejects(cache.get('failed',()=>Promise.reject(new Error('decode'))),/decode/);
  assert.equal(await cache.get('failed',()=> 'retry'),'retry');
  await cache.get('large',()=> 'more than ten bytes');
  assert.equal(await cache.get('large',()=> 'again'),'again','超出字节上限的结果不能留在缓存');
});

test('缓存按字节淘汰，独立在途任务数量有上限且等待后仍合并相同请求',async()=>{
  const cache=createMemoryTasks({maxEntries:10,maxBytes:5,maxPending:1,weight:value=>value.length});
  await cache.get('a',()=> 'aaaa');await cache.get('b',()=> 'bbbb');
  assert.equal(await cache.get('a',()=> 'new'),'new','字节上限先于条数上限生效');
  const pending=deferred();let calls=0;
  const first=cache.get('first',()=>{calls++;return pending.promise;});
  const second=cache.get('second',()=>{calls++;return 'two';});
  const same=cache.get('second',()=>{calls++;return 'duplicate';});
  await Promise.resolve();assert.equal(calls,1);
  pending.resolve('one');assert.deepEqual(await Promise.all([first,second,same]),['one','two','two']);assert.equal(calls,2);
});

test('配色按来源与实际轮廓字段去重，说明文字不触发重算，坐标/颜色证据改变会重算',async()=>{
  let decodes=0,jobs=0;const input=pixels();
  const renderer=createSceneRenderer({decode:async()=>{decodes++;return {aspect:1,pixels:input};},
    process:async job=>{jobs++;return {pixels:job.pixels,fills:[['#fff9e9']]};},encode:()=> 'data:image/png;base64,same'});
  const original=board();const [first,second]=await Promise.all([renderer.colors('blob:first',original),renderer.colors('blob:first',structuredClone(original))]);
  assert.equal(first,second);assert.equal(jobs,1);assert.equal(decodes,1);
  await renderer.colors('blob:first',{...original,intent:'仅文字改变'});assert.equal(jobs,1);
  const moved=board();moved.layers[0].source_bbox[0]=.1;await renderer.colors('blob:first',moved);
  const label=board();label.layers[0].label='红色花朵';await renderer.colors('blob:first',label);
  const contour=board();contour.layers[0].contours=[[[0,0],[.5,0],[.5,.5]]];await renderer.colors('blob:first',contour);
  const holes=board();holes.layers[0].holes=[[[.1,.1],[.3,.1],[.2,.3]]];await renderer.colors('blob:first',holes);
  await renderer.colors('blob:second',original);assert.equal(jobs,6);assert.deepEqual(input,pixels());
});

test('背景缓存包含来源、目标变换、画幅与边界方向，并且不会转移原像素所有权',async()=>{
  let jobs=0;const original=pixels();const renderer=createSceneRenderer({decode:async()=>({aspect:1,pixels:original}),
    process:async job=>{jobs++;return job.kind==='colors'?{pixels:job.pixels,fills:[]}:{...job.pixels};},encode:()=> 'data:image/png;base64,result'});
  const first=await renderer.colors('blob:a',board());
  await Promise.all([renderer.extension(first,transform,1,[]),renderer.extension(first,{...transform},1,[])]);
  assert.equal(jobs,2);
  await renderer.extension(first,{...transform,x:.2},1,[]);
  await renderer.extension(first,transform,4/3,[]);
  await renderer.extension(first,transform,1,[{side:0,position:1,drift:.2,curve:0}]);
  const second=await renderer.colors('blob:b',board());await renderer.extension(second,transform,1,[]);
  assert.equal(jobs,7);assert.deepEqual(first.pixels,original);assert.equal(original.data.byteLength,64);
});

test('角色与遮挡层次改变需要重取色，环境参考与物体透明层分别编码',async()=>{
  let jobs=0;const encoded=[];
  const renderer=createSceneRenderer({decode:async()=>({aspect:1,pixels:pixels()}),
    process:async job=>{jobs++;return {pixels:job.pixels,contextPixels:{...job.pixels,data:job.pixels.data.slice()},fills:[]};},
    encode:value=>{encoded.push(value);return `png-${encoded.length}`;}});
  const original=board();original.layers[0].role='main';original.layers[0].depth=1;
  const value=await renderer.colors('blob:layers',original);
  assert.notEqual(value.url,value.contextUrl);assert.equal(encoded.length,2);
  const background=structuredClone(original);background.layers[0].role='background';
  await renderer.colors('blob:layers',background);
  const closer=structuredClone(original);closer.layers[0].depth=2;
  await renderer.colors('blob:layers',closer);
  assert.equal(jobs,3);
});

test('异步等待期间更改输入不能把新几何写入旧缓存键',async()=>{
  const jobs=[];const renderer=createSceneRenderer({decode:async()=>({aspect:1,pixels:pixels()}),
    process:async job=>{jobs.push(job);return job.kind==='colors'?{pixels:job.pixels,fills:[]}:job.pixels;},encode:()=> 'png'});
  const scene=await renderer.colors('blob:one',board()),target={...transform},directions=[{side:0,position:1,drift:0,curve:0}];
  const first=renderer.extension(scene,target,1,directions);target.x=.3;directions[0].drift=1;await first;
  assert.equal(jobs[1].transform.x,.1);assert.equal(jobs[1].directions[0].drift,0);
  await renderer.extension(scene,transform,1,[{side:0,position:1,drift:0,curve:0}]);assert.equal(jobs.length,2);
});

test('Vue包裹的像素元数据先转为普通对象，背景计算仍可发给Worker',async()=>{
  const renderer=createSceneRenderer({decode:async()=>({aspect:1,pixels:pixels()}),process:async job=>{
    assert.doesNotThrow(()=>structuredClone(job));return job.kind==='colors'?{pixels:job.pixels,fills:[]}:job.pixels;
  },encode:()=> 'png'});
  const scene=await renderer.colors('blob:proxy',board());
  await renderer.extension({...scene,pixels:new Proxy(scene.pixels,{})},transform,1,[]);
});

test('Worker路由与本地背景算法像素一致，输入像素不变',()=>{
  const input=pixels(),before=input.data.slice();
  const job={kind:'extension',pixels:input,transform,width:24,height:24,directions:[]};
  assert.deepEqual(runSceneRenderJob(job),extendSceneBackground(input,transform,24,24,[]));
  assert.deepEqual(input.data,before);
});

test('不支持Worker时使用同一算法，Worker失败只回退一次且不永久缓存失败',async()=>{
  let fallbacks=0;const fallback=async job=>{fallbacks++;return job.value;};
  const unsupported=createSceneWorkerClient({createWorker:()=>null,fallback});
  assert.equal(await unsupported.run({value:12}),12);
  const failed=createSceneWorkerClient({createWorker:()=>({postMessage(){throw new Error('unsupported canvas');},terminate(){}}),fallback});
  assert.equal(await failed.run({value:21}),21);assert.equal(await failed.run({value:22}),22);assert.equal(fallbacks,3);
});

test('Worker只克隆输入，不detach缓存数组，成功与error响应各自配对',async()=>{
  let fake;const client=createSceneWorkerClient({createWorker:()=>fake={postMessage(message,transfer){
    assert.equal(transfer,undefined);assert.equal(message.job.pixels.data.byteLength,64);
    queueMicrotask(()=>fake.onmessage({data:{id:message.id,result:{pixels:message.job.pixels}}}));},terminate(){}},fallback:()=>{throw new Error('不应回退');}});
  const input=pixels();const result=await client.run({pixels:input});assert.deepEqual(result.pixels,input);assert.equal(input.data.byteLength,64);
});

test('Worker响应按请求配对，后台崩溃或超时后每个任务只回退一次',async()=>{
  let fake;const jobs=[],fallbacks=[];
  const client=createSceneWorkerClient({createWorker:()=>fake={postMessage(message){jobs.push(message);},terminate(){}},
    fallback:job=>{fallbacks.push(job.value);return job.value;},timeoutMs:1000});
  const first=client.run({value:'first'}),second=client.run({value:'second'});
  fake.onmessage({data:{id:jobs[1].id,result:'second-worker'}});fake.onmessage({data:{id:jobs[0].id,error:true}});
  assert.deepEqual(await Promise.all([first,second]),['first','second-worker']);assert.deepEqual(fallbacks,['first']);
  let terminated=0;const timeout=createSceneWorkerClient({createWorker:()=>({postMessage(){},terminate(){terminated++;}}),
    fallback:job=>job.value,timeoutMs:5});
  assert.equal(await timeout.run({value:'timeout-fallback'}),'timeout-fallback');assert.equal(terminated,1);
});

test('切换图片或卸载后，晚到的旧配色与背景不会覆盖当前结果',async()=>{
  const latest=createLatestTask(),old=deferred(),fresh=deferred();let shown='';
  const a=latest.run(()=>old.promise,value=>{shown=value;}),b=latest.run(()=>fresh.promise,value=>{shown=value;});
  fresh.resolve('new');await b;old.resolve('old');await a;assert.equal(shown,'new');
  const final=deferred();const c=latest.run(()=>final.promise,value=>{shown=value;});latest.cancel();final.resolve('after-unmount');await c;assert.equal(shown,'new');
});
