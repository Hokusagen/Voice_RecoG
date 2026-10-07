/* Голос в «Слушаю» на стекле Линзы: Капли и Шёлк живьём и стоп-кадрами.
 *
 * Живой показ ведёт голос — имитация речи с фразами и паузами или микрофон —
 * через те же огибающие, что в приложении. У каждой плитки свой контекст
 * WebGL. Листы и плёнка для разглядывания — VoiceSketches.sheet() и film(),
 * дрожь и стоимость кадра — trace() и bench(). Стекло —
 * те же числа, что в лаборатории и в приложении (harness.js → liquidGlass,
 * lens.js, src/ui/lens_shader.py), но порядок слоёв свой: свет голоса лежит
 * между телом стекла и кромкой, так что блик и тёмная кромка остаются сверху,
 * а у края свет чуть ломается вместе с фоном — он внутри материала, а не
 * наклеен поверх.
 */
(function () {
  'use strict';

  const TILE_W = 320;
  const TILE_H = 140;
  const PILL_W = 200;
  const PILL_H = 56;
  const FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
  const FONT_CODE = '"Cascadia Code", "Cascadia Mono", Consolas, monospace';

  // ------------------------------------------------------------ фоны

  const DOC = 'Плашка висит над чужими окнами: над белым документом, тёмным редактором и видео. ' +
    'Поэтому голос в ней обязан читаться боковым зрением на любом фоне, а сама она — оставаться ' +
    'стеклом, сквозь которое виден текст. Говоришь — свет живёт, замолчал — успокаивается. ' +
    'Разница между фразой и паузой видна сразу, но без вспышек на каждый слог и без радуги. ' +
    'Движение одно, остальное тише; форма и свет вместо надписей.';

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
      if (g.measureText(test).width > w - 34 && line) {
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
  ];

  function drawCode(g, w, h) {
    g.fillStyle = '#1e1f22';
    g.fillRect(0, 0, w, h);
    g.font = `400 13px ${FONT_CODE}`;
    const colors = ['#cfd3da', '#e2d58f', '#cfd3da'];
    for (let i = 0; i < 8; i++) {
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
    g.fillText('21:47', w / 2, 66);
    g.textAlign = 'left';
    g.fillStyle = 'rgba(255,255,255,0.14)';
    roundRect(g, 18, 104, w - 36, 60, 16);
    g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.3)';
    g.stroke();
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
uniform vec2 uCenter;    // центр капсулы
uniform vec2 uSize;      // ширина и высота капсулы
uniform float uPhrase;   // 0 — пауза, 1 — середина фразы
uniform float uSeed;     // замороженный момент
uniform float uTone;     // 0 — тёмный фон под плашкой, 1 — светлый
out vec4 outColor;

// Линза в паспортных числах лаборатории: h 13, A 41, frost 2.4, свет сверху справа.
const float BEVEL = 13.0;
const float AMP = 41.0;
const float FROST = 2.4;
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
float hash11(float x) { return fract(sin(x * 127.1 + 11.3) * 43758.5453); }
float noise1(float x) { float i = floor(x), f = fract(x); float u = f * f * (3.0 - 2.0 * f); return mix(hash11(i), hash11(i + 1.0), u); }
float hash21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1, 0)), u.x), mix(hash21(i + vec2(0, 1)), hash21(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p, int oct) {
  float s = 0.0, a = 0.5, n = 0.0;
  for (int i = 0; i < 5; i++) {
    if (i >= oct) break;
    s += a * vnoise(p); n += a;
    p = p * 2.03 + 17.1; a *= 0.5;
  }
  return s / n;
}
vec3 ramp3(vec3 a, vec3 b, vec3 c, float t) {
  t = clamp(t, 0.0, 1.0);
  return t < 0.5 ? mix(a, b, smoothstep(0.0, 1.0, t * 2.0)) : mix(b, c, smoothstep(0.0, 1.0, t * 2.0 - 1.0));
}

// Свет голоса: glow — каким он горит на тёмном, ink — каким читается на светлом,
// d — плотность 0..1, heat — насколько сердцевина уходит в белое (только на тёмном).
struct Light { vec3 glow; vec3 ink; float d; float heat; };
// Над тёмным свет складывается (screen) и светится. Над белым светить нечем:
// там он читается насыщенностью, поэтому ложится обычным наложением густого цвета.
// Поле цвета у варианта одно, и смешивается оно с фоном один раз — пересечения
// разных лент не перемножаются в грязь.
vec3 composite(vec3 col, Light L, float tone) {
  float d = clamp(L.d, 0.0, 1.0);
  vec3 e = mix(L.glow, vec3(1.0), clamp(L.heat, 0.0, 1.0)) * d;
  vec3 onDark = 1.0 - (1.0 - col) * (1.0 - e);
  vec3 onLight = mix(col, L.ink, d * 0.88);
  return mix(onDark, onLight, tone);
}
`;

  const GLASS = `
float shape(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
float shapeDist(vec2 p, out vec2 n) {
  const float e = 0.5;
  float f = shape(p);
  vec2 gr = vec2(shape(p + vec2(e, 0.0)) - shape(p - vec2(e, 0.0)), shape(p + vec2(0.0, e)) - shape(p - vec2(0.0, e))) / (2.0 * e);
  float gl = length(gr);
  n = gl > 1e-5 ? gr / gl : vec2(0.0, -1.0);
  return f / max(gl, 0.25);
}
vec2 shapeNormal(vec2 p) { vec2 n; shapeDist(p, n); return n; }

// Кромка поверх голоса: блик 1 px цвета контента, тёмная кромка iOS 27 и
// лепесток света Линзы со стороны источника.
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
  if (d0 > 90.0) { outColor = vec4(bg, 1.0); return; }
  vec2 n;
  float dist = shapeDist(p, n);
  float cover = clamp(0.5 - dist * uPx, 0.0, 1.0);
  float sd = shape(p - vec2(0.0, 8.0));
  float sh = 0.035 * exp(-max(sd, 0.0) / 30.0) * smoothstep(-30.0, 0.0, sd);
  vec3 under = bg * (1.0 - sh);
  if (cover <= 0.0) { outColor = vec4(under, 1.0); return; }

  float inside = max(-dist, 0.0);
  // Выборка у кромки идёт внутрь: A > h, кромка показывает перевёрнутый фон.
  float t = clamp(1.0 - inside / BEVEL, 0.0, 1.0);
  float disp = AMP * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  vec2 src = p - n * disp;
  vec3 col;
  if (inside < BEVEL + 1.0) {
    col.r = sceneBlur(p - n * disp * 1.035, FROST).r;
    col.g = sceneBlur(src, FROST).g;
    col.b = sceneBlur(p - n * disp * 0.965, FROST).b;
  } else {
    col = sceneBlur(src, FROST);
  }
  // Тон — светлая вуаль, как в приложении (GLASS_TONE в ui.lens_hud): на чёрном
  // +0.086, светлое почти не тронуто. Тон Apple col·1.015 + 0.086 делал светлые
  // окна под плашкой белым пятном.
  col = col * 0.914 + 0.086;
  float tone = uTone;
  // Свет голоса у кромки чуть ломается вместе со стеклом, но слабее фона: при
  // полном смещении кромка отражала капли и ленты «стеблями» до самого края.
  vec2 vp = mix(p, src, 0.3);
  col = voice(col, vp - uCenter, inside, tone);
  col = rim(col, p, n, inside);
  outColor = vec4(mix(under, col, cover), 1.0);
}
`;

  // ------------------------------------------------------------ варианты

  // Шёлк по мотивам LiveKit Aura: 32 нити — одна и та же линия, искажённая
  // синусами со своей фазой; вместе они вьются, как дым. Поле общее для всех
  // трёх способов показать его на прозрачном стекле: плотность нитей, оттенок
  // вдоль них (бирюза → фиолет) и «тело» дыма — широкая мягкая подложка.
  // Рисунок крупнее капсулы в SILK_ZOOM раз, а нити бесконечны: они уходят под
  // кромку, и у дыма нет своих концов и краёв — его обрезает только стекло.
  // На крупном рисунке завитков на длину стало мало, а нити сливались в одно
  // полотно: частота завитков выше, чем у эскиза (SILK_CURL 2.1 против 1.7), и
  // фазы нитей разведены шире (SILK_SPREAD) — в складках проступают волокна.
  const SILK = `
uniform float uFlow;    // накопленная фаза течения дыма: фраза её подгоняет
uniform float uLevel;   // слог — только яркость, форму он не трогает
const float SILK_ZOOM = 1.6;
const float SILK_CURL = 2.1;
const float SILK_SPREAD = 1.3;
const int SILK_STRANDS = 32;
struct Silk { float d; float t; float body; };
Silk silkField(vec2 q, float gain) {
  float ph = uPhrase;
  vec2 base = q / (uSize.y * 0.5 * SILK_ZOOM);
  // Нити держатся у оси: сердцевина яркая и плотная, по краям — волокна дыма.
  float amp = mix(0.07, 0.28, ph);
  float n = float(SILK_STRANDS);
  float acc = 0.0, accT = 0.0, wide = 0.0;
  for (int i = 0; i < SILK_STRANDS; i++) {
    float fi = float(i) / n;
    vec2 p = base;
    float fr = SILK_CURL, a = amp;
    for (int j = 0; j < 3; j++) {
      float fj = float(j);
      // Волны бегут вдоль капсулы (минус у фазы по x), а нити переплетаются: дым течёт.
      p += a * vec2(sin(p.y * fr * 1.3 + fi * 2.4 * SILK_SPREAD + uSeed + fj * 1.7 + uFlow * (0.6 + 0.5 * fj)),
                    sin(p.x * fr + fi * 3.1 * SILK_SPREAD + uSeed * 1.3 + fj * 2.3 - uFlow * (1.0 + 0.6 * fj)));
      fr *= 1.7; a *= 0.6;
    }
    float d = abs(p.y);
    // Волокно — плотная сердцевина в пару пикселей и слабый ореол вокруг. Оно
    // тонкое относительно рисунка: на крупном рисунке толстые волокна сливаются
    // в туман, а тонкие дают складки шёлка.
    float w = exp(-pow(d / 0.05, 1.4)) + 0.06 / (1.0 + d * d / 0.0156);
    acc += w;
    accT += w * fi;
    wide += 1.0 / (1.0 + d * d / 0.2);
  }
  Silk s;
  s.t = accT / max(acc, 1e-4);
  // Нити складываются, а не усредняются: где они сходятся, свет густеет. Яркость
  // отмерена на 24 нити: лишние нити дробят свет на волокна, а не густят его.
  float k = 24.0 / n;
  s.d = 1.0 - exp(-acc * k * 0.13 * gain * mix(0.5, 1.0, ph) * (0.88 + 0.24 * uLevel));
  s.body = (1.0 - exp(-wide * k * 0.05)) * mix(0.5, 1.0, ph);
  return s;
}
vec3 silkGlow(float t) { return mix(vec3(0.10, 0.84, 1.0), vec3(0.58, 0.42, 1.0), t); }
// Шёлк поверх стекла. На тёмном он светится (screen), сердцевина уходит в белое.
// На светлом светить нечем, и свет читается иначе: насыщенный цвет средней
// яркости, полупрозрачные волокна и ось, которая светлее стекла вокруг. Густой
// тёмный цвет делал из дыма мазок маркера, бледный — терялся на белом.
vec3 silkOver(vec3 col, Silk s, float tone, vec3 core) {
  float heat = smoothstep(0.7, 1.0, s.d) * 0.5;
  vec3 e = mix(silkGlow(s.t), vec3(1.0), heat) * s.d;
  vec3 onDark = 1.0 - (1.0 - col) * (1.0 - e);
  vec3 ink = mix(vec3(0.0, 0.58, 1.0), vec3(0.50, 0.30, 1.0), s.t);
  ink = mix(ink, core, smoothstep(0.84, 1.0, s.d) * 0.3);
  // Волокна на светлом полупрозрачны: сквозь дым читается фон, плотна только ось.
  vec3 onLight = mix(col, ink, pow(s.d, 1.6) * 0.7);
  return mix(onDark, onLight, tone);
}
`;

  // Капли: где стоят части в покое и посреди фразы (как на стоп-кадрах) и как
  // они дрейфуют, пока говоришь. Каждая — центр x, y и радиус, px макета.
  const DROP_REST = [[-16, 1, 8.5], [-3, 0, 9.0], [9, 0.5, 7.5], [16, 0, 5.0]];
  const DROP_SPLIT = [[-36, 2, 17.5], [6, -1.5, 12.5], [40, 3, 7.5], [61, -2, 3.8]];
  // Дрейф во время речи: фаза, частота (рад на единицу течения), размах по x и по y.
  // Размах по x небольшой: при большем части расходились в отдельные шарики без
  // перемычек, и жидкость переставала читаться.
  const DROP_WANDER = [[0.0, 0.9, 3.5, 2.0], [1.7, 1.3, 3, 1.6], [3.1, 1.1, 4.5, 2.4], [4.4, 1.6, 4, 2.0]];
  const mix = (a, b, t) => a + (b - a) * t;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));

  function dropsLayout(ph, flow) {
    return DROP_REST.map((r, i) => {
      const s = DROP_SPLIT[i];
      const [phase, freq, ax, ay] = DROP_WANDER[i];
      // Минус синуса фазы: при нулевом течении части стоят ровно как на стоп-кадре.
      const wx = Math.sin(flow * freq + phase) - Math.sin(phase);
      const wy = Math.sin(flow * freq * 1.3 + phase + 1.1) - Math.sin(phase + 1.1);
      return [mix(r[0], s[0], ph) + ph * ax * wx, mix(r[1], s[1], ph) + ph * ay * wy, mix(r[2], s[2], ph)];
    });
  }

  /** Пружина в терминах SwiftUI: response (с) и dampingFraction — как в лаборатории. */
  class Spring {
    constructor(value, response, damping) {
      this.value = this.target = value;
      this.velocity = 0;
      this.response = response;
      this.damping = damping;
    }
    set(target) { this.target = target; return this; }
    step(dt) {
      const omega = (2 * Math.PI) / this.response;
      const n = Math.max(1, Math.ceil(dt / (1 / 240)));
      const h = dt / n;
      for (let i = 0; i < n; i++) {
        const a = -omega * omega * (this.value - this.target) - 2 * this.damping * omega * this.velocity;
        this.velocity += a * h;
        this.value += this.velocity * h;
      }
      return this.value;
    }
  }

  const VARIANTS = [
    {
      id: 'drops',
      name: 'Капли',
      line: 'Жидкий свет: голос делит каплю и гонит её частями, в паузе она собирается в одну. Свечение Apple Intelligence и метаморфозы Ртути.',
      seed: 0.0,
      glsl: `
uniform vec4 uDrop[4];   // части капли: центр xy и радиус z, px макета
vec3 voice(vec3 col, vec2 q, float inside, float tone) {
  float ph = uPhrase;
  // Как жидкость: энергия голоса дробит каплю — большая тянет перемычку к средней,
  // малая отделилась, крошечная отрывается. В тишине поверхностное натяжение
  // собирает всё в одну спокойную каплю посередине. Где стоят части — считает JS.
  vec4 d = vec4(length(q - uDrop[0].xy) - uDrop[0].z, length(q - uDrop[1].xy) - uDrop[1].z,
                length(q - uDrop[2].xy) - uDrop[2].z, length(q - uDrop[3].xy) - uDrop[3].z);
  float k = mix(7.0, 8.5, ph);
  float F = smin(smin(smin(d.x, d.y, k), d.z, k), d.w, k * 0.6);
  // Ясная кромка, светлая сердцевина и свечение вокруг: жидкий свет, а не наклейка
  // и не размытое пятно. Перемычки видны, потому что кромка резкая.
  float body = smoothstep(0.9, -1.4, F);
  float depth = clamp(-F / 13.0, 0.0, 1.0);
  // Свечение заметно слабее тела у кромки — иначе кромка тонет и капля расплывается.
  float glow = exp(-max(F, 0.0) / 4.0) * 0.2;
  // Цвет каждой капли тянется к ней: в перемычках оттенки переливаются друг в друга.
  vec4 w = 1.0 / pow(max(d + 12.0, vec4(1.0)), vec4(2.5));
  vec3 C = (w.x * vec3(0.78, 0.36, 1.0) + w.y * vec3(0.30, 0.50, 1.0) + w.z * vec3(0.24, 0.76, 1.0) + w.w * vec3(0.30, 0.90, 1.0)) / (w.x + w.y + w.z + w.w);
  float D = clamp(max(body * (0.8 + 0.2 * depth), glow) * mix(0.65, 1.0, ph), 0.0, 1.0);
  // Светлый фон: насыщенный цвет поверх — так, как понравилось на стоп-кадрах.
  vec3 onLight = mix(col, C * 0.9, D * 0.88);
  // Тёмный фон: тело капли закрывает фон её же глубоким цветом, и уже поверх
  // светит сама капля. Одно сложение света делало каплю прозрачной (сквозь неё
  // читался код), а полная сила света пересвечивала крупную каплю в белое пятно.
  vec3 base = mix(col, C * 0.3, body * 0.75);
  float heat = body * pow(depth, 2.5) * 0.28 * ph;
  vec3 e = mix(C * 0.78, vec3(1.0), heat) * D;
  vec3 onDark = 1.0 - (1.0 - base) * (1.0 - e);
  return mix(onDark, onLight, tone);
}`,
      statics: (ph) => ({ phrase: ph, drops: dropsLayout(ph, 0) }),
      // Части идут к своим местам на пружинах с лёгким перелётом: разделение и
      // слияние — с инерцией жидкости, а не по рельсам.
      makeLive() {
        let flow = 0;
        const springs = dropsLayout(0, 0).map((xyr) => xyr.map((x, j) => (j < 2 ? new Spring(x, 0.6, 0.62) : new Spring(x, 0.5, 0.72))));
        return {
          step(dt, voice) {
            const ph = voice.ph;
            // Течение подгоняет фраза: в паузе части стоят, в речи — плывут.
            flow += dt * (0.1 + 0.9 * ph);
            const drops = dropsLayout(ph, flow).map((xyr, i) => xyr.map((x, j) => springs[i][j].set(x).step(dt)));
            return { phrase: ph, drops };
          },
        };
      },
    },
    {
      id: 'silk',
      name: 'Шёлк',
      line: 'Светящийся дым, свитый в волну, по мотивам LiveKit Aura. Рисунок крупнее капсулы: нити уходят под кромку. Стекло прозрачное: на белом шёлк держится насыщенным цветом и светлой осью.',
      seed: 0.6,
      glsl: SILK + `
vec3 voice(vec3 col, vec2 q, float inside, float tone) {
  Silk s = silkField(q, 2.1);
  vec3 glass = col;
  // Под нитями — собственное тело дыма: полупрозрачная сине-фиолетовая подложка,
  // а не серая тень и не притемнённое стекло (оно серило всю пилюлю на белом).
  // На ней светлая ось читается как свет, а стекло вокруг остаётся чистым.
  vec3 bodyInk = mix(vec3(0.16, 0.38, 0.92), vec3(0.42, 0.28, 0.90), s.t);
  col = mix(col, bodyInk, s.body * mix(0.12, 0.08, tone));
  // У самой кромки дым гаснет, как в приложении: блик и тёмная кромка — поверх.
  return mix(glass, silkOver(col, s, tone, vec3(0.74, 0.95, 1.0)), smoothstep(0.6, 2.2, inside));
}`,
      statics: (ph) => ({ phrase: ph, flow: 0, level: 0.5 }),
      makeLive() {
        let flow = 0;
        return {
          step(dt, voice) {
            const ph = voice.ph;
            // Дым течёт всегда, фраза его подгоняет: в паузе он почти стоит.
            flow += dt * (0.3 + 1.8 * ph);
            return { phrase: ph, flow, level: voice.syllable };
          },
        };
      },
    },
  ];

  // ------------------------------------------------------------ голос

  // Те же огибающие, что в приложении (ui.lens_hud, _Motion.voice): громкость в
  // окне дБ с гаммой 0.7; «слог» — атака 70 мс, спад 280 мс; «фраза» поверх
  // слога — 180 мс и 0.75 с. Форму ведёт фраза, слог трогает только яркость.
  // Окно следит за голосом (автоусиление): опора — средний уровень звучащих
  // блоков за последние секунды, окно от опоры −30 до опоры +10 дБ, низ — над
  // шумом пауз. Обычная речь в журнале — около −31 дБ: в постоянном окне −56…−6
  // шёлк раскрывался целиком только на крике.
  const VOICE_AGC = {
    ref0: -33, tau: 2.5, refRange: [-46, -14], span: [30, 10],
    gate: 15, room: 6, floor0: -60, floorRise: 1,
  };

  // Детерминированная речь, как в лаборатории (harness.js → stepVoice): фразы из
  // слогов 4–6 Гц, ударный слог громче. Паузы между фразами то короткие, как
  // вдох, то настоящие, на пару секунд: иначе «молчу» почти не видно.
  class Voice {
    constructor(seed = 20261006) { this.reset(seed); }
    reset(seed = 20261006) {
      this.seed = seed;
      this.t = 0;
      this.gap = 0.6;
      this.left = 2.2;
      this.amp = 0.85;
      this.rate = 5;
      this.syll = 0;
      this.stress = 1;
      this.talking = false;
      this.syllable = 0;
      this.phrase = 0;
      this.ref = VOICE_AGC.ref0;
      this.floor = VOICE_AGC.floor0;
    }
    rand() {
      this.seed = (this.seed * 16807) % 2147483647;
      return (this.seed - 1) / 2147483646;
    }
    simulatedRms(dt) {
      this.talking = false;
      if (this.gap > 0) { this.gap -= dt; return 0.0015; }
      this.talking = true;
      this.left -= dt;
      const before = Math.floor(this.syll);
      this.syll += dt * this.rate;
      if (Math.floor(this.syll) !== before) this.stress = this.rand() < 0.28 ? 1.3 : 1;
      const env = Math.pow(Math.sin(Math.PI * (this.syll % 1)), 1.6);
      const target = this.amp * this.stress * (0.35 + 0.65 * env) * (0.8 + 0.2 * Math.sin(this.t * 1.7));
      if (this.left <= 0) {
        this.gap = this.rand() < 0.4 ? 1.4 + this.rand() * 1.6 : 0.25 + this.rand() * 0.55;
        this.left = 1.2 + this.rand() * 2.4;
        this.amp = 0.35 + this.rand() * 0.65;
        this.rate = 4 + this.rand() * 2.2;
      }
      // Речь около −31 дБ по звучащим блокам — как обычная речь в журнале диктовок.
      return 0.0015 + 0.059 * target;
    }
    /** Громкость блока 0…1 в окне, которое подстраивается под голос и шум. */
    loudness(db, dt) {
      const A = VOICE_AGC;
      this.floor = Math.min(db, this.floor + A.floorRise * dt);
      if (db > this.floor + A.gate) {
        this.ref += (db - this.ref) * (1 - Math.exp(-dt / A.tau));
        this.ref = Math.min(Math.max(this.ref, A.refRange[0]), A.refRange[1]);
      }
      const lo = Math.max(this.ref - A.span[0], this.floor + A.room);
      const hi = this.ref + A.span[1];
      return Math.pow(clamp01((db - lo) / Math.max(hi - lo, 6)), 0.7);
    }
    step(dt, micRms = null) {
      this.t += dt;
      const rms = micRms == null ? this.simulatedRms(dt) : micRms;
      const x = rms > 1e-6 ? this.loudness(20 * Math.log10(rms), dt) : 0;
      let a = 1 - Math.exp(-dt / (x > this.syllable ? 0.07 : 0.28));
      this.syllable += (x - this.syllable) * a;
      a = 1 - Math.exp(-dt / (this.syllable > this.phrase ? 0.18 : 0.75));
      this.phrase += (this.syllable - this.phrase) * a;
    }
    /** Фраза в шкале стоп-кадров: середина фразы ≈ 1, тишина — 0. */
    get ph() { return clamp01((this.phrase - 0.05) / 0.75); }
  }

  // Живой микрофон: RMS блока, как считает приложение (core/audio.py). Обработку
  // браузера выключаем — у приложения её нет, иначе шкала поплывёт.
  async function openMic() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    return {
      rms() {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        return Math.sqrt(sum / buf.length);
      },
      close() { stream.getTracks().forEach((t) => t.stop()); ctx.close(); },
    };
  }

  // ------------------------------------------------------------ WebGL

  // У каждой плитки свой контекст WebGL: кадр рисуется прямо в её холст. Через
  // общий холст с копированием в 2D каждый кадр ждал видеокарту, и живой показ
  // на шести плитках шёл рывками (~20 к/с).
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

  function makeRenderer(canvas, keep = false) {
    const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, premultipliedAlpha: false, preserveDrawingBuffer: keep });
    if (!gl) return null;
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    return { gl, canvas, programs: {}, textures: {}, drop: new Float32Array(16) };
  }

  function program(r, v) {
    if (r.programs[v.id]) return r.programs[v.id];
    const gl = r.gl;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, HEAD + v.glsl + GLASS));
    gl.bindAttribLocation(prog, 0, 'aPos');
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    const uniforms = {};
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(prog, i);
      // Массив юниформ приходит как «uDrop[0]»: храним по имени без индекса.
      uniforms[info.name.replace(/\[0\]$/, '')] = gl.getUniformLocation(prog, info.name);
    }
    r.programs[v.id] = { prog, uniforms };
    return r.programs[v.id];
  }

  // Фон плитки рисуется один раз на масштаб и идёт во все плитки; текстура из
  // него — своя у каждого контекста.
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
    sc.draw(g, TILE_W, TILE_H);
    // Тон под плашкой — как в приложении: по средней светлоте фона под капсулой.
    const x0 = Math.round((TILE_W - PILL_W) / 2 * px), y0 = Math.round((TILE_H - PILL_H) / 2 * px);
    const data = g.getImageData(x0, y0, Math.round(PILL_W * px), Math.round(PILL_H * px)).data;
    let sum = 0, n = 0;
    for (let i = 0; i < data.length; i += 4 * 5) {
      sum += (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
      n++;
    }
    const tone = Math.min(1, Math.max(0, (sum / n - 0.38) / 0.2));
    backdrops[key] = { canvas: c, tone };
    return backdrops[key];
  }

  function texture(r, sc, px) {
    const key = sc.id + '@' + px;
    if (r.textures[key]) return r.textures[key];
    const gl = r.gl;
    const bd = backdrop(sc, px);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bd.canvas);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    r.textures[key] = { tex, tone: bd.tone };
    return r.textures[key];
  }

  // uni — что меняется от кадра к кадру: фраза, течение, слог, части капли.
  function render(r, v, sc, zoom, uni) {
    const gl = r.gl;
    const px = zoom * Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(TILE_W * px), h = Math.round(TILE_H * px);
    if (r.canvas.width !== w || r.canvas.height !== h) {
      r.canvas.width = w;
      r.canvas.height = h;
    }
    r.canvas.style.width = TILE_W * zoom + 'px';
    r.canvas.style.height = TILE_H * zoom + 'px';
    const { prog, uniforms: u } = program(r, v);
    const bg = texture(r, sc, px);
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
    set2('uCenter', TILE_W / 2, TILE_H / 2);
    set2('uSize', PILL_W, PILL_H);
    set1('uPhrase', uni.phrase);
    set1('uFlow', uni.flow || 0);
    set1('uLevel', uni.level == null ? 0.5 : uni.level);
    if (uni.drops && u.uDrop) {
      uni.drops.forEach((d, i) => { r.drop[i * 4] = d[0]; r.drop[i * 4 + 1] = d[1]; r.drop[i * 4 + 2] = d[2]; });
      gl.uniform4fv(u.uDrop, r.drop);
    }
    set1('uSeed', v.seed);
    set1('uTone', bg.tone);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  // Для листов и плёнки: отдельный холст, кадр из которого копируется в лист.
  let offscreen = null;
  function offRenderer() {
    if (!offscreen) offscreen = makeRenderer(document.createElement('canvas'), true);
    return offscreen;
  }

  // ------------------------------------------------------------ страница

  // Ключ новый: после оживления по умолчанию — «Живьём», старый выбор не мешает.
  const STORE = 'voice-sketches-live';
  const state = { moment: 'live', zoom: 1, source: 'sim' };
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
    if (saved.moment) state.moment = saved.moment;
    if (saved.zoom) state.zoom = saved.zoom;
  } catch (e) { /* без сохранения — с умолчаний */ }
  // Адрес вида #moment=pause&zoom=2&only=silk — для снимков и разглядывания.
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('moment')) state.moment = hash.get('moment');
  if (hash.has('zoom')) state.zoom = Number(hash.get('zoom'));
  const only = hash.has('only') ? hash.get('only').split(',') : null;
  if (hash.has('bare')) document.body.classList.add('bare');

  const rows = document.getElementById('rows');
  const tiles = [];
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
      const r = makeRenderer(canvas);
      if (!r) fig.innerHTML = '<pre class="error">Нет контекста WebGL2 для плитки.</pre>';
      tiles.push({ v, sc, r, fig, broken: !r });
    }
    rows.appendChild(row);
  });

  function paint(unis) {
    for (const t of tiles) {
      if (t.broken) continue;
      try {
        render(t.r, t.v, t.sc, state.zoom, unis[t.v.id]);
      } catch (err) {
        t.broken = true;
        t.fig.innerHTML = `<pre class="error">${String(err.message || err).slice(0, 1600)}</pre>`;
        console.error(t.v.id, err);
      }
    }
  }

  function heads() {
    document.getElementById('heads').innerHTML = SCENES.map((sc) => `<span style="width:${TILE_W * state.zoom}px">${sc.name}</span>`).join('');
  }

  function drawStatic() {
    const ph = state.moment === 'phrase' ? 1 : 0.06;
    paint(Object.fromEntries(VARIANTS.map((v) => [v.id, v.statics(ph)])));
  }

  // Живой показ: один голос на все плитки — у одного варианта на трёх фонах
  // движение общее, сравнивать фоны можно кадр в кадр.
  const live = { raf: 0, last: 0, voice: new Voice(), states: null, mic: null };
  function liveFrame(now) {
    const dt = live.last ? Math.min(0.05, (now - live.last) / 1000) : 1 / 60;
    live.last = now;
    live.voice.step(dt, live.mic ? live.mic.rms() : null);
    paint(Object.fromEntries(VARIANTS.map((v) => [v.id, live.states[v.id].step(dt, live.voice)])));
    live.raf = requestAnimationFrame(liveFrame);
  }
  function startLive() {
    stopLive();
    live.voice.reset();
    live.states = Object.fromEntries(VARIANTS.map((v) => [v.id, v.makeLive()]));
    live.last = 0;
    live.raf = requestAnimationFrame(liveFrame);
  }
  function stopLive() {
    if (live.raf) cancelAnimationFrame(live.raf);
    live.raf = 0;
  }

  const note = document.getElementById('mic-note');
  async function setSource(source) {
    if (live.mic) { live.mic.close(); live.mic = null; }
    note.textContent = '';
    if (source === 'mic') {
      try {
        live.mic = await openMic();
      } catch (err) {
        note.textContent = 'Микрофон недоступен: ' + (err.message || err.name || err);
        state.source = 'sim';
      }
    } else {
      state.source = 'sim';
    }
    syncButtons();
  }

  function update() {
    heads();
    document.querySelector('[data-key="source"]').hidden = state.moment !== 'live';
    if (state.moment === 'live') {
      if (!live.raf) startLive();
    } else {
      stopLive();
      if (live.mic) setSource('sim');
      drawStatic();
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
      const value = key === 'zoom' ? Number(b.dataset.value) : b.dataset.value;
      if (state[key] === value) return;
      state[key] = value;
      try { localStorage.setItem(STORE, JSON.stringify({ moment: state.moment, zoom: state.zoom })); } catch (err) { /* не критично */ }
      syncButtons();
      if (key === 'source') setSource(value);
      else update();
    });
  }

  if (!tiles.length || tiles.every((t) => !t.r)) {
    rows.innerHTML = '<p class="error">WebGL2 недоступен в этом браузере.</p>';
  } else {
    syncButtons();
    // Шрифты Segoe на фонах: ждём их, иначе первый кадр уйдёт с запасным шрифтом.
    (document.fonts ? document.fonts.ready : Promise.resolve()).then(update);
  }

  // ------------------------------------------------------------ для разглядывания

  function crop(src, px, cw, ch, g, dx, dy) {
    const sx = Math.round((TILE_W - cw) / 2 * px), sy = Math.round((TILE_H - ch) / 2 * px);
    const w = Math.round(cw * px), h = Math.round(ch * px);
    g.drawImage(src, sx, sy, w, h, dx, dy, w, h);
  }

  // Лист стоп-кадров: варианты строками, фоны столбцами, вырез вокруг капсулы.
  function sheet({ ids = VARIANTS.map((v) => v.id), moment = 'phrase', zoom = 3, cw = 236, ch = 76 } = {}) {
    const px = zoom * Math.min(window.devicePixelRatio || 1, 2);
    const list = VARIANTS.filter((v) => ids.includes(v.id));
    const w = Math.round(cw * px), h = Math.round(ch * px);
    const out = document.createElement('canvas');
    out.width = w * SCENES.length + 4 * (SCENES.length - 1);
    out.height = h * list.length + 4 * (list.length - 1);
    const g = out.getContext('2d');
    g.fillStyle = '#000';
    g.fillRect(0, 0, out.width, out.height);
    const off = offRenderer();
    const ph = moment === 'phrase' ? 1 : 0.06;
    list.forEach((v, r) => SCENES.forEach((sc, c) => {
      render(off, v, sc, zoom, v.statics(ph));
      crop(off.canvas, px, cw, ch, g, c * (w + 4), r * (h + 4));
    }));
    return out;
  }

  // Плёнка: кадры живого показа в замороженном времени (шаг 1/60 с от начала),
  // варианты строками, моменты столбцами. Голос и пружины — свои, показ не трогают.
  function film({ ids = VARIANTS.map((v) => v.id), scene: sceneId = 'doc', times = [1, 2, 3, 4, 5, 6], zoom = 1.6, cw = 236, ch = 76 } = {}) {
    const px = zoom * Math.min(window.devicePixelRatio || 1, 2);
    const list = VARIANTS.filter((v) => ids.includes(v.id));
    const sc = SCENES.find((s) => s.id === sceneId);
    const w = Math.round(cw * px), h = Math.round(ch * px);
    const out = document.createElement('canvas');
    out.width = w * times.length + 4 * (times.length - 1);
    out.height = h * list.length + 4 * (list.length - 1);
    const g = out.getContext('2d');
    g.fillStyle = '#000';
    g.fillRect(0, 0, out.width, out.height);
    const off = offRenderer();
    const voice = new Voice();
    const states = Object.fromEntries(VARIANTS.map((v) => [v.id, v.makeLive()]));
    const marks = [];
    const dt = 1 / 60;
    let t = 0;
    let unis = null;
    times.forEach((at, col) => {
      while (t < at - 1e-9) {
        voice.step(dt);
        unis = Object.fromEntries(VARIANTS.map((v) => [v.id, states[v.id].step(dt, voice)]));
        t += dt;
      }
      marks.push({ t: Math.round(t * 100) / 100, ph: Math.round(voice.ph * 100) / 100, talking: voice.talking });
      list.forEach((v, r) => {
        render(off, v, sc, zoom, unis[v.id]);
        crop(off.canvas, px, cw, ch, g, col * (w + 4), r * (h + 4));
      });
    });
    return { canvas: out, marks };
  }

  // Трасса для замера дрожи: ряд значений по кадрам 60 Гц. Дрожь — доля спектра
  // на частотах слогов 3–8 Гц (как trace.py лаборатории): выше ~0.25 — форма
  // дёргается на каждом слоге.
  function trace({ seconds = 30 } = {}) {
    const voice = new Voice();
    const states = Object.fromEntries(VARIANTS.map((v) => [v.id, v.makeLive()]));
    const dt = 1 / 60;
    const series = { ph: [], dropR: [], dropX: [], tinyX: [], silkAmp: [], silkGlow: [] };
    for (let i = 0; i < seconds * 60; i++) {
      voice.step(dt);
      const d = states.drops.step(dt, voice);
      const s = states.silk.step(dt, voice);
      series.ph.push(voice.ph);
      series.dropR.push(d.drops[0][2]);
      series.dropX.push(d.drops[0][0]);
      series.tinyX.push(d.drops[3][0]);
      series.silkAmp.push(mix(0.07, 0.28, s.phrase));
      series.silkGlow.push(0.88 + 0.24 * s.level);
    }
    const jitter = (xs) => {
      const n = xs.length;
      const mean = xs.reduce((a, b) => a + b, 0) / n;
      let lo = 0, hi = 0;
      for (let f = 0.1; f <= 8.0001; f += 0.1) {
        let re = 0, im = 0;
        for (let k = 0; k < n; k++) {
          const a = 2 * Math.PI * f * k / 60;
          re += (xs[k] - mean) * Math.cos(a);
          im += (xs[k] - mean) * Math.sin(a);
        }
        const m = Math.hypot(re, im);
        if (f >= 3) hi += m; else lo += m;
      }
      return Math.round(hi / (lo + hi) * 1000) / 1000;
    };
    return Object.fromEntries(Object.entries(series).map(([k, xs]) => [k, jitter(xs)]));
  }

  // Стоимость кадра живого показа: шаг голоса и все плитки, с ожиданием видеокарты
  // (gl.finish) — чтобы мерить, а не гадать. Работает и в скрытой вкладке.
  // ids — только эти варианты; sync — ждать видеокарту после каждого кадра
  // (иначе кадры идут конвейером, и в конце ждём всё разом).
  function bench({ frames = 60, ids = null, sync = true } = {}) {
    const voice = new Voice();
    const states = Object.fromEntries(VARIANTS.map((v) => [v.id, v.makeLive()]));
    const dt = 1 / 60;
    const live = tiles.filter((t) => !t.broken && (!ids || ids.includes(t.v.id)));
    const t0 = performance.now();
    for (let i = 0; i < frames; i++) {
      voice.step(dt);
      const unis = Object.fromEntries(VARIANTS.map((v) => [v.id, states[v.id].step(dt, voice)]));
      for (const t of live) render(t.r, t.v, t.sc, state.zoom, unis[t.v.id]);
      if (sync) for (const t of live) t.r.gl.finish();
    }
    if (!sync) for (const t of live) t.r.gl.finish();
    return Math.round((performance.now() - t0) / frames * 100) / 100;
  }

  window.VoiceSketches = { state, VARIANTS, sheet, film, trace, bench, Voice };
})();
