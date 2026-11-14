// 自影 · 地图镜头：把地点画成 SVG（离线、确定性，不依赖在线地图瓦片）
// 输入（stdin JSON）：{"width":920,"height":560,"places":[{"name":"北京","lon":116.4,"lat":39.9}],"highlight":["China"],"zoom":1}
// 输出（stdout JSON）：{"land":"<path d>","hi":[{"name","d"}],"pins":[{"name","x","y"}],"graticule":"<path d>"}
// 数据：Natural Earth（公有领域），经 world-atlas 转换
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { geoMercator, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
const require = createRequire(import.meta.url);
// 背景国家用 1:1.1 亿精度（体积小），高亮国家用 1:5000 万精度（边界更细）
const load = (f) => { const t = JSON.parse(readFileSync(require.resolve(`world-atlas/${f}`), "utf8")); return feature(t, t.objects.countries).features; };
const countries = load("countries-110m.json");
const detailed = load("countries-50m.json");
const req = JSON.parse(readFileSync(0, "utf8"));
const W = req.width || 920, H = req.height || 560;
const pts = (req.places || []).filter((p) => isFinite(p.lon) && isFinite(p.lat));
// 取景：包住所有地点（外加高亮国家），四周留白；只有一个点时按 zoom 取一块区域
const hiNames = new Set((req.highlight || []).map((s) => s.toLowerCase()));
const hiFeatures = detailed.filter((c) => hiNames.has(String(c.properties.name).toLowerCase()));
let target;
// 有 2 个以上地点：按地点取景（高亮国家只上色，不参与取景，否则俄罗斯这类大国会把画面拉成半个世界）
// 地点之间太近时，按最小跨度（约 12°×8°）补足，避免放得过大
if (pts.length > 1) {
  const lons = pts.map((p) => p.lon), lats = pts.map((p) => p.lat);
  let [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, hw = Math.max(6, (x1 - x0) / 2) * 1.25, hh = Math.max(4, (y1 - y0) / 2) * 1.25;
  target = { type: "MultiPoint", coordinates: [[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]] };
} else if (hiFeatures.length && !pts.length) {
  target = { type: "FeatureCollection", features: hiFeatures };
} else {
  const p = pts[0] || { lon: 105, lat: 35 };
  const r = 18 / (req.zoom || 1);
  // 用四个角点取景（d3 的多边形有方向性，画反了会被当成「除此之外的全世界」）
  target = { type: "MultiPoint", coordinates: [[p.lon - r, p.lat - r * 0.7], [p.lon + r, p.lat - r * 0.7], [p.lon + r, p.lat + r * 0.7], [p.lon - r, p.lat + r * 0.7]] };
}
const pad = req.pad ?? 60;
const proj = geoMercator().fitExtent([[pad, pad], [W - pad, H - pad]], target).clipExtent([[0, 0], [W, H]]);
const path = geoPath(proj).digits(1);
const land = countries.map((c) => path(c) || "").join("");
const hi = hiFeatures.map((c) => ({ name: c.properties.name, d: path(c) || "" }));
const pins = pts.map((p) => { const [x, y] = proj([p.lon, p.lat]); return { name: p.name, x: +x.toFixed(1), y: +y.toFixed(1) }; });
process.stdout.write(JSON.stringify({ land, hi, pins, graticule: path(geoGraticule10()) || "" }));
