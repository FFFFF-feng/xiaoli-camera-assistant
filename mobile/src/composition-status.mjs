// Presentation only: never relax drawing validation or retry a paid request.
const stageCopy = {
  recognition: ['没有获得可用的物体识别结果。', '文字建议仍可查看，请展开生成环节核对原因。'],
  contours: ['主体轮廓提取未完成。', '文字方案仍可查看，具体原因见生成环节。'],
  intent: ['没有获得有效的构图方案。', '请明确主体和希望保留的画面，再决定是否重新分析。'],
  layout: ['推荐布局未通过校验。', '可以先按文字步骤试拍，暂不显示不可靠的线稿。'],
};

export function compositionStatus(composition, proposal, hasBoard) {
  if (hasBoard) return { badge: composition?.status === 'unverified' ? '待试拍验证' : '线稿已生成', failed: false };
  if (!composition) return { badge: '未开启构图', failed: false };
  if (composition.status === 'demo') return { badge: '规则演示', failed: false };
  if (proposal?.storyboard) return { badge: '线稿未完成', failed: true,
    reason: '线稿数据未通过显示校验。', action: '文字方案仍可查看，请保留排查编号以便检查。' };
  const diagnostic = composition.diagnostics?.find(item => item?.status === 'failed' && stageCopy[item.stage]);
  if (diagnostic?.code === 'recognition_service_failed' || diagnostic?.code === 'intent_service_failed') {
    return { badge: '线稿未完成', failed: true, reason: '构图识别或规划服务未完成。',
      action: '文字建议仍可查看，请稍后检查服务状态。' };
  }
  let stage = diagnostic?.stage;
  // Older responses may only have a bounded explanation, not structured stages.
  if (!stage && composition.notes?.some(note => /未能.*轮廓|未获得.*轮廓|轮廓.*未完成/.test(note))) stage = 'contours';
  const [reason, action] = stageCopy[stage] || ['这次未生成可展示的线稿。', '可以先看原图对照和文字拍摄步骤。'];
  return { badge: composition.proposals?.length ? '仅文字方案' : '构图未完成', failed: true, reason, action };
}
