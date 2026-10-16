import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { compileScript, parse } from '@vue/compiler-sfc';
import ts from 'typescript';
import { createRenderer, h, nextTick, reactive } from 'vue';
import * as deviceSearch from '../src/device-selection.mjs';

const catalog = [
  { profile_id: 'generic_phone', display_name: '未知手机' },
  { profile_id: 'a_x1', display_name: 'Brand A X1', model: 'A X1', aliases: ['X1', 'Ｘ　１', 'x_1'] },
  { profile_id: 'a_x1_pro', display_name: 'Brand A X1 Pro', aliases: ['A X1 Pro'] },
  { profile_id: 'b_x1', display_name: 'Brand B X1', aliases: ['X1'] },
];

test('索引保留空查询、精确优先、歧义和候选原顺序', () => {
  const index = deviceSearch.createDeviceSearchIndex(catalog);
  assert.equal(index.search('  '), catalog);
  assert.equal(index.exact(''), undefined);
  assert.equal(index.exact('Ｘ－１'), undefined);
  assert.deepEqual(index.search('X1').map(profile => profile.profile_id), ['a_x1', 'b_x1']);
  assert.deepEqual(index.search('Brand A X1').map(profile => profile.profile_id), ['a_x1']);
  assert.equal(index.exact('Ａ　Ｘ１'), catalog[1]);
  assert.deepEqual(index.search('Brand').map(profile => profile.profile_id), ['a_x1', 'a_x1_pro', 'b_x1']);
  assert.deepEqual(index.search('A X1 Ultra'), []);
  assert.equal(index.exact('A X2'), undefined);
});

test('同一设备的重复别名不会制造精确匹配歧义', () => {
  const index = deviceSearch.createDeviceSearchIndex([catalog[1], catalog[2]]);
  assert.equal(index.exact('X1'), catalog[1]);
  assert.deepEqual(index.search('x_1'), [catalog[1]]);
});

test('查询只读取已建索引，不再访问设备别名', () => {
  let allowAliasRead = true;
  const profile = {
    profile_id: 'iphone15', display_name: 'Apple iPhone 15', model: 'iPhone 15',
    get aliases() {
      assert.ok(allowAliasRead, '查询期间不应重新访问或规范化目录别名');
      return ['苹果15'];
    },
  };
  const index = deviceSearch.createDeviceSearchIndex([profile]);
  allowAliasRead = false;
  assert.equal(index.exact('苹果 15'), profile);
  assert.deepEqual(index.search('苹果'), [profile]);
  assert.deepEqual(index.search('iPhone 15 Pro'), []);
});

test('兼容函数每次读取当前目录及原地修改的别名', () => {
  const profile = { profile_id: 'a', display_name: 'Brand A', aliases: ['旧别名'] };
  const profiles = [profile];
  assert.equal(deviceSearch.exactDeviceMatch(profiles, '旧别名'), profile);
  profile.aliases.splice(0, 1, '新别名');
  assert.equal(deviceSearch.exactDeviceMatch(profiles, '旧别名'), undefined);
  assert.deepEqual(deviceSearch.searchDevices(profiles, '新别名'), [profile]);
  const replacement = { profile_id: 'b', display_name: 'Brand B', aliases: ['新别名'] };
  profiles.splice(0, 1, replacement);
  assert.equal(deviceSearch.exactDeviceMatch(profiles, '新别名'), replacement);
});

// Compile the real SFC setup; a null render keeps these state and event tests independent of a DOM shim.
const source = await readFile(new URL('../src/components/DevicePicker.vue', import.meta.url), 'utf8');
const script = compileScript(parse(source).descriptor, { id: 'device-picker-test' }).content
  .replaceAll("from 'vue'", `from '${new URL('../node_modules/vue/index.mjs', import.meta.url).href}'`)
  .replaceAll("from '../device-selection.mjs'", `from '${new URL('../src/device-selection.mjs', import.meta.url).href}'`);
const compiled = ts.transpileModule(script, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { default: DevicePicker } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function mountPicker(profiles) {
  const props = reactive({
    profiles, modelValue: 'generic_phone', manual: false, manualModelName: '',
    deviceLabel: '手机', genericId: 'generic_phone', inputId: 'phone', catalogLoaded: true,
  });
  const renderer = createRenderer({
    createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null,
    nextSibling: () => null, createElement: () => ({}), createText: () => ({}),
    setText() {}, setElementText() {}, patchProp() {},
  });
  const component = { ...DevicePicker, render: () => null };
  const app = renderer.createApp({
    render: () => h(component, {
      ...props,
      'onUpdate:modelValue': value => { props.modelValue = value; },
      'onUpdate:manual': value => { props.manual = value; },
      'onUpdate:manualModelName': value => { props.manualModelName = value; },
    }),
  });
  app.mount({});
  return { props, state: app._instance.subTree.component.setupState, unmount: () => app.unmount() };
}

test('DevicePicker 连续输入共用索引，精确选择与候选查询不重读别名', async t => {
  let aliasReads = 0;
  const picker = mountPicker([
    catalog[0],
    { profile_id: 'a', display_name: 'Brand A X1', brand: 'A', get aliases() { aliasReads += 1; return ['X1', 'x_1']; } },
    { profile_id: 'b', display_name: 'Brand B X1', brand: 'B', aliases: ['X1'] },
  ]);
  t.after(picker.unmount);
  assert.equal(picker.state.options.length, 3);
  const builtReads = aliasReads;
  for (const query of ['B', 'Br', 'Brand', 'X1', 'Brand A X1']) {
    picker.state.query = query;
    await nextTick();
    assert.ok(picker.state.matches.length > 0);
  }
  assert.equal(picker.props.modelValue, 'a');
  assert.equal(aliasReads, builtReads, '输入只查询现有索引');
});

test('DevicePicker 当前查询可见原地别名更新与目录替换', async t => {
  const picker = mountPicker([catalog[0], { profile_id: 'a', display_name: 'Brand A', aliases: ['旧别名'] }]);
  t.after(picker.unmount);
  picker.state.query = '新别名';
  await nextTick();
  assert.deepEqual(picker.state.matches, []);
  picker.props.profiles[1].aliases.splice(0, 1, '新别名');
  await nextTick();
  assert.deepEqual(picker.state.matches.map(profile => profile.profile_id), ['a']);
  picker.props.profiles = [catalog[0], { profile_id: 'b', display_name: 'Replacement', aliases: ['新别名'] }];
  await nextTick();
  assert.deepEqual(picker.state.matches.map(profile => profile.profile_id), ['b']);
});

test('DevicePicker 品牌内才允许唯一精确选择，手填沿用输入并清除已选设备', async t => {
  const picker = mountPicker([
    catalog[0],
    { profile_id: 'a', display_name: 'Brand A X1', brand: 'A', aliases: ['X1'] },
    { profile_id: 'b', display_name: 'Brand B X1', brand: 'B', aliases: ['X1'] },
  ]);
  t.after(picker.unmount);
  picker.state.query = 'X1';
  await nextTick();
  assert.equal(picker.props.modelValue, 'generic_phone');
  picker.state.brand = 'A';
  await nextTick();
  picker.state.query = 'X1';
  await nextTick();
  assert.equal(picker.props.modelValue, 'a');
  assert.deepEqual(picker.state.matches.map(profile => profile.profile_id), ['a']);
  picker.state.query = '  Brand A X2 Pro  ';
  await nextTick();
  picker.state.useQuery();
  await nextTick();
  assert.equal(picker.props.manual, true);
  assert.equal(picker.props.manualModelName, 'Brand A X2 Pro');
  assert.equal(picker.props.modelValue, 'generic_phone');
});
