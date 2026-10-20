// These weights describe workflow milestones, not elapsed time or model tokens.
// Independent branches contribute separately so fast parameters cannot imply
// that a slow composition branch is nearly finished. Only a result reaches 100%.
const weights = {
  upload: 8, photos: 7, scene: 20, knowledge: 10,
  observation: 12, contours: 10, layout: 10, composition: 10, parameters: 8,
};
const timingMilestones = {
  upload: 'upload', upload_validation: 'upload', image_preprocessing: 'photos',
  vision: 'scene', parameter_retrieval: 'knowledge', composition_retrieval: 'knowledge',
  composition_observation: 'observation', composition_contours: 'contours',
  composition_layout: 'layout', composition_local_layout: 'layout',
  composition: 'composition', parameter_validation: 'parameters',
};
const activityMessages = {
  vision: '正在识别照片中的主体、光线和场景…',
  localization: '正在确认主体在画面中的位置…',
  composition_observation: '正在观察景物外形和前后空间关系…',
  composition_contours: '正在提取主体轮廓，保留照片细节…',
  composition_layout: '正在结合你的目标规划构图…',
  target_drawing: '正在绘制推荐构图的线条与细节…',
  parameters: '正在结合器材整理拍摄参数与操作建议…',
};

export function initialAnalysisProgress() {
  return {
    percent: 0, completed: /** @type {string[]} */ ([]),
    message: '正在上传照片…', history: /** @type {string[]} */ ([]),
  };
}

/** @param {ReturnType<typeof initialAnalysisProgress>} state @param {any} event */
export function advanceAnalysisProgress(state, event) {
  if (!event || state.percent === 100) return state;
  const completed = new Set(state.completed);
  let message = state.message;
  const mark = (...keys) => keys.forEach(key => completed.add(key));
  if (event.type === 'result') {
    return { ...state, percent: 100, message: '拍摄方案已整理完成。' };
  }
  if (event.type === 'progress' && typeof event.message === 'string') {
    message = /分析完成/.test(event.message) ? '正在汇总完整拍摄方案…' : event.message;
    // A pipeline progress event can only arrive after the upload was received.
    mark('upload');
    if (/查阅|检索/.test(message)) mark('photos', 'scene');
    if (/生成构图|生成拍摄参数/.test(message)) mark('knowledge');
  } else if (event.type === 'timing') {
    // A failed stage is still handled work; it does not mean its output passed.
    const key = timingMilestones[event.stage];
    if (key && ['complete', 'failed'].includes(event.status)) mark(key);
  } else if (event.type === 'activity') {
    if (['request_started', 'content'].includes(event.phase) && activityMessages[event.stage]) {
      message = activityMessages[event.stage];
    }
  } else if (event.type === 'partial') {
    if (event.kind === 'scene') {
      mark('upload', 'photos', 'scene');
      message = '画面识别已完成，正在查阅适用的拍摄知识…';
    } else if (event.kind === 'composition') {
      // Layout text is validated, but contours/drawing may still be running.
      mark('knowledge', 'layout');
      if (!completed.has('composition')) message = '构图文字已校验，正在整理推荐画面…';
    } else if (event.kind === 'composition_ready' && event.ready === true) {
      mark('observation', 'contours', 'layout', 'composition');
      message = completed.has('parameters')
        ? '构图与拍摄建议已就绪，正在汇总完整方案…'
        : '推荐构图已就绪，正在整理其余拍摄建议…';
    } else if (event.kind === 'parameters') {
      mark('knowledge', 'parameters');
      message = completed.has('composition')
        ? '构图与拍摄建议已就绪，正在汇总完整方案…'
        : '拍摄建议已校验，正在继续整理构图画面…';
    }
  }
  const percent = [...completed].reduce((sum, key) => sum + (weights[key] || 0), 0);
  const history = message !== state.message
    ? [...state.history.filter(item => item !== message), message].slice(-4)
    : state.history;
  return { percent: Math.max(state.percent, Math.min(95, percent)),
    completed: [...completed], message, history };
}
