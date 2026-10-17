import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readAnalysis } from '../src/analysis-stream.mjs';

const final = { request_id: 'local-id', analysis_mode: 'demo', result: {
  scene: { subject: '树木' }, recommendation: { shooting_mode: '自动' },
  composition: { proposals: [{
    sketch: { elements: [{ source_bbox: { x: .1, y: .2, width: .3, height: .6 },
      identity_features: ['分叉树干'] }] },
    framing_plan: { keep: ['分叉树干'], remove: ['边缘杂物'] },
  }] },
} };
function response(events, { tail = '', split = 1 } = {}) {
  const bytes = new TextEncoder().encode(events.map(e => JSON.stringify(e) + '\n').join('') + tail);
  return new Response(new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += split) controller.enqueue(bytes.slice(i, i + split));
    controller.close();
  } }), { headers: { 'content-type': 'application/x-ndjson' } });
}

test('增量显示中文场景与参数，最终仍返回完整结果', async () => {
  const events = [{ type: 'progress', message: '正在识别画面' },
    { type: 'partial', kind: 'scene', value: { subject: '树木' } },
    { type: 'partial', kind: 'parameters', value: { shooting_mode: '自动' } },
    { type: 'activity', chars: 128, phase: 'content' },
    { type: 'result', ...final }];
  const observed = [];
  assert.deepEqual(await readAnalysis(response(events), e => observed.push(e)), final);
  assert.deepEqual(observed.map(e => e.type), events.map(e => e.type));
});

test('读取尚未关闭的连接时，部分结果已经到达前端', async () => {
  let streamController;
  const stream = new ReadableStream({ start(controller) { streamController = controller; } });
  let partialResolve;
  const partialArrived = new Promise(resolve => partialResolve = resolve);
  const reading = readAnalysis(new Response(stream, { headers: { 'content-type': 'application/x-ndjson' } }),
    event => { if (event.type === 'partial') partialResolve(event.value); });
  streamController.enqueue(new TextEncoder().encode(JSON.stringify({ type: 'partial', kind: 'scene', value: { subject: '树' } }) + '\n'));
  assert.deepEqual(await partialArrived, { subject: '树' });
  streamController.enqueue(new TextEncoder().encode(JSON.stringify({ type: 'result', ...final }) + '\n'));
  streamController.close();
  assert.deepEqual(await reading, final);
});

test('旧服务普通JSON可在同次响应中兼容，无需再次上传', async () => {
  assert.deepEqual(await readAnalysis(new Response(JSON.stringify(final), {
    headers: { 'content-type': 'application/json' },
  }), () => assert.fail('旧JSON没有增量事件')), final);
});

test('中途断流不能把部分参数当成完整方案', async () => {
  await assert.rejects(readAnalysis(response([{ type: 'partial', kind: 'parameters', value: {} }]), () => {}), /未完成/);
});

test('错误事件终止读取，且不触发任何重发逻辑', async () => {
  await assert.rejects(readAnalysis(response([{ type: 'error', detail: '分析失败，请稍后重试。' }]), () => {}), /分析失败/);
});

test('畸形事件与超长单行有固定错误提示', async () => {
  await assert.rejects(readAnalysis(response([], { tail: 'invalid-private-remote-text\n' }), () => {}), /响应格式/);
  await assert.rejects(readAnalysis(response([], { tail: 'x'.repeat(2_100_000), split: 65536 }), () => {}), /响应格式/);
});

test('终止结果缺少必要字段时不进入历史', async () => {
  await assert.rejects(readAnalysis(response([{ type: 'result', request_id: 'invalid' }]), () => {}), /响应格式/);
});
