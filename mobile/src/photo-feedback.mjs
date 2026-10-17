// Crop coordinates are only meaningful for the primary photo used by the
// backend. A different viewpoint must never be used to fake this preview.
/** @param {number} width @param {number} height @param {number[] | null | undefined} crop */
export function photoFrame(width,height,crop=null) {
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)return null;
  const valid=Array.isArray(crop)&&crop.length===4
    &&crop.every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=1)
    &&crop[2]>crop[0]&&crop[3]>crop[1];
  const [x1,y1,x2,y2]=valid?crop:[0,0,1,1];
  return {x:x1*width,y:y1*height,width:(x2-x1)*width,height:(y2-y1)*height,cropped:valid};
}
