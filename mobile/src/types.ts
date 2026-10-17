export interface DeviceCatalogProfile {
  profile_id: string; display_name: string; brand?: string; model?: string; aliases?: string[];
  capability_level?: string;
}
export type PreviewApi = (path:string,options?:RequestInit)=>Promise<any>;
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
    appearance?: string; facing?: 'front' | 'left' | 'right'; description?: string;
    source_bbox?: number[] | null; identity_features?: string[] }[];
  horizon_y?: number | null;
  camera_action: 'stay' | 'left' | 'right' | 'closer' | 'farther' | 'lower' | 'higher';
  camera_instruction: string;
  theme?: string; mood?: string; narration?: string; space_note?: string;
}
export interface FramingPlan {
  diagnosis: string; visual_priority: string; placement: string; scale: string;
  negative_space: string; edge_check: string; background_control: string; success_check: string;
}
export interface TargetBoard {
  aspect:'portrait'|'landscape'|'square'; reference_photo_id:string; intent:string;narration?:string;
  distance_relation:'closer'|'farther'|'similar'|'unknown'; distance_instruction:string;
  render_basis?:'legacy'|'source_geometry';layout_mode?:'schematic'|'crop_projection'|'source_preserving';source_photo_aspect?:number|null;
  layout_engine?:'legacy'|'local_v1';
  layers:{label:string;kind:string;role:'main'|'foreground'|'background'|'prop';depth:number;bbox:number[];
    color:'slate'|'blue'|'ochre'|'sage'|'rose';representation?:'silhouette'|'context_lines'|'scene_structure';outline:number[][];contours?:number[][][];holes?:number[][][];outline_style?:'angular'|'curved';details:number[][][];source_details?:number[][][]|null;
    identity_features:string[];evidence_photo_ids:string[];certainty:'observed'|'approximate';
    source_object_id?:string|null;source_bbox?:number[]|null;mobility?:'fixed'|'movable'|'unknown'}[];
  changes:{problem:string;adjustment:string;benefit:string}[];limitations:string[];
}
export interface SceneSurvey {
  status:'consistent'|'uncertain'|'mixed';summary:string;preferred_photo_id:string;selection_reason:string;
  views:{image_id:string;contribution:string;viewpoint_hint:string}[];
  relative_distance:string;subject_options:string[];foreground_options:string[];limitations:string[];
}
export interface Analysis {
  timings?: { stage: string; duration_seconds: number; status: 'complete' | 'failed' }[];
  analysis_mode: 'cloud' | 'demo'; request_id: string;
  scene_photo_count?:number;
  result: {
    camera_profile: { display_name: string; device_type: 'phone' | 'camera'; sensor_format?: string };
    equipment_settings?: { camera_lens?: CameraLensProfile | null; focal_length_mm?: number | null;
      equivalent_focal_length_mm?: number | null; max_aperture?: number | null } | null;
    scene: { scene_label: string; scene_type: string; subject: string; lighting: string; notes: string[];scene_survey?:SceneSurvey|null };
    composition?: {
      status: 'grounded' | 'unverified' | 'unavailable' | 'demo';
      observations: string[]; uncertainties: string[]; notes: string[];
      trace_id?:string|null;
      diagnostics?:{stage:'recognition'|'contours'|'intent'|'layout';status:'complete'|'failed'|'skipped';code:string}[];
      proposals: { action_type: string; goal: string; actions: string[]; reasons: string[];
        tradeoffs: string[]; conditions: string[]; limitations: string[]; knowledge_ids: string[];
        crop_bbox?: number[] | null; sketch?: CompositionSketchData | null; framing_plan?: FramingPlan | null;storyboard?:TargetBoard|null }[];
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
