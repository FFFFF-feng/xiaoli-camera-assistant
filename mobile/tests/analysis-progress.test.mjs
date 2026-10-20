import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialAnalysisProgress, advanceAnalysisProgress } from '../src/analysis-progress.mjs';

const timing = (stage, status = 'complete') => ({ type: 'timing', stage, status });
const partial = (kind, ready = false) => ({ type: 'partial', kind, ready });
const run = events => events.reduce(advanceAnalysisProgress, initialAnalysisProgress());

test('等待、心跳和模型字符数不会冒充完成百分比', () => {
  const state = run([
    { type: 'heartbeat', elapsed_seconds: 90 },
    { type: 'activity', stage: 'composition_layout', phase: 'content', chars: 99999 },
  ]);
  assert.equal(state.percent, 0);
  assert.match(state.message, /规划构图/);
});

test('参数先返回时只计入自己的工作，仍明确提示构图未完成', () => {
  const state = run([
    timing('upload'), timing('image_preprocessing'), partial('scene'),
    timing('parameter_retrieval'), partial('parameters'),
  ]);
  assert.equal(state.percent, 53);
  assert.match(state.message, /继续整理构图/);
  assert.ok(!state.completed.includes('composition'));
});

test('并行分支乱序、重复事件和格式重试不重复计分或倒退', () => {
  let state = initialAnalysisProgress();
  for (const event of [
    timing('image_preprocessing'), partial('parameters'), timing('composition_layout'),
    partial('scene'), partial('parameters'), timing('composition_layout'),
    { type: 'activity', stage: 'vision', phase: 'request_started' },
  ]) {
    const previous = state;
    state = advanceAnalysisProgress(state, event);
    assert.ok(state.percent >= previous.percent);
    assert.ok(state.percent < 100);
  }
  assert.equal(state.percent, 63);
});

test('构图文字和未通过前端校验的画面不冒充已完成构图', () => {
  const text = run([partial('composition'), partial('composition_ready')]);
  assert.ok(!text.completed.includes('composition'));
  assert.ok(!text.completed.includes('contours'));
  const ready = advanceAnalysisProgress(text, partial('composition_ready', true));
  assert.ok(ready.completed.includes('composition'));
  assert.match(ready.message, /推荐构图已就绪/);
});

test('只有最终完整结果到达100%，提前完成提示、失败和断流都不能完成', () => {
  let state = run([
    timing('upload'), timing('image_preprocessing'), partial('scene'),
    timing('composition_retrieval'), timing('composition_observation'),
    timing('composition_contours', 'failed'), timing('composition_layout'),
    timing('composition'), partial('parameters'),
    { type: 'progress', message: '分析完成。' },
  ]);
  assert.equal(state.percent, 95);
  assert.match(state.message, /汇总/);
  assert.equal(advanceAnalysisProgress(state, { type: 'error' }).percent, 95);
  state = advanceAnalysisProgress(state, { type: 'result' });
  assert.equal(state.percent, 100);
  assert.match(state.message, /已整理完成/);
});

test('阶段开始立即更新说明，重复字符事件不刷屏，动态最多保留四条', () => {
  let state = run([
    { type: 'progress', stage: 'composition_contours', message: '正在提取主体轮廓…' },
    ...Array.from({ length: 30 }, (_, chars) => ({ type: 'activity', stage: 'composition_layout', phase: 'content', chars })),
  ]);
  assert.equal(state.history.length, 2);
  for (const message of ['准备画面', '校验细节', '检查建议', '汇总方案', '整理展示']) {
    state = advanceAnalysisProgress(state, { type: 'progress', message });
  }
  assert.equal(state.history.length, 4);
  assert.equal(state.history.at(-1), '整理展示');
  assert.deepEqual(initialAnalysisProgress().completed, []);
  assert.equal(initialAnalysisProgress().percent, 0);
});
