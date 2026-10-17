import { colorizeScenePixels } from './scene-colors.mjs';
import { extendSceneBackground } from './scene-extension.mjs';

// Shared by the worker and compatibility path; do not substitute a cheaper image algorithm.
export function runSceneRenderJob(job,createCanvas) {
  if(job.kind==='colors')return colorizeScenePixels(job.pixels,job.board,createCanvas);
  if(job.kind==='extension')return extendSceneBackground(job.pixels,job.transform,job.width,job.height,job.directions);
  throw new Error('未知的本地绘图任务');
}
