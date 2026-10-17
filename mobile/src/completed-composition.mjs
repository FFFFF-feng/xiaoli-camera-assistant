import {usableTargetBoard} from './target-board.mjs';

// This channel contains a completed local layout, while the overall analysis
// (for example camera parameters) can still be running. Legacy text snapshots
// never acquire drawable geometry here.
export function completedComposition(value,photoIds=[]) {
  if(!value||!['grounded','unverified'].includes(value.status)||!Array.isArray(value.proposals)
    ||!Array.isArray(value.diagnostics)
    ||!value.diagnostics.some(item=>item?.stage==='layout'&&item.status==='complete'&&item.code==='local_layout_solved'))return null;
  const available=new Set(photoIds);
  const proposals=value.proposals.filter(proposal=>{
    const board=usableTargetBoard(proposal?.storyboard);
    return board?.layout_engine==='local_v1'&&board.render_basis==='source_geometry'
      &&available.has(board.reference_photo_id)
      &&board.layers.every(layer=>layer.evidence_photo_ids.every(id=>available.has(id)));
  });
  return proposals.length?{...value,proposals}:null;
}
