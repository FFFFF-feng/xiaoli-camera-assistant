import { runSceneRenderJob } from './scene-render-job.mjs';

self.onmessage=({data:{id,job}})=>{
  try {
    if(typeof OffscreenCanvas!=='function'||typeof Path2D!=='function')throw new Error('unsupported canvas');
    const result=runSceneRenderJob(job,()=>new OffscreenCanvas(1,1));
    self.postMessage({id,result});
  } catch {
    // No photo data or browser diagnostics in error messages; the main thread can use Canvas.
    self.postMessage({id,error:true});
  }
};
