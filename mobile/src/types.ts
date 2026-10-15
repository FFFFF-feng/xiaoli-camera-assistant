export interface DeviceCatalogProfile {
  profile_id: string; display_name: string; brand?: string; model?: string; aliases?: string[];
  capability_level?: string;
}
export interface PhoneProfile extends DeviceCatalogProfile {
  modes: string[];
  pro_controls?: string[];
  lenses: { lens_id: string; name: string; modes?: string[]; aperture?: number | null;
    aperture_max?: number | null; aperture_control?: string; equivalent_focal_length_mm?: number | null }[];
  notes: string[];
}
export interface CameraProfile extends DeviceCatalogProfile {
  sensor_format?: string; crop_factor?: number | null; mount?: string; capability_level?: string;
  catalog_sensor_label?: string; catalog_mount_labels?: string[];
  catalog_sources?: {url: string; license: string; attribution: string}[];
}
export interface CameraLensProfile {
  lens_id: string; display_name: string; mount: string; sensor_formats: string[];
  focal_min_mm: number; focal_max_mm: number; max_aperture_wide: number; max_aperture_tele: number;
  source_url: string; notes: string[];
}
export interface CompositionSketchData {
  aspect: 'portrait' | 'landscape' | 'square';
  caption: string;
  elements: { kind: 'person' | 'tree' | 'pet' | 'building' | 'mountain' | 'flower' | 'object';
    label: string; role: 'main' | 'context'; bbox: number[];
    appearance?: string; facing?: 'front' | 'left' | 'right'; description?: string }[];
  horizon_y?: number | null;
  camera_action: 'stay' | 'left' | 'right' | 'closer' | 'farther' | 'lower' | 'higher';
  camera_instruction: string;
  theme?: string; mood?: string; narration?: string; space_note?: string;
}
export interface Analysis {
  analysis_mode: 'cloud' | 'demo'; request_id: string;
  result: {
    camera_profile: { display_name: string; device_type: 'phone' | 'camera'; sensor_format?: string };
    equipment_settings?: { camera_lens?: CameraLensProfile | null; focal_length_mm?: number | null;
      equivalent_focal_length_mm?: number | null; max_aperture?: number | null } | null;
    scene: { scene_label: string; scene_type: string; subject: string; lighting: string; notes: string[] };
    composition?: {
      status: 'grounded' | 'unverified' | 'unavailable' | 'demo';
      observations: string[]; uncertainties: string[]; notes: string[];
      proposals: { action_type: string; goal: string; actions: string[]; reasons: string[];
        tradeoffs: string[]; conditions: string[]; limitations: string[]; knowledge_ids: string[];
        crop_bbox?: number[] | null; sketch?: CompositionSketchData | null }[];
    } | null;
    composition_knowledge_hits?: { document_id: string; title: string; source: string; content: string }[];
    localization?: {
      real: boolean; status: string;
      selection: { status: string; selected_ids: string[]; reason: string };
      candidates: { object_id: string; label_display: string; bbox: number[]; coordinate_basis: string }[];
      diagnostics: string[];
    } | null;
    recommendation: {
      shooting_mode: string; aperture: string; shutter_speed: string; iso: string;
      exposure_compensation: string; focus_mode: string; metering_mode: string;
      drive_mode: string; white_balance: string;
      reasons: string[]; risks: string[]; adjustments: string[]; validation_notes: string[];
    };
    inspection: { exif: { camera_model: string | null } };
    knowledge_mode: string; knowledge_notes: string[];
    knowledge_hits: { document_id: string; title: string; source: string; content: string }[];
  };
}
