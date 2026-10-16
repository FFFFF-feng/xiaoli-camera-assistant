/** Validate a whole selection before changing previews or losing an existing scene. */
export function selectSceneFiles(existing, incoming, maxCount=6, perImageMb=15, totalMb=30) {
  const signature=f=>`${f.name}|${f.size}|${f.lastModified}`;
  const seen=new Set(existing.map(signature)), added=[];
  for(const file of incoming) {
    if (!/\.(jpe?g|png)$/i.test(file.name) || !['image/jpeg','image/png'].includes(file.type)) {
      throw new Error('请选择 JPEG / PNG。HEIC、RAW 请先在系统相册中导出。');
    }
    if (!file.size || file.size>perImageMb*1024*1024) throw new Error(`每张照片须非空且不超过 ${perImageMb} MB。`);
    const key=signature(file);if(seen.has(key))continue;seen.add(key);added.push(file);
  }
  const all=[...existing,...added];
  if(all.length>maxCount)throw new Error(`同一场景最多 ${maxCount} 张，请先移除多余照片。`);
  if(all.reduce((n,f)=>n+f.size,0)>totalMb*1024*1024)throw new Error(`本组照片合计不能超过 ${totalMb} MB。`);
  return added;
}
