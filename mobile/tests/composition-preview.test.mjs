import {test} from 'node:test';
import assert from 'node:assert/strict';
import {previewPlan,safePreviewImage,localReference} from '../src/composition-preview.mjs';

test('编辑计划仅携带构图动作与当前图的辨识特征，不把抽象几何或其他图号的特征送去替换主体',()=>{
  const proposal={goal:'保留主体',actions:['向右试移并检查背景'],storyboard:{aspect:'portrait',layers:[
    {label:'动物主体',role:'main',bbox:[.1,.1,.8,.9],evidence_photo_ids:['photo1'],identity_features:['尖耳','相机'],outline:'not copied'},
    {evidence_photo_ids:['photo2'],identity_features:['其他图特征']}
  ]}};
  const plan=previewPlan(proposal);
  assert.deepEqual(plan.preserve_features,['尖耳','相机']);
  assert.equal(plan.aspect,'portrait');assert.equal(plan.reference_photo_id,'photo1');
  assert.deepEqual(plan.layout,[{label:'动物主体',role:'main',bbox:[.1,.1,.8,.9]}]);
  assert.ok(!JSON.stringify(plan).includes('outline'));
  assert.equal(previewPlan({goal:' ',actions:[]}),null);
  assert.equal(previewPlan(proposal,'photo7'),null);
});
test('预演只接受明确PNG数据，不加载模型返回的网址、SVG或脚本',()=>{
  assert.equal(safePreviewImage('data:image/png;base64,YWJj'),'data:image/png;base64,YWJj');
  for(const value of ['https://evil.invalid/x.png','data:image/svg+xml,<svg/>','javascript:alert(1)',null])
    assert.equal(safePreviewImage(value),'');
  assert.equal(localReference('blob:https://local.invalid/id','https://local.invalid'),true);
  assert.equal(localReference('https://other.invalid/private','https://local.invalid'),false);
});
