/** @typedef {{profile_id: string, display_name: string, model?: string, aliases?: string[]}} DeviceProfile */

export function normalizeModelName(value) {
  return String(value).normalize('NFKC').toLowerCase().replace(/[\s_-]+/g, '');
}

/** @param {DeviceProfile} profile */
function names(profile) {
  return [profile.profile_id, profile.display_name, profile.model || '', ...(profile.aliases || [])]
    .filter(Boolean).map(normalizeModelName);
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
};
export function sensorLabel(value) { return value === 'APS-C' ? 'APS-C（半画幅）' : (value || '不清楚'); }

/** @param {{mount?: string, sensor_format?: string} | undefined} camera
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
