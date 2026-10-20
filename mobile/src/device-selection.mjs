/** @typedef {import('./types').DeviceCatalogProfile} DeviceProfile */

export function normalizeModelName(value) {
  return String(value).normalize('NFKC').toLowerCase().replace(/[\s_-]+/g, '');
}

/** @param {DeviceProfile} profile */
function names(profile) {
  return [profile.profile_id, profile.display_name, profile.model || '', ...(profile.aliases || [])]
    .filter(Boolean).map(normalizeModelName);
}

/** 构建当前目录快照；在 Vue computed 中调用可跟踪型号与别名的原地更新。 @param {DeviceProfile[]} profiles */
export function createDeviceSearchIndex(profiles) {
  const entries = profiles.map(profile => ({ profile, keys: [...new Set(names(profile))] }));
  /** @type {Map<string, DeviceProfile[]>} */
  const exactMatches = new Map();
  for (const { profile, keys } of entries) {
    for (const key of keys) {
      const matches = exactMatches.get(key);
      if (matches) matches.push(profile);
      else exactMatches.set(key, [profile]);
    }
  }
  return {
    /** @param {string} query */
    exact(query) {
      const key = normalizeModelName(query);
      const matches = key ? exactMatches.get(key) : undefined;
      return matches?.length === 1 ? matches[0] : undefined;
    },
    /** @param {string} query */
    search(query) {
      const key = normalizeModelName(query);
      if (!key) return profiles;
      const exact = exactMatches.get(key);
      if (exact?.length) return exact.slice();
      return entries.filter(({ keys }) => keys.some(name => name.includes(key))).map(({ profile }) => profile);
    },
  };
}

/** @param {DeviceProfile[]} profiles */
export function exactDeviceMatch(profiles, query) {
  const key = normalizeModelName(query);
  const matches = key ? profiles.filter(profile => names(profile).includes(key)) : [];
  return matches.length === 1 ? matches[0] : undefined;
}

/** 搜索候选不是模糊能力匹配；具体代际/后缀只接受精确型号。 @param {DeviceProfile[]} profiles */
export function searchDevices(profiles, query) {
  const key = normalizeModelName(query);
  if (!key) return profiles;
  const exact = profiles.filter(profile => names(profile).includes(key));
  if (exact.length) return exact;
  return profiles.filter(profile => names(profile).some(name => name.includes(key)));
}

/** 手填时强制通用ID，防止上次选中的已知设备残留。 */
export function deviceSelection(deviceType, selectedId, manual, name) {
  const modelName = manual ? String(name).trim() : '';
  if (manual && !modelName) throw new Error('请填写设备完整型号，或取消手动填写。');
  if (modelName.length > 120 || /[\u0000-\u001f\u007f]/.test(modelName)) {
    throw new Error('设备型号最长 120 字，不能包含换行或控制字符。');
  }
  return {
    profile_id: manual ? (deviceType === 'phone' ? 'generic_phone' : 'generic_unknown') : selectedId,
    device_model_name: modelName,
  };
}

export const mountNames = {
  canon_rf: 'Canon RF / RF-S', canon_ef: 'Canon EF / EF-S', nikon_z: 'Nikon Z',
  sony_e: 'Sony E / FE', fujifilm_x: 'Fujifilm X', micro_four_thirds: 'Micro Four Thirds',
  nikon_f: 'Nikon F', sony_a: 'Sony A', leica_l: 'Leica L', leica_m: 'Leica M',
  pentax_k: 'Pentax K', canon_fd: 'Canon FD', four_thirds: 'Four Thirds',
};
const referenceMountAliases = {
  canonrf: 'canon_rf', canonef: 'canon_ef', canonefs: 'canon_ef', nikonz: 'nikon_z',
  nikonf: 'nikon_f', nikonfaf: 'nikon_f', nikonfai: 'nikon_f', sonye: 'sony_e', sonyfe: 'sony_e',
  sonya: 'sony_a', sonyalpha: 'sony_a', minoltaaf: 'sony_a', fujifilmx: 'fujifilm_x', fujix: 'fujifilm_x',
  microfourthirds: 'micro_four_thirds', 'micro4/3system': 'micro_four_thirds',
  leical: 'leica_l', 'lmount': 'leica_l', leicam: 'leica_m', pentaxk: 'pentax_k',
  pentaxkaf: 'pentax_k', pentaxkaf2: 'pentax_k', pentaxkaf3: 'pentax_k',
  canonfd: 'canon_fd', fourthirds: 'four_thirds', '4/3system': 'four_thirds',
};
export function referenceCameraMounts(camera) {
  if (camera?.capability_level !== 'catalog' && camera?.mount && camera.mount !== 'unknown') return [camera.mount];
  return [...new Set((camera?.catalog_mount_labels || []).map(label => referenceMountAliases[normalizeModelName(label)] || (mountNames[label] ? label : '')).filter(Boolean))];
}
/** @param {import('./types').CameraProfile | undefined} camera
 * @param {import('./types').LensReference[]} lenses */
export function candidateReferenceLenses(camera, lenses, declaredMount = '') {
  const mounts = referenceCameraMounts(camera);
  if (!mounts.length && mountNames[declaredMount]) mounts.push(declaredMount);
  return lenses.filter(lens => lens.mount_keys.some(key => mounts.includes(key))
    && (!lens.sensor_formats?.length || !camera?.sensor_format || camera.sensor_format === '不清楚'
      || lens.sensor_formats.includes(camera.sensor_format)));
}

/** @param {import('./types').CameraProfile | undefined} camera
 * @param {import('./types').LensReference | undefined} lens */
export function referenceLensSettings(camera, lens, focalLength) {
  if (!lens?.parameter_linkage || typeof lens.focal_min_mm !== 'number' || typeof lens.focal_max_mm !== 'number') return null;
  const current = focalLength === undefined || focalLength === null || focalLength === '' ? lens.focal_min_mm : Number(focalLength);
  const focal = Math.min(lens.focal_max_mm, Math.max(lens.focal_min_mm, Number.isFinite(current) ? Math.round(current) : lens.focal_min_mm));
  return { focal_min_mm: lens.focal_min_mm, focal_max_mm: lens.focal_max_mm,
    focal_length_mm: focal,
    equivalent_focal_length_mm: camera?.crop_factor ? Math.round(focal * camera.crop_factor * 100) / 100 : null,
    max_aperture: (focal === lens.focal_min_mm ? lens.max_aperture_wide : lens.max_aperture_tele) ?? null };
}
export function sensorLabel(value) { return value === 'APS-C' ? 'APS-C（半画幅）' : (value || '不清楚'); }

/** @param {{mount?: string, sensor_format?: string, capability_level?: string} | undefined} camera
 * @param {import('./types').CameraLensProfile[]} lenses */
export function compatibleLenses(camera, lenses) {
  if (camera?.capability_level === 'catalog') return [];
  return camera?.mount && camera.mount !== 'unknown'
    ? lenses.filter(lens => lens.mount === camera.mount && lens.sensor_formats.includes(camera.sensor_format || '不清楚')) : [];
}

/** @param {{crop_factor?: number | null}} camera @param {import('./types').CameraLensProfile} lens */
export function linkedCameraSettings(camera, lens, focalLength) {
  const value = Number.isFinite(Number(focalLength)) ? Math.round(Number(focalLength)) : lens.focal_min_mm;
  const focal = Math.min(lens.focal_max_mm, Math.max(lens.focal_min_mm, value));
  return {
    focal_length_mm: focal,
    equivalent_focal_length_mm: camera.crop_factor ? Math.round(focal * camera.crop_factor * 100) / 100 : null,
    max_aperture: focal === lens.focal_min_mm ? lens.max_aperture_wide : lens.max_aperture_tele,
  };
}
