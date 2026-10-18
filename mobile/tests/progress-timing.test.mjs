import {test} from 'node:test';
import assert from 'node:assert/strict';
import {liveElapsed,fixedEventSeconds,statusSeconds} from '../src/progress-timing.mjs';

test('总用时来自单调时钟并随等待递增，异常时间不会倒退为负数',()=>{
  assert.equal(liveElapsed(1000,1500),.5);
  assert.equal(liveElapsed(1000,9000),8);
  assert.equal(liveElapsed(2000,1000),0);
  assert.equal(liveElapsed(NaN,1000),0);
  let last=-1;
  for(const now of [1000,1250,1750,2400,4000]) {
    const value=liveElapsed(1000,now);
    assert.ok(value>=last);last=value;
  }
});

test('事件时刻是固定记录值，重复渲染不会把它伪装成持续增长的阶段用时',()=>{
  const event={elapsed_seconds:37.33};
  assert.equal(fixedEventSeconds(event.elapsed_seconds),37.33);
  assert.equal(fixedEventSeconds(event.elapsed_seconds),37.33);
  assert.equal(fixedEventSeconds(undefined),0);
  assert.equal(fixedEventSeconds(-1),0);
  assert.equal(fixedEventSeconds(Infinity),0);
});

test('当前状态持续时间由实时总用时与状态开始时刻计算，并保持有界',()=>{
  assert.ok(Math.abs(statusSeconds(41.2,37.3)-3.9)<1e-9);
  assert.equal(statusSeconds(37.3,37.3),0);
  assert.equal(statusSeconds(1,37.3),0);
  assert.equal(statusSeconds(NaN,1),0);
});
