// Presentation only. Consolidate existing advice without inventing a viewpoint,
// shortening a condition, or claiming that a source-preserving diagram improved it.
const clean=value=>typeof value==='string'?value.trim().replace(/\s+/g,' '):'';
const key=value=>clean(value).replace(/[。；;.!！\s]+$/g,'');
export function uniqueAdvice(values=[]) {
  const seen=new Set();
  return (Array.isArray(values)?values:[]).map(clean).filter(value=>{
    const id=key(value);if(!id||seen.has(id))return false;
    seen.add(id);return true;
  });
}

/**
 * @param {{goal?:string,actions?:string[]}|null|undefined} proposal
 * @param {import('./types').TargetBoard|null} board
 * @param {import('./types').FramingPlan|null} framing
 */
export function fieldActionCard(proposal,board=null,framing=null) {
  if(!proposal)return null;
  const changes=Array.isArray(board?.changes)?board.changes:[];
  const actions=uniqueAdvice(proposal.actions);
  const sourcePreserving=board?.layout_mode==='source_preserving';
  return {
    problem:clean(framing?.diagnosis)||clean(changes[0]?.problem)||clean(proposal.goal)||'先核对主体与画面边缘。',
    actions:actions.length?actions:uniqueAdvice([changes[0]?.adjustment,board?.distance_instruction]),
    benefit:sourcePreserving
      ? '本次线稿保留原始布局，未模拟新的机位效果；实际改善需现场试拍核对。'
      : !board?'本次仅有文字建议，未生成可核对的构图图示；效果需现场试拍确认。'
      : clean(changes[0]?.benefit)||'按建议试拍，再比较主体是否更突出。',
    // The rest of the framing checks remain in the expandable detail sheet.
    checks:uniqueAdvice([clean(framing?.success_check)||clean(framing?.edge_check)||clean(framing?.background_control)]),
  };
}
