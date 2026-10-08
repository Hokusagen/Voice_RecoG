/* Дарви в покое: постоянный элемент в правом нижнем углу, стоп-кадры.
 *
 * Решено (DARVI-SKILLS.md, «Где живёт Дарви на экране»): Дарви на экране
 * всегда — один маленький элемент в углу, и карточка ответа раскрывается от
 * него. Здесь выбирается, каким он стоит в покое: варианты сильно разные, без
 * анимации — так же выбирали голос (voice/). Плитка — угол экрана: рабочая
 * область, панель задач Windows 10 внизу, Дарви у угла с тем же отступом
 * 20 px, что у карточки (ui/card.py, MARGIN).
 *
 * Стекло — числа Линзы из voice/sketches.js и src/ui/lens_shader.py: размытие,
 * тон-вуаль, тёмная кромка, блик. Только толщина (h и A) ужата: у плашки
 * h 13 px на высоту 56, а у элемента в 40 px та же кромка съела бы его целиком.
 */
(function () {
  'use strict';

  const TILE_W = 360;
  const TILE_H = 210;
  const TASK_H = 40;
  const WORK_H = TILE_H - TASK_H;
  const MARGIN = 20;
  const FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
  const FONT_CODE = '"Cascadia Code", "Cascadia Mono", Consolas, monospace';

  // ------------------------------------------------------------ фоны

  const DOC = 'Дарви живёт в углу экрана и не мешает работе: под ним документ, редактор или обои. ' +
    'Его видно боковым зрением, но взгляд за него не цепляется, пока он не нужен. Спросил голосом — ' +
    'от него раскрывается карточка с ответом, закрыл — он снова стоит в углу. Стекло, а не наклейка: ' +
    'сквозь него виден текст, и край экрана остаётся краем.';

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
      if (g.measureText(test).width > w - 30 && line) {
        g.fillText(line, 16, y);
        line = word;
        y += 23;
        if (y > h + 20) break;
      } else line = test;
    }
  }

  const CODE = [
    ['    def ', 'voice', '(self, dt: float, level: float) -> float:'],
    ['        ', '# Фраза ведёт свет, слог — только яркость.', ''],
    ['        on = self.voice_on.set(', '1.0', ' if level > 1e-6 else 0.0)'],
    ['        phrase = self.phrase.step(dt, level)', '', ''],
    ['        ', 'return', ' clamp01(0.2 * level + 0.8 * phrase)'],
    ['', '', ''],
    ['    def ', 'paint', '(self, painter: QPainter) -> None:'],
    ['        width = ', 'max', '(self.w.value, PILL_H)'],
    ['        ', '# Покой — тот же материал, что у плашки.', ''],
    ['        ', 'return', ' width'],
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
    // Мини-карта и полоса прокрутки у правого края, как в VS Code: в углу
    // редактора почти всегда они, а не пустота.
    const mx = w - 70;
    g.fillStyle = '#232428';
    g.fillRect(mx - 4, 0, 60, h);
    for (let i = 0; i < 52; i++) {
      const y = 3 + i * 3.2;
      const len = 8 + ((i * 37) % 41);
      const indent = (i % 7) * 3;
      g.fillStyle = ['#7d828c', '#8c7fa0', '#6f9c5a', '#b9ad6a'][i % 4] + '88';
      g.fillRect(mx + indent, y, Math.min(len, 52 - indent), 1.6);
    }
    g.fillStyle = 'rgba(121,121,121,0.25)';
    g.fillRect(mx - 4, 0, 60, 46);
    g.fillStyle = 'rgba(121,121,121,0.4)';
    g.fillRect(w - 14, 8, 14, 40);
  }

  function drawPhoto(g, w, h) {
    const base = g.createLinearGradient(0, 0, w, h);
    base.addColorStop(0, '#0e1d3d');
    base.addColorStop(1, '#3a1850');
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    g.globalCompositeOperation = 'lighter';
    for (const [bx, by, r, color] of [[0.08, 0.15, 170, '#ff7a45'], [0.9, 0.1, 190, '#3f8cff'],
      [0.55, 1.1, 190, '#ff4fa3'], [0.15, 1.05, 150, '#22c7b8'], [0.98, 0.95, 140, '#ffc24b']]) {
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
    g.fillText('21:47', w / 2 - 40, 82);
    g.textAlign = 'left';
    g.fillStyle = 'rgba(255,255,255,0.14)';
    roundRect(g, 18, 108, w - 36, 52, 16);
    g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.3)';
    g.stroke();
  }

  // Панель задач Windows 10, правый край: трей, часы, «Свернуть все окна».
  function drawTaskbar(g, w, y0) {
    g.fillStyle = '#16171a';
    g.fillRect(0, y0, w, TASK_H);
    g.fillStyle = 'rgba(255,255,255,0.06)';
    g.fillRect(0, y0, w, 1);
    const cy = y0 + TASK_H / 2;
    g.strokeStyle = 'rgba(255,255,255,0.86)';
    g.fillStyle = 'rgba(255,255,255,0.9)';
    g.lineWidth = 1.2;
    // «Свернуть все окна» — тонкая черта у самого края.
    g.fillStyle = 'rgba(255,255,255,0.22)';
    g.fillRect(w - 6, y0 + 8, 1, TASK_H - 16);
    // Часы в две строки.
    g.fillStyle = 'rgba(255,255,255,0.92)';
    g.font = `400 12px ${FONT_UI}`;
    g.textAlign = 'center';
    g.fillText('21:47', w - 44, cy - 3);
    g.fillText('08.10.2026', w - 44, cy + 13);
    // Центр уведомлений.
    g.beginPath();
    roundRect(g, w - 101, cy - 7, 13, 12, 1.5);
    g.stroke();
    g.fillText('РУС', w - 128, cy + 4);
    // Громкость.
    g.beginPath();
    g.moveTo(w - 168, cy - 3); g.lineTo(w - 165, cy - 3); g.lineTo(w - 161, cy - 7);
    g.lineTo(w - 161, cy + 7); g.lineTo(w - 165, cy + 3); g.lineTo(w - 168, cy + 3); g.closePath();
    g.stroke();
    g.beginPath(); g.arc(w - 160, cy, 5, -0.8, 0.8); g.stroke();
    // Сеть.
    g.beginPath();
    roundRect(g, w - 196, cy - 6, 14, 10, 1.5);
    g.stroke();
    g.fillRect(w - 191, cy + 5, 4, 2);
    // Скрытые значки.
    g.beginPath();
    g.moveTo(w - 222, cy + 2); g.lineTo(w - 218, cy - 2); g.lineTo(w - 214, cy + 2);
    g.stroke();
    g.textAlign = 'left';
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

  const SCENES = [
    { id: 'doc', name: 'Белый документ', draw: drawDoc },
    { id: 'code', name: 'Тёмный редактор', draw: drawCode },
    { id: 'photo', name: 'Обои', draw: drawPhoto },
  ];

  // ------------------------------------------------------------ GLSL: основа

  const HEAD = `#version 300 es
precision highp float;
uniform sampler2D uScene;
uniform vec2 uRes;       // холст, px устройства
uniform float uPx;       // px устройства на px макета
uniform vec2 uTile;      // плитка, px макета
uniform vec2 uCenter;    // центр элемента
uniform vec2 uSize;      // ширина и высота элемента
uniform float uBevel;    // ширина кромки h, px макета
uniform float uAmp;      // сила преломления A, px макета
uniform float uFrost;    // радиус размытия
uniform float uTone;     // 0 — тёмный фон под элементом, 1 — светлый
uniform float uPhrase;
uniform float uFlow;
uniform float uLevel;
uniform float uSeed;
out vec4 outColor;

const vec2 LIGHT = vec2(0.70710678, -0.70710678);
const float SPEC = 0.25;

vec2 layoutPx(vec2 frag) { return vec2(frag.x, uRes.y - frag.y) / uPx; }
vec3 sceneAt(vec2 p, float lod) { return textureLod(uScene, p / uTile, lod).rgb; }
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
`;

  // Шёлк — дословно из voice/sketches.js: числа голоса в лаборатории и в
  // src/ui должны совпадать, а здесь он тот же, только в паузе.
  const SILK = `
const float SILK_ZOOM = 1.6;
const float SILK_CURL = 2.1;
const float SILK_SPREAD = 1.3;
const int SILK_STRANDS = 32;
struct Silk { float d; float t; float body; };
Silk silkField(vec2 q, float gain) {
  float ph = uPhrase;
  vec2 base = q / (uSize.y * 0.5 * SILK_ZOOM);
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
vec3 voice(vec3 col, vec2 q, float inside, float tone) {
  Silk s = silkField(q, 2.1);
  vec3 glass = col;
  vec3 bodyInk = mix(vec3(0.16, 0.38, 0.92), vec3(0.42, 0.28, 0.90), s.t);
  col = mix(col, bodyInk, s.body * mix(0.12, 0.08, tone));
  return mix(glass, silkOver(col, s, tone, vec3(0.74, 0.95, 1.0)), smoothstep(0.6, 2.2, inside));
}
`;

  const NO_VOICE = `
vec3 voice(vec3 col, vec2 q, float inside, float tone) { return col; }
`;

  const GLASS = `
float shapeDist(vec2 p, out vec2 n) {
  const float e = 0.5;
  float f = shape(p);
  vec2 gr = vec2(shape(p + vec2(e, 0.0)) - shape(p - vec2(e, 0.0)), shape(p + vec2(0.0, e)) - shape(p - vec2(0.0, e))) / (2.0 * e);
  float gl = length(gr);
  n = gl > 1e-5 ? gr / gl : vec2(0.0, -1.0);
  return f / max(gl, 0.25);
}
vec2 shapeNormal(vec2 p) { vec2 n; shapeDist(p, n); return n; }

// Кромка: блик 1 px цвета контента, тёмная кромка iOS 27 и лепесток света
// Линзы со стороны источника — как у плашки.
vec3 rim(vec3 col, vec2 p, vec2 n, float inside) {
  float e1 = 1.0 - smoothstep(0.0, 1.0, inside);
  float w = pow(max(dot(n, LIGHT), 0.0), 3.0) + pow(max(-dot(n, LIGHT), 0.0), 3.0);
  float l = luma(col);
  vec3 vib = clamp(1.45 * (vec3(l) + 2.07 * (col - vec3(l))) + 0.05, 0.0, 1.0);
  col = mix(col, vib, e1 * (0.5 + 0.5 * w));
  if (inside < 1.6) {
    vec2 tg = vec2(-n.y, n.x);
    float curv = length(shapeNormal(p + tg * 2.0) - shapeNormal(p - tg * 2.0)) / 4.0;
    float ends = clamp(curv * 28.0, 0.0, 1.0);
    float width = mix(0.5, 1.0, ends);
    float mul = mix(0.925, 0.83, ends);
    float band = 1.0 - smoothstep(width * 0.6, width + 0.4, inside);
    col *= mix(1.0, mul, band);
  }
  float wide = 1.8;
  if (inside < wide + 0.5) {
    float c = dot(n, LIGHT);
    float lobe = pow(max(c, 0.0), 6.0) + 0.5 * pow(max(-c, 0.0), 6.0);
    float k = lobe * SPEC;
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
  float d0 = shape(p);
  if (d0 > 60.0) { outColor = vec4(bg, 1.0); return; }
  vec2 n;
  float dist = shapeDist(p, n);
  float cover = clamp(0.5 - dist * uPx, 0.0, 1.0);
#ifdef NO_SHADOW
  vec3 under = bg;
#else
  float sd = shape(p - vec2(0.0, 6.0));
  float sh = 0.035 * exp(-max(sd, 0.0) / 24.0) * smoothstep(-24.0, 0.0, sd);
  vec3 under = bg * (1.0 - sh);
#endif
  if (cover <= 0.0) { outColor = vec4(under, 1.0); return; }

  float inside = max(-dist, 0.0);
  float t = clamp(1.0 - inside / uBevel, 0.0, 1.0);
  float disp = uAmp * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  vec2 src = p - n * disp;
  vec3 col;
  if (inside < uBevel + 1.0) {
    col.r = sceneBlur(p - n * disp * 1.035, uFrost).r;
    col.g = sceneBlur(src, uFrost).g;
    col.b = sceneBlur(p - n * disp * 0.965, uFrost).b;
  } else {
    col = sceneBlur(src, uFrost);
  }
#ifndef NO_TONE
  col = col * 0.914 + 0.086;
#endif
  float tone = uTone;
  vec2 vp = mix(p, src, 0.3);
  col = voice(col, vp - uCenter, inside, tone);
#ifndef NO_RIM
  col = rim(col, p, n, inside);
#endif
  outColor = vec4(mix(under, col, cover), 1.0);
}
`;

  // ------------------------------------------------------------ варианты

  // Угол рабочей области: правый край плитки и верх панели задач.
  const RIGHT = TILE_W - MARGIN;
  const BOTTOM = WORK_H - MARGIN;
  const f1 = (x) => (Number.isInteger(x) ? x.toFixed(1) : String(x));

  // Каждый вариант — форма (SDF в px макета), толщина стекла и рамка, по
  // которой меряется светлота фона под ним (тон вуали, как в приложении).
  const VARIANTS = [
    (() => {
      const r = 20, cx = RIGHT - r, cy = BOTTOM - r;
      return {
        id: 'bead', name: 'Бусина',
        line: 'Капля стекла Ø 40, только материал. Карточка вытекает из неё вверх.',
        center: [cx, cy], size: [2 * r, 2 * r], bevel: 9, amp: 26,
        glsl: `float shape(vec2 p) { return length(p - vec2(${f1(cx)}, ${f1(cy)})) - ${f1(r)}; }` + NO_VOICE,
      };
    })(),
    (() => {
      const w = 72, h = 28, cx = RIGHT - w / 2, cy = BOTTOM - h / 2;
      return {
        id: 'capsule', name: 'Капсула',
        line: 'Плашка, уснувшая маленькой: 72 × 28. Одно тело на всё — покой, пилюля, карточка.',
        center: [cx, cy], size: [w, h], bevel: 8, amp: 22,
        glsl: `float shape(vec2 p) { return sdPill(p, vec2(${f1(cx)}, ${f1(cy)}), ${f1(w)}, ${f1(h)}); }` + NO_VOICE,
      };
    })(),
    (() => {
      // Капсула стоит торчком за краем экрана, видно её левую половину.
      const hw = 24, hh = 30, cx = TILE_W + 2, cy = BOTTOM - hh;
      return {
        id: 'edge', name: 'У края',
        line: 'Полкапсулы выглядывает из-за правого края экрана, 22 px. Карточка выезжает из-за края.',
        center: [cx, cy], size: [2 * hw, 2 * hh], bevel: 10, amp: 28,
        glsl: `float shape(vec2 p) { return sdRoundBox(p - vec2(${f1(cx)}, ${f1(cy)}), vec2(${f1(hw)}, ${f1(hh)}), ${f1(hw)}); }` + NO_VOICE,
        box: [TILE_W - 22, cy - hh, 22, 2 * hh],
      };
    })(),
    (() => {
      const w = 72, h = 28, cx = RIGHT - w / 2, cy = BOTTOM - h / 2;
      return {
        id: 'silk', name: 'Шёлк в тишине',
        line: 'Та же капсула, а внутри — нить голоса в паузе. Дарви узнаётся по шёлку и в покое.',
        center: [cx, cy], size: [w, h], bevel: 8, amp: 22,
        glsl: `float shape(vec2 p) { return sdPill(p, vec2(${f1(cx)}, ${f1(cy)}), ${f1(w)}, ${f1(h)}); }` + SILK,
        uni: { phrase: 0, flow: 0, level: 0.5, seed: 0.6 },
      };
    })(),
    (() => {
      const r = 22, cx = RIGHT - r, cy = BOTTOM - r;
      return {
        id: 'disk', name: 'Диск',
        line: 'Думающий диск Острова, застывший: пять лепестков, Ø 44. Тело то же, что при распознавании.',
        center: [cx, cy], size: [2 * r, 2 * r], bevel: 10, amp: 28,
        glsl: `float shape(vec2 p) {
  vec2 q = p - vec2(${f1(cx)}, ${f1(cy)});
  float a = atan(q.y, q.x);
  return length(q) - ${f1(r)} * (1.0 + 0.1 * cos(5.0 * a + 0.6));
}` + NO_VOICE,
      };
    })(),
    (() => {
      // Крупная капля и малая на перемычке: малая — выше и левее, к экрану.
      const R = 17, cx = RIGHT - R, cy = BOTTOM - R, r = 6.5, sx = cx - 23, sy = cy - 12;
      return {
        id: 'drop', name: 'Капля со спутником',
        line: 'Крупная капля и малая на перемычке — жидкость Ртути. Асимметрия вместо идеального круга.',
        center: [cx, cy], size: [2 * R, 2 * R], bevel: 8, amp: 24,
        glsl: `float shape(vec2 p) {
  float big = length(p - vec2(${f1(cx)}, ${f1(cy)})) - ${f1(R)};
  float small = length(p - vec2(${f1(sx)}, ${f1(sy)})) - ${f1(r)};
  return smin(big, small, 3.0);
}` + NO_VOICE,
        box: [sx - r, sy - r, cx + R - (sx - r), cy + R - (sy - r)],
      };
    })(),
    (() => {
      const r = 22, cx = RIGHT - r, cy = BOTTOM - r;
      return {
        id: 'ghost', name: 'Призрак',
        line: 'Ни кромки, ни блика, ни тени — одна линза. Виден, только когда под ним текст или край.',
        center: [cx, cy], size: [2 * r, 2 * r], bevel: 14, amp: 34, frost: 0.8,
        defines: ['NO_RIM', 'NO_SHADOW', 'NO_TONE'],
        glsl: `float shape(vec2 p) { return length(p - vec2(${f1(cx)}, ${f1(cy)})) - ${f1(r)}; }` + NO_VOICE,
      };
    })(),
  ];

  // ------------------------------------------------------------ WebGL

  // Один контекст на всю страницу, кадр копируется в 2D-холст плитки: плиток
  // 21, а контекстов WebGL браузер держит около 16 и старые теряет. У живого
  // показа в voice/ копирование тормозило, стоп-кадрам оно не мешает.
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
    return { gl, canvas, programs: {}, textures: {} };
  }

  function program(r, v) {
    if (r.programs[v.id]) return r.programs[v.id];
    const gl = r.gl;
    const defines = (v.defines || []).map((d) => `#define ${d}\n`).join('');
    // #version обязан стоять первой строкой: определения — сразу после неё.
    const head = HEAD.replace('#version 300 es\n', '#version 300 es\n' + defines);
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, head + v.glsl + GLASS));
    gl.bindAttribLocation(prog, 0, 'aPos');
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    const uniforms = {};
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(prog, i);
      uniforms[info.name] = gl.getUniformLocation(prog, info.name);
    }
    r.programs[v.id] = { prog, uniforms };
    return r.programs[v.id];
  }

  // Фон плитки — сцена в рабочей области и панель задач под ней; рисуется
  // один раз на масштаб и идёт во все плитки.
  const backdrops = {};
  function backdrop(sc, px) {
    const key = sc.id + '@' + px;
    if (backdrops[key]) return backdrops[key];
    const c = document.createElement('canvas');
    c.width = Math.round(TILE_W * px);
    c.height = Math.round(TILE_H * px);
    const g = c.getContext('2d', { willReadFrequently: true });
    g.scale(px, px);
    g.textBaseline = 'alphabetic';
    g.save();
    g.beginPath();
    g.rect(0, 0, TILE_W, WORK_H);
    g.clip();
    sc.draw(g, TILE_W, WORK_H);
    g.restore();
    drawTaskbar(g, TILE_W, WORK_H);
    backdrops[key] = { canvas: c, g, px };
    return backdrops[key];
  }

  // Тон вуали — как в приложении: по средней светлоте фона под самим элементом.
  function toneUnder(bd, box) {
    const [x, y, w, h] = box.map((k) => Math.round(k * bd.px));
    const x0 = Math.max(0, x), y0 = Math.max(0, y);
    const w0 = Math.max(1, Math.min(bd.canvas.width - x0, w)), h0 = Math.max(1, Math.min(bd.canvas.height - y0, h));
    const data = bd.g.getImageData(x0, y0, w0, h0).data;
    let sum = 0, n = 0;
    for (let i = 0; i < data.length; i += 4 * 3) {
      sum += (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
      n++;
    }
    return Math.min(1, Math.max(0, (sum / n - 0.38) / 0.2));
  }

  function texture(r, sc, px) {
    const key = sc.id + '@' + px;
    if (r.textures[key]) return r.textures[key];
    const gl = r.gl;
    const bd = backdrop(sc, px);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bd.canvas);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    r.textures[key] = { tex, bd };
    return r.textures[key];
  }

  function render(r, v, sc, zoom, out) {
    const gl = r.gl;
    const px = zoom * Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(TILE_W * px), h = Math.round(TILE_H * px);
    if (r.canvas.width !== w || r.canvas.height !== h) {
      r.canvas.width = w;
      r.canvas.height = h;
    }
    if (out.width !== w || out.height !== h) {
      out.width = w;
      out.height = h;
    }
    out.style.width = TILE_W * zoom + 'px';
    out.style.height = TILE_H * zoom + 'px';
    const { prog, uniforms: u } = program(r, v);
    const bg = texture(r, sc, px);
    const box = v.box || [v.center[0] - v.size[0] / 2, v.center[1] - v.size[1] / 2, v.size[0], v.size[1]];
    gl.viewport(0, 0, w, h);
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, bg.tex);
    const set1 = (name, x) => { if (u[name]) gl.uniform1f(u[name], x); };
    const set2 = (name, x, y) => { if (u[name]) gl.uniform2f(u[name], x, y); };
    if (u.uScene) gl.uniform1i(u.uScene, 0);
    set2('uRes', w, h);
    set1('uPx', px);
    set2('uTile', TILE_W, TILE_H);
    set2('uCenter', v.center[0], v.center[1]);
    set2('uSize', v.size[0], v.size[1]);
    set1('uBevel', v.bevel);
    set1('uAmp', v.amp);
    set1('uFrost', v.frost == null ? 2.4 : v.frost);
    set1('uTone', toneUnder(bg.bd, box));
    const uni = v.uni || {};
    set1('uPhrase', uni.phrase || 0);
    set1('uFlow', uni.flow || 0);
    set1('uLevel', uni.level == null ? 0.5 : uni.level);
    set1('uSeed', uni.seed || 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    out.getContext('2d').drawImage(r.canvas, 0, 0);
  }

  // ------------------------------------------------------------ страница

  const STORE = 'corner-sketches';
  const state = { zoom: 1 };
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
    if (saved.zoom) state.zoom = saved.zoom;
  } catch (e) { /* без сохранения — с умолчаний */ }
  // Адрес вида #zoom=3&only=bead,disk&bare — для снимков и разглядывания.
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('zoom')) state.zoom = Number(hash.get('zoom'));
  const only = hash.has('only') ? hash.get('only').split(',') : null;
  if (hash.has('bare')) document.body.classList.add('bare');

  const rows = document.getElementById('rows');
  const tiles = [];
  const renderer = makeRenderer(document.createElement('canvas'));
  VARIANTS.forEach((v, i) => {
    if (only && !only.includes(v.id)) return;
    const row = document.createElement('section');
    row.className = 'row';
    row.innerHTML = `<div class="meta"><div class="num">${String(i + 1).padStart(2, '0')}</div><h2>${v.name}</h2><p>${v.line}</p></div><div class="tiles"></div>`;
    const box = row.querySelector('.tiles');
    for (const sc of SCENES) {
      const fig = document.createElement('div');
      fig.className = 'tile';
      fig.title = sc.name;
      const canvas = document.createElement('canvas');
      fig.appendChild(canvas);
      box.appendChild(fig);
      tiles.push({ v, sc, canvas, fig, broken: false });
    }
    rows.appendChild(row);
  });

  function paint() {
    document.getElementById('heads').innerHTML = SCENES.map((sc) => `<span style="width:${TILE_W * state.zoom}px">${sc.name}</span>`).join('');
    for (const t of tiles) {
      if (t.broken) continue;
      try {
        render(renderer, t.v, t.sc, state.zoom, t.canvas);
      } catch (err) {
        t.broken = true;
        t.fig.innerHTML = `<pre class="error">${String(err.message || err).slice(0, 1600)}</pre>`;
        console.error(t.v.id, err);
      }
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
      const value = Number(b.dataset.value);
      if (state[key] === value) return;
      state[key] = value;
      try { localStorage.setItem(STORE, JSON.stringify({ zoom: state.zoom })); } catch (err) { /* не критично */ }
      syncButtons();
      paint();
    });
  }

  if (!renderer) {
    rows.innerHTML = '<p class="error">WebGL2 недоступен в этом браузере.</p>';
  } else {
    syncButtons();
    // Шрифты Segoe на фонах: ждём их, иначе первый кадр уйдёт с запасным шрифтом.
    (document.fonts ? document.fonts.ready : Promise.resolve()).then(paint);
  }
})();
