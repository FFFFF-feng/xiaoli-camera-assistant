import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fieldActionCard,uniqueAdvice} from '../src/field-actions.mjs';

test('操作卡复用已有字段、顺序不变，去掉完全重复建议但不删限制条件',()=>{
  const actions=['向左移半步，仅在岸边安全位置试拍。',' 向左移半步，仅在岸边安全位置试拍。 ',
    '保持当前距离；无法后退时不要强行移动。','向左移半步，仅在岸边安全位置试拍'];
  const framing={diagnosis:'树干与主体重叠。',success_check:'主体关键部位完整。',edge_check:'主体关键部位完整',background_control:'核对背景重叠。'};
  const card=fieldActionCard({goal:'突出水面',actions},{changes:[{benefit:'分离主体与背景。'}]},framing);
  assert.equal(card.problem,framing.diagnosis);assert.equal(card.actions.length,2);
  assert.equal(card.actions[0],actions[0]);assert.equal(card.actions[1],actions[2]);
  assert.deepEqual(card.checks,['主体关键部位完整。']);
  assert.equal(card.benefit,'分离主体与背景。');
});
test('保留原布局不得把建议收益描述成已经实现的新构图效果',()=>{
  const card=fieldActionCard({actions:['保持当前机位，不裁剪。']},
    {layout_mode:'source_preserving',changes:[{problem:'原取景',benefit:'主体变大。'}]});
  assert.match(card.benefit,/保留原始布局/);assert.match(card.benefit,/未模拟/);
  assert.doesNotMatch(card.benefit,/主体变大/);assert.equal(card.actions[0],'保持当前机位，不裁剪。');
});
test('没有绘图数据时仍有操作卡，且不声称已经生成目标图',()=>{
  const card=fieldActionCard({goal:'核对边缘',actions:['检查边缘。']});
  assert.equal(card.problem,'核对边缘');assert.match(card.benefit,/仅有文字建议/);
  assert.equal(fieldActionCard(null),null);assert.deepEqual(uniqueAdvice([null,{},'  ',42]),[]);
});
test('保留所有动作以便折叠查看，不在适配时截去第四条及后续安全条件',()=>{
  const actions=['先确认主体','再调整取景','检查背景','注意脚下台阶','无法移动则留在原地'];
  assert.deepEqual(fieldActionCard({actions}).actions,actions);
  assert.deepEqual(fieldActionCard({actions:[]},{changes:[{adjustment:'后退一点。'}],distance_instruction:'核对安全位置。'}).actions,
    ['后退一点。','核对安全位置。']);
});
