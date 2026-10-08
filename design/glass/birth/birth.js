/* Появление пилюли «Слушаю»: шесть вариантов против нынешней материализации.
 *
 * Отзыв 8.10.2026: пилюля «появляется просто никак — материализуется»; пусть
 * вылетает из низа экрана или красиво рождается на своём месте. Место прежнее:
 * снизу по центру, 96 px над панелью задач (ui.hud_margin). Варианты сильно
 * разные, в каждом одно движение; уход у всех нынешний — смотрим только
 * появление.
 *
 * Стекло — числа Линзы, как в src/ui/lens_shader.py: материализация m гасит
 * преломление, размытие, вуаль, блик и тень, а не прозрачность формы. Голос
 * внутри — Шёлк в паузе, теми же числами, что в voice/ и в приложении. Форма —
 * до шести капсул, слитых гладким минимумом: из них собираются капли,
 * перемычки и столб жидкости.
 */
(function () {
  'use strict';

  const TILE_W = 520;
  const TILE_H = 240;
  const EDGE = 204;                 // верх панели задач: низ рабочей области
  const C = [260, EDGE - 96 - 28];  // центр пилюли: 96 px над панелью, как в приложении
  const CW = 200;                   // «Слушаю» — капсула без надписей (lens_hud.LISTEN_W)
  const CH = 56;
  const CROP = [150, 24, 220, 216]; // кадр раскадровки: пилюля и край панели под ней
  const FRAMES = [0.05, 0.12, 0.2, 0.3, 0.45, 1.0];
  const HOLD = 2.4;                 // живьём: сколько стоит, прежде чем уйти
  const LOOP = 3.6;
  const FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
  const FONT_CODE = '"Cascadia Code", "Cascadia Mono", Consolas, monospace';

  // ------------------------------------------------------------ фоны

  const DOC = 'Пилюля появляется над чужими окнами: над документом, редактором и обоями. Нажал клавишу — ' +
    'и она уже здесь, слушает. Появление заметно сразу, но органично: одно движение, без вспышек и без ' +
    'радуги. Отпустил — Дарви распознаёт, причёсывает и вставляет текст туда, где стоит курсор, а сам ' +
    'тает. Десятки раз в день, поэтому движение не должно надоесть.';

  function drawDoc(g, w, h) {
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, w, h);
    g.fillStyle = '#1f1f1f';
    g.font = `400 14.5px ${FONT_UI}`;
    const words = (DOC + ' ' + DOC).split(' ');
    let line = '';
    let y = 21;
    for (const word of words) {
      const test = line ? line + ' ' + word : word;
      if (g.measureText(test).width > w - 32 && line) {
        g.fillText(line, 16, y);
        line = word;
        y += 23;
        if (y > h + 20) break;
      } else line = test;
    }
  }

  const CODE = [
    ['    def ', 'appear', '(self, now: float) -> None:'],
    ['        ', '# Одно движение: форма приходит, свет — за ней.', ''],
    ['        self.mat.tune(', '0.45', ', 0.8)'],
    ['        m = self.mat.set(1.0).step(dt)', '', ''],
    ['        ', 'return', ' clamp01(m)'],
    ['', '', ''],
    ['    def ', 'paint', '(self, painter: QPainter) -> None:'],
    ['        width = ', 'max', '(self.w.value, PILL_H)'],
    ['        ', '# Голос внутри стекла — шёлк.', ''],
    ['        ', 'return', ' width'],
    ['', '', ''],
    ['    def ', 'vanish', '(self) -> None:'],
  ];

  function drawCode(g, w, h) {
    g.fillStyle = '#1e1f22';
    g.fillRect(0, 0, w, h);
    g.font = `400 13px ${FONT_CODE}`;
    const colors = ['#cfd3da', '#e2d58f', '#cfd3da'];
    for (let i = 0; i < CODE.length; i++) {
      const y = 18 + i * 17.5;
      g.fillStyle = '#5c6068';
      g.textAlign = 'right';
      g.fillText(String(214 + i), 30, y);
      g.textAlign = 'left';
      let x = 42;
      CODE[i].forEach((part, k) => {
        let color = colors[k];
        if (part.trim().startsWith('#')) color = '#6f9c5a';
        else if (/^\s*(def|return)\s*$/.test(part)) color = '#c38fd1';
        else if (/^[\d.]+$/.test(part)) color = '#b3cea0';
        else if (part === 'max') color = '#6fc2b0';
        if (k === 0 && part.includes('def')) {
          g.fillStyle = '#cfd3da';
          g.fillText(part.replace('def ', ''), x, y);
          x += g.measureText(part.replace('def ', '')).width;
          g.fillStyle = '#c38fd1';
          g.fillText('def ', x, y);
          x += g.measureText('def ').width;
          return;
        }
        g.fillStyle = color;
        g.fillText(part, x, y);
        x += g.measureText(part).width;
      });
    }
  }

  function drawPhoto(g, w, h) {
    const base = g.createLinearGradient(0, 0, w, h);
    base.addColorStop(0, '#0e1d3d');
    base.addColorStop(1, '#3a1850');
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    g.globalCompositeOperation = 'lighter';
    for (const [bx, by, r, color] of [[0.08, 0.15, 190, '#ff7a45'], [0.9, 0.1, 210, '#3f8cff'],
      [0.55, 1.1, 210, '#ff4fa3'], [0.15, 1.05, 170, '#22c7b8'], [0.98, 0.95, 160, '#ffc24b']]) {
      const grd = g.createRadialGradient(bx * w, by * h, 0, bx * w, by * h, r);
      grd.addColorStop(0, color + 'b0');
      grd.addColorStop(1, color + '00');
      g.fillStyle = grd;
      g.fillRect(0, 0, w, h);
    }
    g.globalCompositeOperation = 'source-over';
    // Чёткие края, на которых видно преломление кромки.
    g.fillStyle = 'rgba(255,255,255,0.9)';
    g.font = `200 92px ${FONT_UI}`;
    g.textAlign = 'center';
    g.fillText('21:47', w / 2, 112);
    g.textAlign = 'left';
    g.fillStyle = 'rgba(255,255,255,0.14)';
    roundRect(g, 30, 140, w - 60, 52, 16);
    g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.3)';
    g.stroke();
  }

  // Середина панели задач Windows 10: закреплённые приложения, активное — с чертой.
  function drawTaskbar(g, w, y0, h) {
    g.fillStyle = '#16171a';
    g.fillRect(0, y0, w, h);
    g.fillStyle = 'rgba(255,255,255,0.06)';
    g.fillRect(0, y0, w, 1);
    const icons = ['#3d7bd9', '#e8a33d', '#4caf7a', '#9a6ad6', '#d9534f', '#2fa4c9', '#c9c9c9'];
    const x0 = w / 2 - (icons.length * 48) / 2;
    icons.forEach((color, i) => {
      const x = x0 + i * 48 + 14;
      g.fillStyle = color;
      roundRect(g, x, y0 + 10, 20, 20, 4);
      g.fill();
      if (i === 2) {
        g.fillStyle = 'rgba(255,255,255,0.08)';
        g.fillRect(x - 14, y0, 48, h);
        g.fillStyle = '#76b9ed';
        g.fillRect(x - 14, y0 + h - 2, 48, 2);
      }
    });
  }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  const SCENES = { doc: drawDoc, code: drawCode, photo: drawPhoto };

  // ------------------------------------------------------------ GLSL

  const FRAG = `#version 300 es
precision highp float;
uniform sampler2D uScene;
uniform vec2 uRes;       // холст, px устройства
uniform float uPx;       // px устройства на px макета
uniform vec2 uTile;      // плитка, px макета
uniform vec4 uPrim[6];   // капсулы формы: центр xy, полуразмеры zw
uniform int uPrimN;
uniform float uK;        // гладкость слияния капсул
uniform float uClipY;    // ниже — панель задач: стекло выходит из-за неё
uniform vec4 uGlass;     // материализация m, преломление A, кромка h, размытие
uniform vec4 uShadow;    // сдвиг тени вниз, спад, сила, мягкость края формы (px устройства)
uniform vec4 uRipple;    // кольцо ряби: расстояние от кромки пилюли, сила px, ширина px
uniform vec4 uSilk;      // шёлк: виден, полудлина прорисовки, шёлк поверх фона без стекла
uniform vec2 uC;         // центр и размер пилюли в покое
uniform vec2 uCap;
uniform float uTone;     // 0 — тёмный фон под пилюлей, 1 — светлый
uniform float uPhrase;
uniform float uFlow;
uniform float uLevel;
uniform float uSeed;
out vec4 outColor;

const vec2 LIGHT = vec2(0.70710678, -0.70710678);
const float SPEC = 0.25;

vec2 layoutPx(vec2 frag) { return vec2(frag.x, uRes.y - frag.y) / uPx; }
float sdRoundBox(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
float sdPill(vec2 p, vec2 c, float w, float h) { return sdRoundBox(p - c, vec2(w, h) * 0.5, h * 0.5); }
float smin(float a, float b, float k) {
  k = max(k, 1e-4) * (16.0 / 3.0);
  float h = max(k - abs(a - b), 0.0) / k;
  return min(a, b) - h * h * h * (4.0 - h) * k * (1.0 / 16.0);
}

// Рябь по фону: кольцо вокруг пилюли сдвигает фон вдоль нормали её формы.
vec2 ripple(vec2 p) {
  if (uRipple.y <= 0.0) return vec2(0.0);
  float s = sdPill(p, uC, uCap.x, uCap.y);
  const float e = 0.75;
  vec2 g = vec2(sdPill(p + vec2(e, 0.0), uC, uCap.x, uCap.y) - sdPill(p - vec2(e, 0.0), uC, uCap.x, uCap.y),
                sdPill(p + vec2(0.0, e), uC, uCap.x, uCap.y) - sdPill(p - vec2(0.0, e), uC, uCap.x, uCap.y));
  vec2 n = length(g) > 1e-5 ? normalize(g) : vec2(0.0, -1.0);
  float x = (s - uRipple.x) / uRipple.z;
  return n * uRipple.y * x * exp(-x * x);
}
vec3 sceneAt(vec2 p, float lod) { return textureLod(uScene, (p + ripple(p)) / uTile, lod).rgb; }
vec3 sceneBlur(vec2 p, float r) {
  if (r < 0.6) return sceneAt(p, 0.0);
  float lod = log2(max(r * uPx * 0.45, 1.0));
  vec3 acc = vec3(0.0); float w = 0.0;
  for (int i = 0; i < 12; i++) {
    float fi = float(i);
    float a = fi * 2.39996323;
    float rr = r * sqrt((fi + 0.5) / 12.0);
    float k = 1.0 - 0.5 * fi / 12.0;
    acc += sceneAt(p + vec2(cos(a), sin(a)) * rr, lod) * k;
    w += k;
  }
  return acc / w;
}
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

float shape(vec2 p) {
  float d = 1e5;
  for (int i = 0; i < 6; i++) {
    if (i >= uPrimN) break;
    vec4 c = uPrim[i];
    float di = sdRoundBox(p - c.xy, c.zw, min(c.z, c.w));
    d = i == 0 ? di : smin(d, di, uK);
  }
  return d;
}
float shapeDist(vec2 p, out vec2 n) {
  const float e = 0.5;
  float f = shape(p);
  vec2 gr = vec2(shape(p + vec2(e, 0.0)) - shape(p - vec2(e, 0.0)), shape(p + vec2(0.0, e)) - shape(p - vec2(0.0, e))) / (2.0 * e);
  float gl = length(gr);
  n = gl > 1e-5 ? gr / gl : vec2(0.0, -1.0);
  return f / max(gl, 0.25);
}
vec2 shapeNormal(vec2 p) { vec2 n; shapeDist(p, n); return n; }

// Шёлк — дословно из voice/sketches.js, только масштаб рисунка — от высоты
// пилюли в покое: у «Шва» стекло раскрывается вокруг уже прочерченной нити.
const float SILK_H = 56.0;
const float SILK_ZOOM = 1.6;
const float SILK_CURL = 2.1;
const float SILK_SPREAD = 1.3;
const int SILK_STRANDS = 32;
struct Silk { float d; float t; float body; };
Silk silkField(vec2 q, float gain) {
  float ph = uPhrase;
  vec2 base = q / (SILK_H * 0.5 * SILK_ZOOM);
  float amp = mix(0.07, 0.28, ph);
  float n = float(SILK_STRANDS);
  float acc = 0.0, accT = 0.0, wide = 0.0;
  for (int i = 0; i < SILK_STRANDS; i++) {
    float fi = float(i) / n;
    vec2 p = base;
    float fr = SILK_CURL, a = amp;
    for (int j = 0; j < 3; j++) {
      float fj = float(j);
      p += a * vec2(sin(p.y * fr * 1.3 + fi * 2.4 * SILK_SPREAD + uSeed + fj * 1.7 + uFlow * (0.6 + 0.5 * fj)),
                    sin(p.x * fr + fi * 3.1 * SILK_SPREAD + uSeed * 1.3 + fj * 2.3 - uFlow * (1.0 + 0.6 * fj)));
      fr *= 1.7; a *= 0.6;
    }
    float d = abs(p.y);
    float w = exp(-pow(d / 0.05, 1.4)) + 0.06 / (1.0 + d * d / 0.0156);
    acc += w;
    accT += w * fi;
    wide += 1.0 / (1.0 + d * d / 0.2);
  }
  Silk s;
  s.t = accT / max(acc, 1e-4);
  float k = 24.0 / n;
  s.d = 1.0 - exp(-acc * k * 0.13 * gain * mix(0.5, 1.0, ph) * (0.88 + 0.24 * uLevel));
  s.body = (1.0 - exp(-wide * k * 0.05)) * mix(0.5, 1.0, ph);
  return s;
}
vec3 silkGlow(float t) { return mix(vec3(0.10, 0.84, 1.0), vec3(0.58, 0.42, 1.0), t); }
vec3 silkOver(vec3 col, Silk s, float tone, vec3 core) {
  float heat = smoothstep(0.7, 1.0, s.d) * 0.5;
  vec3 e = mix(silkGlow(s.t), vec3(1.0), heat) * s.d;
  vec3 onDark = 1.0 - (1.0 - col) * (1.0 - e);
  vec3 ink = mix(vec3(0.0, 0.58, 1.0), vec3(0.50, 0.30, 1.0), s.t);
  ink = mix(ink, core, smoothstep(0.84, 1.0, s.d) * 0.3);
  vec3 onLight = mix(col, ink, pow(s.d, 1.6) * 0.7);
  return mix(onDark, onLight, tone);
}
float silkReveal(vec2 q) { return 1.0 - smoothstep(uSilk.y - 10.0, uSilk.y, abs(q.x)); }
vec3 silkIn(vec3 col, vec2 q, float inside, float tone) {
  Silk s = silkField(q, 2.1);
  float m = uSilk.x * silkReveal(q);
  s.d *= m; s.body *= m;
  vec3 glass = col;
  vec3 bodyInk = mix(vec3(0.16, 0.38, 0.92), vec3(0.42, 0.28, 0.90), s.t);
  col = mix(col, bodyInk, s.body * mix(0.12, 0.08, tone));
  return mix(glass, silkOver(col, s, tone, vec3(0.74, 0.95, 1.0)), smoothstep(0.6, 2.2, inside));
}

// Кромка, как в приложении: блик 1 px цвета контента, тёмная кромка iOS 27 и
// лепесток света со стороны источника — все гаснут вместе с материализацией.
vec3 rim(vec3 col, vec2 p, vec2 n, float inside, float m) {
  float e1 = 1.0 - smoothstep(0.0, 1.0, inside);
  float w = pow(max(dot(n, LIGHT), 0.0), 3.0) + pow(max(-dot(n, LIGHT), 0.0), 3.0);
  float l = luma(col);
  vec3 vib = clamp(1.45 * (vec3(l) + 2.07 * (col - vec3(l))) + 0.05, 0.0, 1.0);
  col = mix(col, vib, e1 * (0.5 + 0.5 * w) * m);
  if (inside < 1.6) {
    vec2 tg = vec2(-n.y, n.x);
    float curv = length(shapeNormal(p + tg * 2.0) - shapeNormal(p - tg * 2.0)) / 4.0;
    float ends = clamp(curv * 28.0, 0.0, 1.0);
    float width = mix(0.5, 1.0, ends);
    float mul = mix(0.925, 0.83, ends);
    float band = 1.0 - smoothstep(width * 0.6, width + 0.4, inside);
    col *= mix(1.0, mul, band * m);
  }
  float wide = 1.8;
  if (inside < wide + 0.5) {
    float c = dot(n, LIGHT);
    float lobe = pow(max(c, 0.0), 6.0) + 0.5 * pow(max(-c, 0.0), 6.0);
    float k = lobe * SPEC * m;
    float bright = smoothstep(0.5, 0.85, luma(col));
    float band = 1.0 - smoothstep(0.3, wide, inside);
    col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
    float e2 = 1.0 - smoothstep(0.35, 1.25, inside);
    col *= 1.0 - 0.42 * bright * e2 * k;
  }
  return col;
}

void main() {
  vec2 p = layoutPx(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  float tone = uTone;
  vec2 q = p - uC;
  // Нить, прочерченная ещё до стекла («Шов»), лежит прямо на фоне.
  if (uSilk.z > 0.001) {
    Silk s = silkField(q, 2.1);
    s.d *= uSilk.z * silkReveal(q);
    bg = silkOver(bg, s, tone, vec3(0.74, 0.95, 1.0));
  }
  if (uPrimN == 0 || p.y > uClipY) { outColor = vec4(bg, 1.0); return; }
  float d0 = shape(p);
  if (d0 > 120.0) { outColor = vec4(bg, 1.0); return; }
  float m = clamp(uGlass.x, 0.0, 1.0);
  vec2 n;
  float dist = shapeDist(p, n);
  float cover = clamp(0.5 - dist * uPx / max(uShadow.w, 1.0), 0.0, 1.0);
  float sd = shape(p - vec2(0.0, uShadow.x));
  float sh = uShadow.z * m * exp(-max(sd, 0.0) / uShadow.y) * smoothstep(-uShadow.y, 0.0, sd);
  vec3 under = bg * (1.0 - sh * (1.0 - cover));
  if (cover <= 0.0 || m <= 0.001) { outColor = vec4(under, 1.0); return; }

  float inside = max(-dist, 0.0);
  float t = clamp(1.0 - inside / max(uGlass.z, 0.5), 0.0, 1.0);
  // Выборка у кромки идёт внутрь: A > h, кромка показывает перевёрнутый фон.
  float disp = uGlass.y * m * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  vec2 src = p - n * disp;
  float frost = uGlass.w * m;
  vec3 col;
  if (inside < uGlass.z + 1.0) {
    col.r = sceneBlur(p - n * disp * 1.035, frost).r;
    col.g = sceneBlur(src, frost).g;
    col.b = sceneBlur(p - n * disp * 0.965, frost).b;
  } else {
    col = sceneBlur(src, frost);
  }
  col = clamp(col * mix(1.0, 0.914, m) + 0.086 * m, 0.0, 1.0);
  if (uSilk.x > 0.001) col = silkIn(col, mix(p, src, 0.3) - uC, inside, tone);
  col = rim(col, p, n, inside, m);
  outColor = vec4(mix(under, col, cover), 1.0);
}
`;

  // ------------------------------------------------------------ движение

  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const mix = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };

  /** Пружина SwiftUI в замкнутом виде: response — период, с; damping — доля
   *  критического. Кадр раскадровки — то же положение, что и живьём. */
  function spring(t, from, to, response, damping, delay = 0) {
    t -= delay;
    if (t <= 0) return from;
    const w = (2 * Math.PI) / response;
    const x0 = from - to;
    if (damping < 1) {
      const wd = w * Math.sqrt(1 - damping * damping);
      return to + Math.exp(-damping * w * t) * (x0 * Math.cos(wd * t) + ((damping * w * x0) / wd) * Math.sin(wd * t));
    }
    return to + x0 * (1 + w * t) * Math.exp(-w * t);
  }
  const speed = (f, t) => (f(t + 0.004) - f(t - 0.004)) / 0.008;

  const pill = (cx, cy, hw, hh) => [cx, cy, Math.max(hw, 0.01), Math.max(hh, 0.01)];
  // Покой «Слушаю»: стекло Линзы целиком, шёлк в паузе на всю капсулу.
  const rest = (over) => Object.assign({
    prims: [pill(C[0], C[1], CW / 2, CH / 2)], k: 0.01, clipY: 1e4,
    glass: [1, 41, 13, 2.4], shadow: [8, 30, 0.035, 1], ripple: [0, 0, 1], silk: [1, 1e4, 0],
  }, over);
  // Кромка не толще половины самой тонкой части формы, иначе она съедает её целиком.
  const bevelFor = (half) => Math.min(13, 0.46 * Math.max(half, 0.5));

  const VARIANTS = [
    {
      id: 'now', name: 'Сейчас',
      line: 'Материализация из приложения: форма на месте сразу, стекло проступает пружиной 0.45 с, масштаб 0.96 → 1.',
      at(t) {
        const m = spring(t, 0, 1, 0.45, 0.8);
        const mc = clamp01(m);
        const s = 0.96 + 0.04 * m;
        return rest({
          prims: [pill(C[0], C[1], (CW / 2) * s, (CH / 2) * s)],
          glass: [mc, 41 * mc, 13 * (0.35 + 0.65 * mc), 2.4],
          silk: [smooth(0.6, 1, mc), 1e4, 0],
        });
      },
    },
    {
      id: 'rise', name: 'Всплытие',
      line: 'Выныривает из-за панели задач и поднимается на место с лёгким перелётом. На скорости вытягивается, на месте округляется.',
      at(t) {
        const y = (u) => spring(u, EDGE + CH / 2 + 6, C[1], 0.55, 0.72);
        const e = clamp01(Math.abs(speed(y, t)) / 1800) * 0.14;
        return rest({
          prims: [pill(C[0], y(t), (CW / 2) * (1 - e * 0.5), (CH / 2) * (1 + e))],
          clipY: EDGE,
          silk: [smooth(0.08, 0.4, t), 1e4, 0],
        });
      },
    },
    {
      id: 'pull', name: 'Отрыв',
      line: 'Край панели вспухает, капля тянется вверх на перемычке, перемычка рвётся — и капля растекается в капсулу.',
      at(t) {
        const head = smooth(0, 0.25, t);
        const y = spring(t, EDGE - 4, C[1], 0.62, 0.76, 0.05);
        const r = 5 + 15 * head;
        const hw = t < 0.25 ? r : spring(t, 20, CW / 2, 0.55, 0.62, 0.25);
        const hh = t < 0.25 ? r : spring(t, 20, CH / 2, 0.42, 0.5, 0.25);
        const prims = [pill(C[0], y, hw, hh)];
        // Перемычка — вертикальная капсула от края до капли; тоньше 0.6 px — порвалась.
        const neck = 9 * smooth(0, 0.08, t) * (1 - smooth(0.14, 0.3, t));
        if (neck > 0.6) prims.push(pill(C[0], (EDGE + y) / 2, neck, (EDGE - y) / 2 + neck));
        const bulge = smooth(0, 0.06, t) * (1 - smooth(0.16, 0.42, t));
        if (bulge > 0.05) prims.push(pill(C[0], EDGE + 2, 34 * bulge, 10 * bulge));
        return rest({
          prims, k: 5, clipY: EDGE,
          glass: [1, 41 * clamp01(hh / 28), bevelFor(Math.min(hw, hh)), 2.4],
          silk: [smooth(0.35, 0.7, t), 1e4, 0],
        });
      },
    },
    {
      id: 'drop', name: 'Капля',
      line: 'На месте пилюли набухает капля, упруго округляется до диска и растекается вширь в капсулу.',
      at(t) {
        const hh = Math.max(0, spring(t, 0, CH / 2, 0.32, 0.6));
        const w = spring(t, CH, CW, 0.5, 0.78, 0.2);
        const hw = Math.max(hh, (w / 2) * smooth(0, 1, hh / (CH / 2)));
        const k = clamp01(hh / (CH / 2));
        return rest({
          prims: [pill(C[0], C[1], hw, hh)],
          glass: [smooth(0, 0.06, t), 41 * Math.pow(k, 1.5), bevelFor(hh), 2.4],
          silk: [smooth(0.3, 0.6, t), 1e4, 0],
        });
      },
    },
    {
      id: 'merge', name: 'Слияние',
      line: 'Пять капель проступают вокруг места пилюли, сбегаются и сливаются в одну капсулу — Капли наоборот.',
      at(t) {
        const DROPS = [[-92, 8, 8], [-44, -16, 11], [6, 14, 13], [50, -12, 10], [94, 6, 8]];
        const conv = spring(t, 0, 1, 0.55, 0.85, 0.12);
        const prims = DROPS.map(([x, y, r], i) => {
          const s = clamp01(spring(t, 0, 1, 0.3, 0.7, 0.03 * i));
          return pill(C[0] + mix(x, x * 0.45, conv), C[1] + mix(y, 0, conv), 0, 0).map((v, j) => (j < 2 ? v : Math.min(26, r * s * mix(1, 2, conv))));
        });
        const grow = clamp01(spring(t, 0, 1, 0.5, 0.8, 0.32));
        if (grow > 0.02) prims.push(pill(C[0], C[1], (CW / 2) * grow, (CH / 2) * grow));
        return rest({
          prims, k: mix(3.5, 0.01, smooth(0.75, 1.1, t)),
          glass: [smooth(0, 0.05, t), mix(16, 41, conv), mix(4.5, 13, conv), 2.4],
          silk: [smooth(0.45, 0.8, t), 1e4, 0],
        });
      },
    },
    {
      id: 'land', name: 'Приземление',
      line: 'Опускается на экран из глубины: крупнее, мягче, тень далеко. Касание — и по фону расходится кольцо ряби.',
      at(t) {
        const z = Math.max(0, spring(t, 1, 0, 0.5, 0.92));
        const s = 1 + 0.12 * z;
        const after = t - 0.3;
        const ripple = after > 0
          // Сила 7 px давала смещение в полтора пикселя — кольца не было видно.
          ? [150 * Math.pow(after / 0.7, 0.7), 16 * Math.exp(-after / 0.3), 12 + 20 * after]
          : [0, 0, 1];
        return rest({
          prims: [pill(C[0], C[1], (CW / 2) * s, (CH / 2) * s)],
          glass: [smooth(0, 0.12, t), 41, 13, 2.4 + 5 * z],
          shadow: [8 + 26 * z, 30 + 36 * z, 0.035 * (1 - 0.3 * z), 1 + 10 * z],
          ripple,
          silk: [smooth(0.25, 0.55, t), 1e4, 0],
        });
      },
    },
    {
      id: 'seam', name: 'Шов',
      line: 'Сначала нить шёлка прочерчивается от середины, потом стекло раскрывается вокруг неё, как веко. Голос рождает пилюлю.',
      at(t) {
        const reveal = spring(t, 0, 92, 0.38, 0.95);
        const h = Math.max(0, spring(t, 0, CH, 0.42, 0.68, 0.24));
        return rest({
          prims: [pill(C[0], C[1], CW / 2, h / 2)],
          glass: [smooth(0.24, 0.32, t), 41 * Math.pow(clamp01(h / CH), 1.5), bevelFor(h / 2), 2.4],
          silk: [1, reveal, 1 - smooth(0.3, 0.5, t)],
        });
      },
    },
  ];

  /** Живьём: появление, покой, нынешний уход и пауза — по кругу. */
  function liveState(v, t) {
    if (t < HOLD) return v.at(t);
    const st = v.at(HOLD);
    const m = clamp01(spring(t, 1, 0, 0.32, 1.0, HOLD));
    const s = 0.96 + 0.04 * m;
    st.prims = st.prims.map(([x, y, w, h]) => [x, y, w * s, h * s]);
    st.glass = [st.glass[0] * m, st.glass[1] * m, st.glass[2], st.glass[3]];
    st.silk = [st.silk[0] * smooth(0.3, 1, m), st.silk[1], st.silk[2]];
    if (m < 0.003) st.prims = [];
    return st;
  }

  // ------------------------------------------------------------ WebGL

  const VERT = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

  function compile(gl, type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const numbered = src.split('\n').map((l, i) => `${i + 1}: ${l}`).join('\n');
      throw new Error(gl.getShaderInfoLog(sh) + '\n' + numbered);
    }
    return sh;
  }

  function makeRenderer(canvas) {
    const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, premultipliedAlpha: false, preserveDrawingBuffer: true });
    if (!gl) return null;
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.bindAttribLocation(prog, 0, 'aPos');
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    const u = {};
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(prog, i);
      u[info.name.replace(/\[0\]$/, '')] = gl.getUniformLocation(prog, info.name);
    }
    return { gl, canvas, prog, u, textures: {}, prim: new Float32Array(24) };
  }

  // Фон — сцена в рабочей области и панель задач под ней; рисуется один раз на
  // масштаб и сцену.
  const backdrops = {};
  function backdrop(sceneId, px) {
    const key = sceneId + '@' + px;
    if (backdrops[key]) return backdrops[key];
    const c = document.createElement('canvas');
    c.width = Math.round(TILE_W * px);
    c.height = Math.round(TILE_H * px);
    const g = c.getContext('2d', { willReadFrequently: true });
    g.scale(px, px);
    g.save();
    g.beginPath();
    g.rect(0, 0, TILE_W, EDGE);
    g.clip();
    SCENES[sceneId](g, TILE_W, EDGE);
    g.restore();
    drawTaskbar(g, TILE_W, EDGE, TILE_H - EDGE);
    // Тон вуали — как в приложении: по средней светлоте фона под пилюлей.
    const data = g.getImageData(Math.round((C[0] - CW / 2) * px), Math.round((C[1] - CH / 2) * px),
      Math.round(CW * px), Math.round(CH * px)).data;
    let sum = 0, n = 0;
    for (let i = 0; i < data.length; i += 4 * 5) {
      sum += (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
      n++;
    }
    backdrops[key] = { canvas: c, tone: clamp01((sum / n - 0.38) / 0.2) };
    return backdrops[key];
  }

  function texture(r, sceneId, px) {
    const key = sceneId + '@' + px;
    if (r.textures[key]) return r.textures[key];
    const gl = r.gl;
    const bd = backdrop(sceneId, px);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bd.canvas);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    r.textures[key] = { tex, tone: bd.tone };
    return r.textures[key];
  }

  function render(r, sceneId, zoom, st) {
    const gl = r.gl;
    const px = zoom * Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(TILE_W * px), h = Math.round(TILE_H * px);
    if (r.canvas.width !== w || r.canvas.height !== h) {
      r.canvas.width = w;
      r.canvas.height = h;
    }
    const bg = texture(r, sceneId, px);
    const u = r.u;
    gl.viewport(0, 0, w, h);
    gl.useProgram(r.prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, bg.tex);
    const set1 = (name, x) => { if (u[name]) gl.uniform1f(u[name], x); };
    const set2 = (name, x, y) => { if (u[name]) gl.uniform2f(u[name], x, y); };
    const set4 = (name, a) => { if (u[name]) gl.uniform4f(u[name], a[0], a[1], a[2], a[3] || 0); };
    if (u.uScene) gl.uniform1i(u.uScene, 0);
    set2('uRes', w, h);
    set1('uPx', px);
    set2('uTile', TILE_W, TILE_H);
    r.prim.fill(0);
    st.prims.slice(0, 6).forEach((pr, i) => r.prim.set(pr, i * 4));
    if (u.uPrim) gl.uniform4fv(u.uPrim, r.prim);
    if (u.uPrimN) gl.uniform1i(u.uPrimN, Math.min(6, st.prims.length));
    set1('uK', st.k);
    set1('uClipY', st.clipY);
    set4('uGlass', st.glass);
    set4('uShadow', st.shadow);
    set4('uRipple', st.ripple);
    set4('uSilk', st.silk);
    set2('uC', C[0], C[1]);
    set2('uCap', CW, CH);
    set1('uTone', bg.tone);
    set1('uPhrase', 0);
    set1('uFlow', 0);
    set1('uLevel', 0.5);
    set1('uSeed', 0.6);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    return px;
  }

  // ------------------------------------------------------------ страница

  const STORE = 'birth-sketches';
  const state = { mode: 'film', speed: 1, scene: 'doc', zoom: 1 };
  try {
    Object.assign(state, JSON.parse(localStorage.getItem(STORE) || '{}'));
  } catch (e) { /* без сохранения — с умолчаний */ }
  // Адрес вида #mode=live&scene=code&only=rise,seam — для разглядывания.
  const hash = new URLSearchParams(location.hash.slice(1));
  for (const key of ['mode', 'scene']) if (hash.has(key)) state[key] = hash.get(key);
  for (const key of ['speed', 'zoom']) if (hash.has(key)) state[key] = Number(hash.get(key));
  const only = hash.has('only') ? hash.get('only').split(',') : null;

  // Раскадровка рисуется одним общим контекстом с копированием в 2D: кадров
  // 42, а контекстов WebGL браузер держит около 16. Живым плиткам — по своему
  // контексту: копирование каждого кадра в 2D тормозит.
  let film = null;
  const rows = document.getElementById('rows');
  const items = [];
  VARIANTS.forEach((v, i) => {
    if (only && !only.includes(v.id)) return;
    const row = document.createElement('section');
    row.className = 'row';
    row.innerHTML = `<div class="meta"><span class="num">${String(i).padStart(2, '0')}</span><h2>${v.name}</h2><p>${v.line}</p></div>` +
      '<div class="frames"></div><div class="live"></div>';
    const frames = FRAMES.map((t) => {
      const fig = document.createElement('div');
      fig.className = 'frame';
      const canvas = document.createElement('canvas');
      fig.appendChild(canvas);
      const label = document.createElement('span');
      label.textContent = `${Math.round(t * 1000)} мс`;
      fig.appendChild(label);
      row.querySelector('.frames').appendChild(fig);
      return { t, canvas };
    });
    const liveCanvas = document.createElement('canvas');
    row.querySelector('.live').appendChild(liveCanvas);
    rows.appendChild(row);
    items.push({ v, row, frames, liveCanvas, live: null, broken: false });
  });

  function fail(item, err) {
    item.broken = true;
    item.row.insertAdjacentHTML('beforeend', `<pre class="error">${String(err.message || err).slice(0, 1600)}</pre>`);
    console.error(item.v.id, err);
  }

  function drawFilm() {
    if (!film) film = makeRenderer(document.createElement('canvas'));
    for (const item of items) {
      if (item.broken) continue;
      try {
        for (const f of item.frames) {
          const px = render(film, state.scene, state.zoom, item.v.at(f.t));
          const [x, y, w, h] = CROP.map((k) => Math.round(k * px));
          f.canvas.width = w;
          f.canvas.height = h;
          f.canvas.style.width = CROP[2] * state.zoom + 'px';
          f.canvas.style.height = CROP[3] * state.zoom + 'px';
          f.canvas.getContext('2d').drawImage(film.canvas, x, y, w, h, 0, 0, w, h);
        }
      } catch (err) {
        fail(item, err);
      }
    }
  }

  const clock = { raf: 0, start: 0 };
  function liveFrame(now) {
    if (!clock.start) clock.start = now;
    const t = (((now - clock.start) / 1000) * state.speed) % LOOP;
    for (const item of items) {
      if (item.broken) continue;
      try {
        if (!item.live) item.live = makeRenderer(item.liveCanvas);
        render(item.live, state.scene, state.zoom, liveState(item.v, t));
        item.liveCanvas.style.width = TILE_W * state.zoom + 'px';
        item.liveCanvas.style.height = TILE_H * state.zoom + 'px';
      } catch (err) {
        fail(item, err);
      }
    }
    clock.raf = requestAnimationFrame(liveFrame);
  }

  function update() {
    document.body.classList.toggle('is-live', state.mode === 'live');
    document.querySelector('[data-key="speed"]').hidden = state.mode !== 'live';
    if (state.mode === 'live') {
      if (!clock.raf) {
        clock.start = 0;
        clock.raf = requestAnimationFrame(liveFrame);
      }
    } else {
      if (clock.raf) cancelAnimationFrame(clock.raf);
      clock.raf = 0;
      drawFilm();
    }
  }

  function syncButtons() {
    for (const seg of document.querySelectorAll('.seg')) {
      const key = seg.dataset.key;
      for (const b of seg.querySelectorAll('button')) b.setAttribute('aria-pressed', String(String(state[key]) === b.dataset.value));
    }
  }

  for (const seg of document.querySelectorAll('.seg')) {
    seg.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      const key = seg.dataset.key;
      const value = key === 'speed' || key === 'zoom' ? Number(b.dataset.value) : b.dataset.value;
      if (state[key] === value) return;
      state[key] = value;
      try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (err) { /* не критично */ }
      syncButtons();
      // Новая скорость — с начала круга, иначе текущее время прыгает.
      if (key === 'speed') clock.start = 0;
      update();
    });
  }

  /** Сколько стоит живой кадр всех плиток, мс: в скрытой вкладке кадров нет,
   *  и частоту по requestAnimationFrame не снять. */
  function bench({ frames = 30, t = 0.42 } = {}) {
    const result = {};
    for (const item of items) {
      if (!item.live) item.live = makeRenderer(item.liveCanvas);
      const gl = item.live.gl;
      render(item.live, state.scene, state.zoom, liveState(item.v, t));
      gl.finish();
      const t0 = performance.now();
      for (let i = 0; i < frames; i++) render(item.live, state.scene, state.zoom, liveState(item.v, t + i * 0.016));
      gl.finish();
      result[item.v.id] = +((performance.now() - t0) / frames).toFixed(2);
    }
    return result;
  }
  window.BirthSketches = { bench };

  syncButtons();
  // Шрифты Segoe на фонах: ждём их, иначе первый кадр уйдёт с запасным шрифтом.
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(update);
})();
