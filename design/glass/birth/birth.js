/* Появление пилюли «Слушаю», второй круг: Капля и Слияние.
 *
 * Отзыв 8.10.2026: пилюля «появляется просто никак — материализуется»; пусть
 * вылетает из низа экрана или красиво рождается на своём месте. Место прежнее:
 * снизу по центру, 96 px над панелью задач (ui.hud_margin). Из шести вариантов
 * первого круга 9.10 выбраны Капля и Слияние — «давай их развивать». Капля —
 * как была и три развития; её пока не трогаем. Слияние второго круга
 * отвергнуто: площадь капель не сходилась с пилюлей, а капли летели друг в
 * друга — «нежидкостное движение». Третий заход — ниже, у констант. Уход у
 * всех нынешний — смотрим только появление.
 *
 * Стекло — числа Линзы, как в src/ui/lens_shader.py: материализация m гасит
 * преломление, размытие, вуаль, блик и тень, а не прозрачность формы. Голос
 * внутри — Шёлк в паузе, теми же числами, что в voice/ и в приложении. Форма —
 * до шестнадцати капсул, каждая со своим поворотом, слитых гладким минимумом:
 * из них собираются капли и перемычки между ними.
 */
(function () {
  'use strict';

  const TILE_W = 520;
  const TILE_H = 300;               // над пилюлей — место, откуда стекают капли
  const EDGE = 264;                 // верх панели задач: низ рабочей области
  const C = [260, EDGE - 96 - 28];  // центр пилюли: 96 px над панелью, как в приложении
  const CW = 200;                   // «Слушаю» — капсула без надписей (lens_hud.LISTEN_W)
  const CH = 56;
  // Кадр раскадровки: пилюля и край панели под ней; кому тесно — свой кадр.
  const CROP = [150, C[1] - 56, 220, TILE_H - (C[1] - 56)];
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
uniform vec4 uPrim[16];  // капсулы формы: центр xy, полуразмеры zw
uniform float uPrimA[16]; // и поворот каждой, рад
uniform int uPrimN;
uniform float uK;        // гладкость слияния капсул
uniform float uClipY;    // ниже — панель задач: стекло выходит из-за неё
uniform vec4 uGlass;     // материализация m, преломление A, кромка h, размытие
uniform vec4 uShadow;    // сдвиг тени вниз, спад, сила, мягкость края формы (px устройства)
uniform vec4 uRipple;    // кольцо ряби: расстояние от кромки пилюли, сила px, ширина px
uniform vec4 uSilk;      // шёлк: виден, полудлина прорисовки, шёлк поверх фона без стекла
uniform float uSilkA;    // поворот нити вместе с вращающимся телом
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
  for (int i = 0; i < 16; i++) {
    if (i >= uPrimN) break;
    vec4 c = uPrim[i];
    vec2 q = p - c.xy;
    float a = uPrimA[i];
    if (a != 0.0) { float ca = cos(a), sa = sin(a); q = vec2(ca * q.x + sa * q.y, -sa * q.x + ca * q.y); }
    float di = sdRoundBox(q, c.zw, min(c.z, c.w));
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
vec2 silkFrame(vec2 q) { float ca = cos(uSilkA), sa = sin(uSilkA); return vec2(ca * q.x + sa * q.y, -sa * q.x + ca * q.y); }
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
  vec2 q = silkFrame(p - uC);
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
  if (uSilk.x > 0.001) col = silkIn(col, silkFrame(mix(p, src, 0.3) - uC), inside, tone);
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

  // Капля первого круга: набухает, упруго округляется до диска, растекается вширь.
  function dropAt(t) {
    const hh = Math.max(0, spring(t, 0, CH / 2, 0.32, 0.6));
    const w = spring(t, CH, CW, 0.5, 0.78, 0.2);
    const hw = Math.max(hh, (w / 2) * smooth(0, 1, hh / (CH / 2)));
    return { hw, hh, k: clamp01(hh / (CH / 2)) };
  }

  // Слияние, третий заход (отзыв 9.10): площадь капель с самого начала равна
  // площади пилюли — масса не берётся из ниоткуда, — и капли не летят друг в
  // друга: сливаются по ходу общего движения — вихря, стекания или роста.
  const AREA = CW * CH - (4 - Math.PI) * (CH / 2) ** 2;  // площадь «Слушаю», px²

  /** Капля площадью area: круг, пока помещается в высоту пилюли, дальше —
   *  капсула той же высоты. Площадь пилюли целиком — ровно пилюля «Слушаю». */
  function blob(cx, cy, area, angle = 0) {
    const h = Math.min(CH / 2, Math.sqrt(Math.max(area, 0) / Math.PI));
    const l = h > 0 ? Math.max(0, (area - Math.PI * h * h) / (4 * h)) : 0;
    return [cx, cy, l + h, h, angle];
  }

  const sdBoxJS = (x, y, bx, by, r) => {
    const qx = Math.abs(x) - bx + r, qy = Math.abs(y) - by + r;
    return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
  };
  /** Сколько капли радиуса r уже влилось в тело: 0 — только коснулась, 1 — целиком
   *  внутри. Что зашло в тело, то тело и забрало: иначе на перекрытии терялась
   *  площадь — во втором заходе до четверти пилюли. */
  // Капля влита целиком, когда её центр ушёл внутрь на (SOAK − 1)·r: при 2 —
  // на весь радиус, и остаток капли ещё торчал в теле — площадь проседала на 9%.
  const SOAK = 1.4;
  function soaked(x, y, r, body) {
    let dx = x - body[0], dy = y - body[1];
    const a = body[4] || 0;
    if (a) { const ca = Math.cos(a), sa = Math.sin(a); [dx, dy] = [ca * dx + sa * dy, -sa * dx + ca * dy]; }
    return clamp01((r - sdBoxJS(dx, dy, body[2], body[3], Math.min(body[2], body[3]))) / (SOAK * r));
  }

  // «Вихрь»: пять капель кружат вокруг зародыша и по спирали уходят в него;
  // радиус орбиты, начальный угол и когда капля целиком влилась, с.
  const VORTEX = [96, 104, 112, 100, 108].map((r0, i) => [r0, 0.4 + (i * 2 * Math.PI) / 5, 0.42 + 0.07 * i]);
  const VORTEX_SEED = 0.25;   // доля площади у зародыша, остальное поровну у пяти капель

  // «Стекание»: доля площади, x от центра пилюли, высота над ней, когда сорвалась.
  // Центр масс капель — ровно над центром пилюли, иначе лужица в конце съезжала бы.
  const RAIN = (() => {
    const f = [0.2, 0.14, 0.18, 0.16, 0.12, 0.2];
    const x = [-70, -38, -6, 28, 52, 74];
    const shift = f.reduce((s, fi, i) => s + fi * x[i], 0);
    const D = [104, 70, 110, 88, 60, 96];
    const t0 = [0.02, 0, 0.1, 0.05, 0.12, 0.07];
    // Время падения — как у свободного падения: растёт как корень из высоты.
    return f.map((fi, i) => ({ f: fi, x: x[i] - shift, D: D[i], t0: t0[i], T: 0.035 * Math.sqrt(D[i]) }));
  })();

  // «Роса»: зародыши парами, симметричными относительно центра пилюли, — общий
  // центр масс всегда в её центре, и последняя капля встаёт ровно на место.
  const DEW_GROW = 0.5;   // за сколько конденсируется каждая капля, с
  const DEW_SNAP = 0.07;  // за сколько две коснувшиеся капли становятся одной
  const DEW_SEEDS = (() => {
    const half = [[-84, -11], [-84, 11], [-54, -11], [-54, 11], [-24, -11], [-24, 11]];
    const jit = [[3, 2], [-2, -1], [4, -2], [-3, 1], [1, 0], [-4, 2]];
    const t0 = [0.03, 0.0, 0.06, 0.02, 0.09, 0.05];
    const w = [0.9, 1.1, 1.0, 0.95, 1.05, 1.0];
    const seeds = half.map(([x, y], i) => ({ x: x + jit[i][0], y: y + jit[i][1], t0: t0[i], w: w[i] }));
    const all = seeds.concat(seeds.map((s) => ({ ...s, x: -s.x, y: -s.y })));
    const total = all.reduce((s, d) => s + d.w, 0);
    return all.map((d) => ({ ...d, m: (d.w / total) * AREA }));
  })();

  const dewMass = (set, u) => set.reduce((s, i) => s + DEW_SEEDS[i].m * smooth(DEW_SEEDS[i].t0, DEW_SEEDS[i].t0 + DEW_GROW, u), 0);
  function dewCenter(set, u) {
    let sx = 0, sy = 0, sm = 0;
    for (const i of set) {
      const d = DEW_SEEDS[i];
      const m = d.m * Math.max(1e-3, smooth(d.t0, d.t0 + DEW_GROW, u));
      sx += m * d.x; sy += m * d.y; sm += m;
    }
    return [C[0] + sx / sm, C[1] + sy / sm];
  }
  // Касание двух горизонтальных капсул: расстояние между их осями минус высоты.
  function dewTouch(a, b) {
    const dx = Math.max(0, Math.abs(a[0] - b[0]) - (a[2] - a[3]) - (b[2] - b[3]));
    return Math.hypot(dx, a[1] - b[1]) - a[3] - b[3] < 0.5;
  }
  const dewShape = (set, u) => blob(...dewCenter(set, u), dewMass(set, u));

  // Слияния считаются один раз: роса детерминирована, и раскадровка и показ
  // живьём берут готовую летопись капель, а не гоняют расчёт с нуля на кадр.
  const DEW_LOG = (() => {
    const log = DEW_SEEDS.map((_, i) => ({ set: [i], born: -1, died: Infinity, parents: null }));
    const alive = () => log.filter((d) => d.died === Infinity);
    const end = Math.max(...DEW_SEEDS.map((d) => d.t0)) + DEW_GROW;
    const join = (a, b, u) => {
      a.died = b.died = u;
      log.push({ set: a.set.concat(b.set), born: u, died: Infinity, parents: [a, b] });
    };
    for (let u = 0; u <= end + 0.05; u += 1 / 480) {
      for (let again = true; again;) {
        again = false;
        const now = alive();
        outer: for (let i = 0; i < now.length; i++) {
          for (let j = i + 1; j < now.length; j++) {
            if (dewTouch(dewShape(now[i].set, u), dewShape(now[j].set, u))) {
              join(now[i], now[j], u);
              again = true;
              break outer;
            }
          }
        }
      }
      // К концу конденсации всё обязано стать одной пилюлей.
      if (u >= end) while (alive().length > 1) join(alive()[0], alive()[1], u);
    }
    return log;
  })();

  const VARIANTS = [
    {
      id: 'drop', name: 'Капля',
      line: 'Как в первом круге: капля набухает, упруго округляется до диска и растекается вширь в капсулу.',
      at(t) {
        const { hw, hh, k } = dropAt(t);
        return rest({
          prims: [pill(C[0], C[1], hw, hh)],
          glass: [smooth(0, 0.06, t), 41 * Math.pow(k, 1.5), bevelFor(hh), 2.4],
          silk: [smooth(0.3, 0.6, t), 1e4, 0],
        });
      },
    },
    {
      id: 'lens', name: 'Капля-линза',
      line: 'Маленькая капля — толстая линза и крупно увеличивает фон. Растекаясь, она сплющивается и успокаивается до стекла пилюли.',
      at(t) {
        const hh0 = Math.max(0, spring(t, 0, CH / 2, 0.32, 0.6));
        const w = (u) => spring(u, CH, CW, 0.5, 0.78, 0.2);
        // Объём сохраняется: пока капля быстро растекается, она чуть ниже.
        const squash = clamp01(Math.abs(speed(w, t)) / 1400) * 0.12;
        const hh = hh0 * (1 - squash);
        const hw = Math.max(hh, (w(t) / 2) * smooth(0, 1, hh0 / (CH / 2)));
        // Купол: кромка во весь радиус и сильное преломление, без матовости —
        // чистая линза; к покою — паспортная толщина и размытие Линзы.
        const relax = smooth(0.2, 0.65, t);
        return rest({
          prims: [pill(C[0], C[1], hw, hh)],
          glass: [smooth(0, 0.06, t), mix(58, 41, relax) * clamp01(hh0 / (CH / 2)),
            mix(hh * 0.95, bevelFor(hh), relax), mix(0.8, 2.4, relax)],
          silk: [smooth(0.35, 0.65, t), 1e4, 0],
        });
      },
    },
    {
      id: 'thread', name: 'Капля с нитью',
      line: 'Голос рождается вместе с каплей: в диске нить шёлка — короткий узелок, и она разворачивается, пока капля растекается.',
      at(t) {
        const { hw, hh, k } = dropAt(t);
        return rest({
          prims: [pill(C[0], C[1], hw, hh)],
          glass: [smooth(0, 0.06, t), 41 * Math.pow(k, 1.5), bevelFor(hh), 2.4],
          silk: [smooth(0.04, 0.16, t), Math.max(0, hw - 12), 0],
        });
      },
    },
    {
      id: 'single', name: 'Капля одним движением',
      line: 'Без двух фаз: капля растёт сразу и вверх, и вширь — высота с упругим перелётом, ширина течёт следом. Быстрее, около 0.4 с.',
      at(t) {
        const hh = Math.max(0, spring(t, 0, CH / 2, 0.36, 0.6));
        const hw = Math.max(hh, spring(t, 0, CW / 2, 0.46, 0.76));
        const k = clamp01(hh / (CH / 2));
        return rest({
          prims: [pill(C[0], C[1], hw, hh)],
          glass: [smooth(0, 0.05, t), 41 * Math.pow(k, 1.5), bevelFor(hh), 2.4],
          silk: [smooth(0.2, 0.45, t), 1e4, 0],
        });
      },
    },
    {
      id: 'vortex', name: 'Вихрь',
      line: 'Пять капель кружат вокруг зародыша и по спирали вливаются в него сбоку, по ходу вращения. Растущая капля вытягивается и, замедляясь, ложится пилюлей.',
      crop: [110, C[1] - 84, 300, TILE_H - (C[1] - 84)],
      at(t) {
        const part = (1 - VORTEX_SEED) / VORTEX.length;
        const rs = Math.sqrt((part * AREA) / Math.PI);
        const phi = spring(t, -1.6 * Math.PI, 0, 0.9, 1.0);
        const sats = VORTEX.map(([r0, th0, end]) => {
          const tau = clamp01(t / end);
          const R = r0 * (1 - tau * tau);
          // Ближе к центру — быстрее: как фигуристка, прижавшая руки.
          const th = th0 + 3.2 * t + 2.0 * (1 - R / r0);
          return [C[0] + R * Math.cos(th) * 1.15, C[1] + R * Math.sin(th) * 0.5];
        });
        // Тело растёт от того, что впитало, и впитывает больше, чем выросло, —
        // несколько проходов сводят это к согласию.
        let soak = sats.map(() => 0);
        let body = 0;
        for (let k = 0; k < 5; k++) {
          body = VORTEX_SEED + part * soak.reduce((sum, a) => sum + a, 0);
          const shape = blob(C[0], C[1], body * AREA, phi);
          soak = sats.map(([x, y], i) => Math.max(soak[i], soaked(x, y, rs, shape)));
        }
        const prims = [];
        sats.forEach(([x, y], i) => { if (soak[i] < 0.999) prims.push(blob(x, y, part * (1 - soak[i]) * AREA)); });
        prims.unshift(blob(C[0], C[1], body * AREA, phi));
        return rest({
          prims, k: 3,
          glass: [smooth(0, 0.06, t), 41, 11, 2.4],
          silk: [smooth(0.6, 0.95, body), 1e4, 0], silkA: phi,
        });
      },
    },
    {
      id: 'rain', name: 'Стекание',
      line: 'Шесть капель — вместе ровно столько стекла, сколько в пилюле, — срываются и стекают вниз, как дождь по окну, и собираются лужицей на месте пилюли.',
      crop: [150, C[1] - 136, 220, TILE_H - (C[1] - 136)],
      at(t) {
        const drops = RAIN.map((d, i) => {
          const tau = clamp01((t - d.t0) / d.T);
          return {
            d, tau, r: Math.sqrt((d.f * AREA) / Math.PI),
            x: d.x + 3 * Math.sin(tau * Math.PI * 1.5 + i) * tau,
            y: C[1] - d.D * (1 - tau * tau),
          };
        });
        // Капля отдаёт лужице ту часть, что ушла ниже её поверхности; лужица
        // от этого выше и забирает больше — несколько проходов до согласия.
        let soak = drops.map(() => 0);
        let pool = 0, sx = 0;
        for (let k = 0; k < 5; k++) {
          pool = drops.reduce((sum, q, i) => sum + q.d.f * soak[i], 0);
          const top = C[1] - Math.min(CH / 2, Math.sqrt((pool * AREA) / Math.PI));
          soak = drops.map((q, i) => Math.max(soak[i], clamp01((q.y + q.r - top) / (SOAK * q.r))));
        }
        pool = drops.reduce((sum, q, i) => sum + q.d.f * soak[i], 0);
        sx = drops.reduce((sum, q, i) => sum + q.d.f * soak[i] * q.x, 0);
        const prims = [];
        drops.forEach((q, i) => {
          if (soak[i] > 0.999) return;
          const r = q.r * Math.sqrt(1 - soak[i]);
          // На скорости капля вытягивается вдоль пути при той же площади.
          const e = 0.18 * q.tau * (1 - soak[i]);
          prims.push([C[0] + q.x, q.y, r / Math.sqrt(1 + e), r * Math.sqrt(1 + e)]);
        });
        if (pool > 0.001) prims.unshift(blob(C[0] + sx / pool, C[1], pool * AREA));
        return rest({
          prims, k: 3,
          glass: [smooth(0, 0.06, t), 41, 11, 2.4],
          silk: [smooth(0.45, 0.9, pool), 1e4, 0],
        });
      },
    },
    {
      id: 'dew', name: 'Роса',
      line: 'Никто никуда не летит: капли конденсируются на месте пилюли, растут, и коснувшиеся сливаются в одну — как роса на холодном стекле.',
      at(t) {
        const prims = [];
        let biggest = 0;
        for (const d of DEW_LOG) {
          if (d.born > t || d.died <= t) continue;
          const snap = d.born < 0 ? 1 : smooth(d.born, d.born + DEW_SNAP, t);
          const [cx, cy] = dewCenter(d.set, t);
          const mass = dewMass(d.set, t);
          biggest = Math.max(biggest, mass);
          prims.push(blob(cx, cy, mass * snap));
          // Пока две капли становятся одной, они ещё видны и отдают ей площадь.
          if (snap < 1) for (const p of d.parents) prims.push(blob(...dewCenter(p.set, t), dewMass(p.set, t) * (1 - snap)));
        }
        const h = Math.min(CH / 2, Math.sqrt(biggest / Math.PI));
        return rest({
          prims, k: 2.5,
          glass: [1, 41 * Math.pow(h / (CH / 2), 1.5), bevelFor(h), 2.4],
          silk: [smooth(0.5, 0.9, biggest / AREA), 1e4, 0],
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
    st.prims = st.prims.map(([x, y, w, h, a]) => [x, y, w * s, h * s, a || 0]);
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
    return { gl, canvas, prog, u, textures: {}, prim: new Float32Array(64), primA: new Float32Array(16) };
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
    r.primA.fill(0);
    st.prims.slice(0, 16).forEach((pr, i) => { r.prim.set(pr.slice(0, 4), i * 4); r.primA[i] = pr[4] || 0; });
    if (u.uPrim) gl.uniform4fv(u.uPrim, r.prim);
    if (u.uPrimA) gl.uniform1fv(u.uPrimA, r.primA);
    if (u.uPrimN) gl.uniform1i(u.uPrimN, Math.min(16, st.prims.length));
    set1('uK', st.k);
    set1('uClipY', st.clipY);
    set4('uGlass', st.glass);
    set4('uShadow', st.shadow);
    set4('uRipple', st.ripple);
    set4('uSilk', st.silk);
    set2('uC', C[0], C[1]);
    set2('uCap', CW, CH);
    set1('uSilkA', st.silkA || 0);
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
    row.innerHTML = `<div class="meta"><span class="num">${String(i + 1).padStart(2, '0')}</span><h2>${v.name}</h2><p>${v.line}</p></div>` +
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
          const crop = item.v.crop || CROP;
          const [x, y, w, h] = crop.map((k) => Math.round(k * px));
          f.canvas.width = w;
          f.canvas.height = h;
          f.canvas.style.width = crop[2] * state.zoom + 'px';
          f.canvas.style.height = crop[3] * state.zoom + 'px';
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
  const sminJS = (a, b, k) => {
    k = Math.max(k, 1e-4) * (16 / 3);
    const h = Math.max(k - Math.abs(a - b), 0) / k;
    return Math.min(a, b) - h * h * h * (4 - h) * k / 16;
  };
  /** Площадь формы варианта в моменты times, в долях площади пилюли «Слушаю» —
   *  та же форма, что в шейдере, по пикселям рабочей области. */
  function areas(id, times = [0.05, 0.12, 0.2, 0.3, 0.45, 0.6, 1.0]) {
    const v = VARIANTS.find((x) => x.id === id);
    return times.map((t) => {
      const st = v.at(t);
      let n = 0;
      for (let y = 0.5; y < Math.min(EDGE, st.clipY); y += 1) {
        for (let x = 0.5; x < TILE_W; x += 1) {
          let d = 1e5;
          st.prims.slice(0, 16).forEach((c, i) => {
            let dx = x - c[0], dy = y - c[1];
            const a = c[4] || 0;
            if (a) { const ca = Math.cos(a), sa = Math.sin(a); [dx, dy] = [ca * dx + sa * dy, -sa * dx + ca * dy]; }
            const di = sdBoxJS(dx, dy, c[2], c[3], Math.min(c[2], c[3]));
            d = i === 0 ? di : sminJS(d, di, st.k);
          });
          if (d < 0) n++;
        }
      }
      return [t, +(n / AREA).toFixed(3)];
    });
  }
  window.BirthSketches = { bench, areas };

  syncButtons();
  // Шрифты Segoe на фонах: ждём их, иначе первый кадр уйдёт с запасным шрифтом.
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(update);
})();
