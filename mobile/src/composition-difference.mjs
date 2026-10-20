import { sourceLayout } from './target-board.mjs';

// Report actual geometry, never the magnitude requested by the model.
export function compositionDifference(board) {
  if(!sourceLayout(board))return null;
  const main=board.layers.find(layer=>layer.role==='main');
  const a=main.source_bbox,b=main.bbox;
  const sourceWidth=(a[2]-a[0])*100,targetWidth=(b[2]-b[0])*100;
  const sourceHeight=(a[3]-a[1])*100,targetHeight=(b[3]-b[1])*100;
  const center=box=>[(box[0]+box[2])*50,(box[1]+box[3])*50];
  const from=center(a),to=center(b);
  const preserved=board.layout_mode==='source_preserving';
  const small=preserved||Math.max(Math.abs(targetWidth-sourceWidth),Math.abs(targetHeight-sourceHeight),
    Math.abs(to[0]-from[0]),Math.abs(to[1]-from[1]))<3;
  return {sourceWidth,targetWidth,sourceHeight,targetHeight,from,to,preserved,small,
    summary:preserved?'保留原取景，未模拟新的机位':small?'本次取景调整幅度较小':
      `主体宽度占比 ${Math.round(sourceWidth)}% → ${Math.round(targetWidth)}%`,
    position:`主体中心：横向 ${Math.round(from[0])}% → ${Math.round(to[0])}%，纵向 ${Math.round(from[1])}% → ${Math.round(to[1])}%`};
}
