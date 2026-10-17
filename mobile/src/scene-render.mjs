import { scenePhotoPixels,scenePixelsUrl } from './scene-colors.mjs';
import { runSceneRenderJob } from './scene-render-job.mjs';

// Private, per-tab memory only. Completed work is limited by both entry count and bytes.
export function createMemoryTasks({maxEntries=4,maxBytes=8*1024*1024,maxPending=4,weight=(value,key)=>
  key.length*2+(value?.url?.length||0)*2+(value?.pixels?.data?.byteLength||0)+JSON.stringify(value?.fills||[]).length*2}={}) {
  const completed=new Map(),pending=new Map();let bytes=0;
  async function get(key,load) {
    if(completed.has(key)) {
      const item=completed.get(key);completed.delete(key);completed.set(key,item);return item.value;
    }
    if(pending.has(key))return pending.get(key);
    if(pending.size>=maxPending) {
      await Promise.race([...pending.values()].map(task=>task.catch(()=>{})));
      return get(key,load);
    }
    const task=Promise.resolve().then(load).then(value=>{
      const size=weight(value,key);
      if(Number.isFinite(size)&&size>=0&&size<=maxBytes) {
        completed.set(key,{value,size});bytes+=size;
        while(completed.size>maxEntries||bytes>maxBytes) {
          const oldest=completed.keys().next().value;bytes-=completed.get(oldest).size;completed.delete(oldest);
        }
      }
      return value;
    }).finally(()=>pending.delete(key));
    pending.set(key,task);return task;
  }
  return {get};
}

function browserWorker() {
  if(typeof Worker!=='function'||typeof OffscreenCanvas!=='function'||typeof Path2D!=='function')return null;
  return new Worker(new URL('./scene-render.worker.mjs',import.meta.url),{type:'module'});
}

export function createSceneWorkerClient({createWorker=browserWorker,fallback=runSceneRenderJob,timeoutMs=20000}={}) {
  let worker,disabled=false,nextId=0;const pending=new Map();
  function disable() {
    disabled=true;worker?.terminate();worker=undefined;
    for(const item of pending.values()){clearTimeout(item.timer);item.reject(new Error('本地绘图回退'));}
    pending.clear();
  }
  async function run(job) {
    if(!disabled&&!worker) {
      try {
        worker=createWorker();
        if(!worker)disabled=true;
        else {
          worker.onmessage=({data})=>{
            const item=pending.get(data?.id);if(!item)return;
            pending.delete(data.id);clearTimeout(item.timer);
            if(data.error){item.reject(new Error('本地绘图回退'));disable();}
            else item.resolve(data.result);
          };
          worker.onerror=disable;worker.onmessageerror=disable;
        }
      } catch {disable();}
    }
    if(!worker)return fallback(job);
    try {
      return await new Promise((resolve,reject)=>{
        const id=++nextId,timer=setTimeout(disable,timeoutMs);pending.set(id,{resolve,reject,timer});
        // Structured clone preserves the cached source pixels; never transfer their ArrayBuffer.
        try {worker.postMessage({id,job});}catch {disable();}
      });
    } catch {return fallback(job);}
  }
  return {run};
}

// Only source geometry and object colour evidence affect the sampled palette.
function colorGeometry(board) {
  return {layers:board.layers.map(layer=>({kind:layer.kind,label:layer.label,representation:layer.representation,
    source_bbox:layer.source_bbox,outline:layer.outline,outline_style:layer.outline_style,contours:layer.contours,holes:layer.holes}))};
}

export function createSceneRenderer({decode=scenePhotoPixels,encode=scenePixelsUrl,process=createSceneWorkerClient().run}={}) {
  const colorsCache=createMemoryTasks(),extensionCache=createMemoryTasks({weight:(value,key)=>key.length*2+(value?.length||0)*2});
  function colors(source,board) {
    const geometry=JSON.stringify(colorGeometry(board)),key=JSON.stringify([source,geometry]);
    return colorsCache.get(key,async()=>{
      const decoded=await decode(source);
      const result=await process({kind:'colors',pixels:decoded.pixels,board:JSON.parse(geometry)});
      return {...result,aspect:decoded.aspect,url:encode(result.pixels),key};
    });
  }
  function extension(scene,transform,aspect,directions) {
    if(!Number.isFinite(aspect)||aspect<=0)return Promise.resolve(null);
    const target={x:transform.x,y:transform.y,width:transform.width,height:transform.height};
    const edges=directions.map(d=>({side:d.side,position:d.position,drift:d.drift,curve:d.curve}));
    // Vue wraps plain objects in Proxies; send plain metadata around the untransferred pixel view.
    const pixels={data:scene.pixels.data,width:scene.pixels.width,height:scene.pixels.height};
    const key=JSON.stringify([scene.key,target.x,target.y,target.width,target.height,aspect,
      edges.map(d=>[d.side,d.position,d.drift,d.curve])]);
    return extensionCache.get(key,async()=>{
      const result=await process({kind:'extension',pixels,transform:target,
        width:Math.max(1,Math.round(720*Math.min(1,aspect))),height:Math.max(1,Math.round(720/Math.max(1,aspect))),
        directions:edges});
      return result?encode(result):null;
    });
  }
  return {colors,extension};
}

// Each component owns a revision; sharing the underlying work must not share its UI lifetime.
export function createLatestTask() {
  let revision=0;
  return {
    cancel(){revision++;},
    async run(load,accept,reject=()=>{},finish=()=>{}) {
      const current=++revision;
      try {const value=await load();if(current===revision)accept(value);}
      catch(error){if(current===revision)reject(error);}
      finally {if(current===revision)finish();}
    },
  };
}

export const sceneRenderer=createSceneRenderer();
