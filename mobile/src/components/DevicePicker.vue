<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { exactDeviceMatch, searchDevices } from '../device-selection.mjs';
import type { DeviceCatalogProfile } from '../types';

const props = defineProps<{
  profiles: DeviceCatalogProfile[]; modelValue: string; manual: boolean;
  manualModelName: string; deviceLabel: string; genericId: string; inputId: string;
  catalogLoaded: boolean;
}>();
const emit = defineEmits<{
  'update:modelValue': [value: string]; 'update:manual': [value: boolean];
  'update:manualModelName': [value: string];
}>();
const query = ref('');
const brand = ref('');
const brands = computed(() => [...new Set(props.profiles.filter(p => !p.profile_id.startsWith('generic_')).map(p => p.brand).filter(Boolean))] as string[]);
const brandNames: Record<string, string> = { Canon: '佳能 Canon', Nikon: '尼康 Nikon', Sony: '索尼 Sony', Fujifilm: '富士 Fujifilm', Panasonic: '松下 Panasonic', Apple: '苹果 Apple', Samsung: '三星 Samsung', Xiaomi: '小米 Xiaomi', Huawei: '华为 Huawei', HONOR: '荣耀 HONOR' };
const brandProfiles = computed(() => props.profiles.filter(p => !brand.value || p.brand === brand.value || p.profile_id.startsWith('generic_')));
const matches = computed(() => searchDevices(brandProfiles.value, query.value));
const options = computed(() => {
  const generic = props.profiles.find(p => p.profile_id === props.genericId);
  const visible = matches.value.slice(0, 100);
  const selected = matches.value.find(p => p.profile_id === props.modelValue);
  if (selected && !visible.includes(selected)) visible.unshift(selected);
  return generic && !visible.some(p => p.profile_id === props.genericId)
    ? [generic, ...visible] : visible;
});
const knownCount = computed(() => props.profiles.filter(p => !p.profile_id.startsWith('generic_')).length);
const catalogCount = computed(() => props.profiles.filter(p => p.capability_level === 'catalog').length);
watch(query, () => {
  const exact = exactDeviceMatch(brandProfiles.value, query.value);
  if (exact) emit('update:modelValue', exact.profile_id);
  else if (!options.value.some(p => p.profile_id === props.modelValue)) emit('update:modelValue', props.genericId);
});
watch(brand, () => { query.value = ''; emit('update:modelValue', props.genericId); });
function setManual(value: boolean) {
  emit('update:manual', value);
  if (value) {
    if (query.value.trim()) emit('update:manualModelName', query.value.trim());
    emit('update:modelValue', props.genericId);
  }
}
function useQuery() {
  emit('update:manualModelName', query.value.trim());
  setManual(true);
}
</script>

<template>
  <div class="device-picker">
    <p class="helper coverage-note">{{ catalogLoaded ? (catalogCount ? `可搜索 ${knownCount} 个${deviceLabel}目录项，其中 ${knownCount - catalogCount} 个已录入适配资料。基础目录不代表完成调参适配。` : `已收录 ${knownCount} 款${deviceLabel}能力资料，并非全量机型目录。`) : '连接电脑服务后加载已收录型号；也可先手动填写。' }}</p>
    <template v-if="!manual">
      <label :for="`${inputId}-brand`">{{ deviceLabel }}品牌</label>
      <select :id="`${inputId}-brand`" v-model="brand"><option value="">全部品牌</option><option v-for="item in brands" :key="item" :value="item">{{ brandNames[item] || item }}</option></select>
      <label :for="`${inputId}-search`">搜索{{ deviceLabel }}型号或品牌</label>
      <input :id="`${inputId}-search`" v-model="query" type="search" maxlength="120" :placeholder="`输入完整${deviceLabel}型号，注意 Pro / Ultra 等后缀`" />
      <p v-if="query.trim() && !matches.length" class="device-missing" role="status">
        {{ catalogLoaded ? (brand ? '当前品牌下没有匹配型号，也可切换全部品牌再搜索。' : '这个型号还没有能力资料。') : '尚未加载型号目录，可先手填，连接后由服务核对。' }}
        <button type="button" class="text-button" @click="useQuery">使用“{{ query.trim() }}”继续</button>
      </p>
      <label :for="inputId">{{ deviceLabel }}型号</label>
      <p v-if="matches.length > 100" class="helper">匹配 {{ matches.length }} 项，先显示前 100 项；请选择品牌或输入更完整型号缩小范围。</p>
      <select :id="inputId" :value="modelValue" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)">
        <option v-for="profile in options" :key="profile.profile_id" :value="profile.profile_id">{{ profile.display_name }}{{ profile.capability_level === 'catalog' ? '（基础目录）' : '' }}</option>
      </select>
    </template>
    <label class="check-row manual-toggle"><input type="checkbox" :checked="manual" @change="setManual(($event.target as HTMLInputElement).checked)" />找不到型号？手动填写</label>
    <template v-if="manual">
      <label :for="`${inputId}-manual`">{{ deviceLabel }}完整型号</label>
      <input :id="`${inputId}-manual`" :value="manualModelName" maxlength="120" required :placeholder="`填写品牌 + 型号 + 后缀`" @input="emit('update:manualModelName', ($event.target as HTMLInputElement).value)" />
      <p class="device-missing">未精确匹配能力资料前，只提供通用拍摄指导；不会借用相近型号的镜头、专业模式或硬件上限。</p>
    </template>
  </div>
</template>
