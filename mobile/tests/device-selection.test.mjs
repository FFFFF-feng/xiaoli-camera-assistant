import { test } from 'node:test';
import assert from 'node:assert/strict';
import { candidateReferenceLenses, compatibleLenses, deviceSelection, exactDeviceMatch, linkedCameraSettings, referenceCameraMounts, referenceLensSettings, searchDevices, sensorLabel } from '../src/device-selection.mjs';

test('知识库镜头不再只有名称，焦距与光圈端点实际联动', () => {
  const lens = { reference_id: 'source', mount_keys: ['sony_e'], parameter_linkage: true,
    focal_min_mm: 18, focal_max_mm: 55, max_aperture_wide: 3.5, max_aperture_tele: 5.6,
    sensor_formats: ['APS-C'] };
  assert.equal(referenceLensSettings({ crop_factor: 1.5 }, lens, undefined).focal_length_mm, 18);
  assert.equal(referenceLensSettings({ crop_factor: 1.5 }, lens, 18).max_aperture, 3.5);
  assert.equal(referenceLensSettings({ crop_factor: 1.5 }, lens, 35).max_aperture, 5.6);
  assert.equal(referenceLensSettings({ crop_factor: 1.5 }, lens, 500).equivalent_focal_length_mm, 82.5);
  assert.equal(referenceLensSettings({}, { ...lens, parameter_linkage: false }, 50), null);
  assert.deepEqual(candidateReferenceLenses({ mount: 'sony_e', sensor_format: '全画幅' }, [lens]), []);
});

test('知识库镜头只按明确卡口做参考候选，不提升为精确兼容', () => {
  const refs = [{ reference_id: 'sony', mount_keys: ['sony_e'] }, { reference_id: 'nikon', mount_keys: ['nikon_f'] }];
  const camera = { capability_level: 'catalog', mount: 'unknown', catalog_mount_labels: ['Nikon F AF'] };
  assert.deepEqual(referenceCameraMounts(camera), ['nikon_f']);
  assert.deepEqual(candidateReferenceLenses(camera, refs).map(x => x.reference_id), ['nikon']);
  assert.deepEqual(candidateReferenceLenses({mount: 'canon_rf'}, refs, 'sony_e'), []);
  assert.deepEqual(candidateReferenceLenses({mount: 'unknown'}, refs), []);
  assert.deepEqual(candidateReferenceLenses({mount: 'unknown'}, refs, 'sony_e').map(x => x.reference_id), ['sony']);
  assert.deepEqual(compatibleLenses(camera, []), []);
});

const profiles = [
  { profile_id: 'generic_phone', display_name: '未知手机' },
  { profile_id: 'iphone15', display_name: 'Apple iPhone 15', model: 'iPhone 15', aliases: ['苹果15'] },
  { profile_id: 'xiaomi14', display_name: '小米 14', model: 'Xiaomi 14', aliases: ['小米14'] },
];

test('搜索支持精确型号、全角输入及品牌关键词', () => {
  assert.equal(exactDeviceMatch(profiles, 'ＩＰＨＯＮＥ　１５').profile_id, 'iphone15');
  assert.equal(searchDevices(profiles, '苹果15')[0].profile_id, 'iphone15');
  assert.equal(searchDevices(profiles, '小米')[0].profile_id, 'xiaomi14');
  assert.equal(exactDeviceMatch(profiles, '小米'), undefined);
  assert.equal(searchDevices(profiles, '').length, 3);
});

const lenses = [
  { lens_id: 'canon1855', display_name: 'EF-S 18–55', mount: 'canon_ef', sensor_formats: ['APS-C'], focal_min_mm: 18, focal_max_mm: 55, max_aperture_wide: 4, max_aperture_tele: 5.6, source_url: '', notes: [] },
  { lens_id: 'sonye1855', display_name: 'E 18–55', mount: 'sony_e', sensor_formats: ['APS-C'], focal_min_mm: 18, focal_max_mm: 55, max_aperture_wide: 3.5, max_aperture_tele: 5.6, source_url: '', notes: [] },
];

test('不同卡口及需要裁切的镜头不能混入候选', () => {
  assert.deepEqual(compatibleLenses({ mount: 'canon_ef', sensor_format: 'APS-C' }, lenses).map(l => l.lens_id), ['canon1855']);
  assert.deepEqual(compatibleLenses({ mount: 'sony_e', sensor_format: '全画幅' }, lenses), []);
  assert.deepEqual(compatibleLenses({ mount: 'unknown', sensor_format: 'APS-C' }, lenses), []);
  assert.equal(sensorLabel('APS-C'), 'APS-C（半画幅）');
});

test('18–55焦段约束、等效计算和光圈端点联动', () => {
  assert.deepEqual(linkedCameraSettings({ crop_factor: 1.6 }, lenses[0], 55), {
    focal_length_mm: 55, equivalent_focal_length_mm: 88, max_aperture: 5.6,
  });
  assert.equal(linkedCameraSettings({ crop_factor: 1.6 }, lenses[0], 800).focal_length_mm, 55);
  assert.equal(linkedCameraSettings({ crop_factor: 1.6 }, lenses[0], 8).focal_length_mm, 18);
  assert.equal(linkedCameraSettings({ crop_factor: 1.6 }, lenses[0], undefined).max_aperture, 4);
  assert.equal(linkedCameraSettings({ crop_factor: 1.6 }, lenses[0], 35).max_aperture, 5.6);
});

test('未收录后缀及代际不替换为基础版', () => {
  for (const query of ['iPhone 15 Pro', 'iPhone 15 Plus', '小米14 Ultra', '小米14 Pro', 'iPhone 16']) {
    assert.deepEqual(searchDevices(profiles, query), []);
    assert.equal(exactDeviceMatch(profiles, query), undefined);
  }
});

test('手机手填覆盖残留已知ID，相机也可保留未收录名称', () => {
  assert.deepEqual(deviceSelection('phone', 'xiaomi14', true, '  vivo X100 Pro  '), {
    profile_id: 'generic_phone', device_model_name: 'vivo X100 Pro',
  });
  assert.deepEqual(deviceSelection('camera', 'canon_eos_r50', true, 'Sony α7 IV'), {
    profile_id: 'generic_unknown', device_model_name: 'Sony α7 IV',
  });
});

test('退出手填不发送残留名称，空名称及控制字符被拒绝', () => {
  assert.deepEqual(deviceSelection('phone', 'iphone15', false, '旧型号'), {
    profile_id: 'iphone15', device_model_name: '',
  });
  for (const name of ['', '   ', 'x'.repeat(121), 'vivo\nX100', 'test\u007f']) {
    assert.throws(() => deviceSelection('phone', 'iphone15', true, name));
  }
});

test('跨品牌相同短型号只展示候选，不擅自选第一个', () => {
  const ambiguous = [
    { profile_id: 'a', display_name: 'Brand A X1', aliases: ['X1'] },
    { profile_id: 'b', display_name: 'Brand B X1', aliases: ['X1'] },
  ];
  assert.equal(exactDeviceMatch(ambiguous, 'X1'), undefined);
  assert.equal(searchDevices(ambiguous, 'X1').length, 2);
  assert.equal(exactDeviceMatch(ambiguous, 'Brand A X1').profile_id, 'a');
});

test('基础目录不能据未核验卡口提供镜头或虚构裁切系数', () => {
  assert.deepEqual(compatibleLenses({ capability_level: 'catalog', mount: 'canon_ef', sensor_format: 'APS-C' }, lenses), []);
  assert.equal(linkedCameraSettings({ crop_factor: null }, lenses[0], 55).equivalent_focal_length_mm, null);
});
