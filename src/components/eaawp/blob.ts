/** Organic membrane path generator shared by the AI organism visuals. */
export function blobPath(
  cx: number,
  cy: number,
  r: number,
  t: number,
  energy: number,
  points = 9,
): string {
  const pts: [number, number][] = [];
  for (let i = 0; i < points; i++) {
    const a = (i / points) * Math.PI * 2;
    const wobble =
      Math.sin(a * 3 + t * 0.9) * 0.07 +
      Math.sin(a * 5 - t * 1.4) * 0.045 +
      Math.cos(a * 2 + t * 0.55) * 0.05;
    const rr = r * (1 + wobble * (0.55 + energy));
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.92]);
  }
  let d = "";
  for (let i = 0; i < pts.length; i++) {
    const p0 = pts[(i - 1 + pts.length) % pts.length]!;
    const p1 = pts[i]!;
    const p2 = pts[(i + 1) % pts.length]!;
    const p3 = pts[(i + 2) % pts.length]!;
    if (i === 0) d += `M ${p1[0].toFixed(2)} ${p1[1].toFixed(2)}`;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return `${d} Z`;
}
