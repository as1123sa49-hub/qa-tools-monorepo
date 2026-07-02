import sharp from 'sharp';

/** 兩張圖差異比例 0~1；可選 region 只比某區塊 */
export async function imageDiffRatio(a, b, region) {
  const toThumb = async buf => {
    let img = sharp(buf);
    if (region) img = img.extract(region);
    return img.resize(80, 45, { fit: 'fill' }).raw().toBuffer({ resolveWithObject: true });
  };
  const ra = await toThumb(a);
  const rb = await toThumb(b);
  if (ra.data.length !== rb.data.length) return 1;
  const ch = ra.info.channels;
  let diff = 0;
  let n = 0;
  for (let i = 0; i < ra.data.length; i += ch) {
    const d =
      Math.abs(ra.data[i] - rb.data[i]) +
      Math.abs(ra.data[i + 1] - rb.data[i + 1]) +
      Math.abs(ra.data[i + 2] - rb.data[i + 2]);
    if (d > 60) diff++;
    n++;
  }
  return diff / n;
}
