import { test } from 'node:test';
import assert from 'node:assert/strict';
import { usableSketch, cameraMove, openSpace } from '../src/composition-sketch.mjs';

const drawing = () => ({ aspect: 'portrait', caption: '树冠完整入画', camera_action: 'farther',
  camera_instruction: '后退一点，检查树冠四周余量', horizon_y: null,
  elements: [{ kind: 'tree', label: '树木', role: 'main', bbox: [.2, .12, .7, .9] }] });

test('旧记录没有图时保留文字入口，合法示意可显示', () => {
  assert.equal(usableSketch(undefined), null);
  assert.equal(usableSketch(null), null);
  const value = drawing(); assert.equal(usableSketch(value), value);
});

test('拒绝越界、非数值和不完整主体的绘图数据', () => {
  for (const bbox of [[0, 0, Infinity, 1], [0, 0, '1', 1], [0, 0, 2, 1], [.5, 0, .3, 1], [0, 0, 1]]) {
    const value = drawing(); value.elements[0].bbox = bbox;
    assert.equal(usableSketch(value), null);
  }
  const value = drawing(); value.elements[0].role = 'context';
  assert.equal(usableSketch(value), null);
});

test('只允许固定线稿类型，机位箭头符合动作方向', () => {
  const value = drawing(); value.elements[0].kind = '<svg onload=alert(1)>';
  assert.equal(usableSketch(value), null);
  assert.ok(cameraMove('left').x < cameraMove('left').startX);
  assert.ok(cameraMove('right').x > cameraMove('right').startX);
  assert.ok(cameraMove('closer').y < cameraMove('closer').startY);
  assert.ok(cameraMove('farther').y > cameraMove('farther').startY);
  assert.ok(cameraMove('lower').y > cameraMove('lower').startY);
});

test('主题、旁白和物种形象可保留，未知图形数据不会进入绘制', () => {
  const value = drawing();
  Object.assign(value, { theme: '树下的片刻', mood: '宁静', narration: '用天空衬托完整的树冠。', space_note: '右侧保留天空' });
  Object.assign(value.elements[0], { appearance: 'broadleaf', facing: 'front', description: '完整树冠' });
  assert.equal(usableSketch(value), value);
  value.elements[0].appearance = 'arbitrary-svg';
  assert.equal(usableSketch(value), null);
  value.elements[0].appearance = 'pine'; value.narration = { html: 'bad' };
  assert.equal(usableSketch(value), null);
});

test('留白区域避开主角和环境，不把树木涂成空白', () => {
  const elements = [{ bbox: [.54,.27,.8,.9] }, { bbox: [.06,.1,.4,.84] }];
  const space = openSpace(elements);
  assert.ok(space.w * space.h > .08);
  for (const { bbox: [x1,y1,x2,y2] } of elements) {
    assert.ok(space.x+space.w <= x1 || space.x >= x2 || space.y+space.h <= y1 || space.y >= y2);
  }
  assert.equal(openSpace([{ bbox: [0,0,1,1] }]).w, 0);
});
