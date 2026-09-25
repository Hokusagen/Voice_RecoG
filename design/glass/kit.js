/* Общие куски второго круга поверх основы (harness.js).
 *
 * Три варианта второго круга берут отсюда одно и то же, чтобы не разойтись:
 * цвет итогов из «Сияния» (полоса в кромке стягивается в зелёный или
 * красный), морф форм Material 3 из «Острова» и свечение «из-под пальца».
 * Подключается после harness.js; первый круг его не использует.
 */
(function () {
  'use strict';

  const LG = window.LG;
  const Spring = LG.Spring;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));

  // ---------------------------------------------------------------- цвет итогов

  // Полоса света внутри кромки — только в «Готово» и «Ошибке». Вспыхивает
  // нейтральным светом стекла и за ~150 мс стягивается пятнами по шуму в
  // зелёный #4FDCA6 или красный #FF6B74, затем гаснет до чистого стекла.
  // Кривая вспышки и смешение с фоном — как в «Сиянии», которое заказчик одобрил.
  LG.glsl.status = `
uniform vec4 uStatus;   // x — сила вспышки, y — доля зелёного, z — доля красного, w — ширина полосы, px
const vec3 LG_GREEN = vec3(0.310, 0.863, 0.651);
const vec3 LG_RED = vec3(1.000, 0.420, 0.455);
// col — цвет после liquidGlass, inside — глубина от кромки внутрь (px, >= 0),
// cover — покрытие стеклом (liquidGlass(...).a).
vec3 statusRim(vec3 col, vec2 p, float inside, float cover) {
  if (uStatus.x < 0.003 || cover <= 0.0 || inside > uStatus.w * 1.7 + 6.0) return col;
  vec2 np = p / 30.0;
  // Ширину ведёт шум пониже частотой: край дышит длинными волнами, а не рвётся комками.
  float n1 = fbm(np / 1.6 + vec2(uTime * 0.07, -uTime * 0.05));
  float n2 = fbm(np * 1.8 + vec2(-uTime * 0.14, uTime * 0.11) + 7.3);
  float width = uStatus.w * (0.8 + 0.4 * n1);
  float prof = pow(1.0 - smoothstep(0.0, width, inside), 1.7);
  float line = 1.0 - smoothstep(0.0, 2.0, inside);
  float I = 0.74 * prof + 0.26 * line;
  float bright = uStatus.x * (0.68 + 0.64 * n2);
  vec3 lc = vec3(1.0);
  lc = mix(lc, LG_GREEN, smoothstep(0.0, 1.0, clamp(uStatus.y * 1.5 - 0.5 * n2, 0.0, 1.0)));
  lc = mix(lc, LG_RED, smoothstep(0.0, 1.0, clamp(uStatus.z * 1.5 - 0.5 * n2, 0.0, 1.0)));
  // На светлом фоне сложение только белит — там работает подмес цвета, на тёмном —
  // свечение. Потолок 0.9: фон всегда проглядывает.
  float lum = luma(col);
  float dark = 1.0 - smoothstep(0.35, 0.9, lum);
  float light = smoothstep(0.6, 0.8, lum);
  float a = min(0.9, 0.9 * (1.0 - exp(-1.5 * I * bright)) * (1.0 + 0.3 * light)) * cover;
  return mix(col, lc, a * mix(mix(0.72, 0.9, light), 0.58, dark)) + lc * a * 0.34 * dark;
}
`;

  /** Состояние перехода в итог: step(s) раз в кадр, uniform — в uStatus. */
  class StatusFlash {
    constructor() {
      this.stage = 'hidden';
      this.kind = null;
      this.t = -1;
      // Перекраска быстрая: полоса успевает сменить цвет, пока ещё горит.
      this.green = new Spring(0, 0.12, 1.0);
      this.red = new Spring(0, 0.12, 1.0);
      this.flash = 0;
    }
    step(s) {
      if (s.stage !== this.stage) {
        this.stage = s.stage;
        if (s.stage === 'done' || s.stage === 'error') {
          this.kind = s.stage;
          this.t = 0;
        } else if (s.stage === 'listening') {
          this.kind = null;
          this.t = -1;
          this.green.snap(0);
          this.red.snap(0);
        }
      }
      this.flash = 0;
      if (this.t >= 0) {
        this.t += s.dt;
        // Рост с 100 мс, пик ~1 на 200 мс, угасание 360 мс: к секунде полосы нет.
        const fz = Math.max(0, this.t - 0.1);
        this.flash = (1 - Math.exp(-fz / 0.05)) * Math.exp(-fz / 0.36) * 1.5;
        if (this.t > 2.5) this.t = -1;
      }
      this.green.set(this.kind === 'done' ? 1 : 0).step(s.dt);
      this.red.set(this.kind === 'error' ? 1 : 0).step(s.dt);
      return this;
    }
    get uniform() {
      return [this.flash, clamp01(this.green.value), clamp01(this.red.value), 6 + 5 * Math.min(1, this.flash)];
    }
  }
  LG.StatusFlash = StatusFlash;

  // ---------------------------------------------------------------- морф Material 3

  // Формы M3 в полярной записи: r(θ) = овал(θ) · (1 − (1 − inner) · f(θ)),
  // f = ((1 − cos nθ) / 2)^gamma. gamma > 1 — широкие лепестки и узкие впадины
  // (печенье, клевер), < 1 — острые вершины (солнце, взрыв). Это «стеклянные»
  // версии каталога androidx MaterialShapes: впадины мельче, скругления мягче,
  // иначе бортик линзы складывается на острых вершинах (RESEARCH.md → «Морф»).
  // Все формы нормированы на средний квадрат радиуса 1: морф не пульсирует размером.
  const SHAPES = {
    Circle: { n: 0, inner: 1, gamma: 1 },
    Oval: { n: 0, inner: 1, gamma: 1, oval: [0.64, -Math.PI / 4] },
    Pill: { n: 0, inner: 1, gamma: 1, oval: [0.56, 0] },
    Cookie4: { n: 4, inner: 0.84, gamma: 1.5 },
    Cookie6: { n: 6, inner: 0.86, gamma: 1.3 },
    Cookie9: { n: 9, inner: 0.9, gamma: 1.1 },
    Clover4Leaf: { n: 4, inner: 0.62, gamma: 2.4 },
    Pentagon: { n: 5, inner: 0.87, gamma: 0.7 },
    Sunny: { n: 8, inner: 0.86, gamma: 0.8 },
    SoftBurst: { n: 10, inner: 0.84, gamma: 0.9 },
    Puffy: { n: 6, inner: 0.9, gamma: 3.0 },
  };
  function radius(sh, th) {
    let r = 1;
    if (sh.oval) {
      const a = th - sh.oval[1];
      const b = sh.oval[0];
      r = b / Math.sqrt(b * b * Math.cos(a) ** 2 + Math.sin(a) ** 2);
    }
    if (sh.n > 0) r *= 1 - (1 - sh.inner) * Math.pow(0.5 - 0.5 * Math.cos(sh.n * th), sh.gamma);
    return r;
  }
  for (const sh of Object.values(SHAPES)) {
    let sum = 0;
    let max = 0;
    for (let i = 0; i < 720; i++) {
      const r = radius(sh, (i / 720) * 2 * Math.PI);
      sum += r * r;
      max = Math.max(max, r);
    }
    sh.norm = 1 / Math.sqrt(sum / 720);
    sh.max = max * sh.norm;   // внешний радиус в долях R: для линзы от описанного круга
  }
  LG.shapes = SHAPES;
  /** Юниформы формы: [n, inner, gamma, norm] и [овал: отношение осей, угол]. */
  LG.shapeVec = (name) => {
    const sh = SHAPES[name];
    if (!sh) throw new Error('Нет формы M3: ' + name);
    return [[sh.n, sh.inner, sh.gamma, sh.norm], sh.oval ? [sh.oval[0], sh.oval[1]] : [1, 0]];
  };

  LG.glsl.morph = `
// r(θ)/R формы M3: S = (n, inner, gamma, norm), E = (отношение осей овала, его угол).
float m3r(float th, vec4 S, vec2 E) {
  float r = 1.0;
  if (E.x < 0.999) {
    float a = th - E.y;
    float c = cos(a), s = sin(a);
    r = E.x / sqrt(E.x * E.x * c * c + s * s);
  }
  if (S.x > 0.5) r *= 1.0 - (1.0 - S.y) * pow(max(0.5 - 0.5 * cos(S.x * th), 1e-6), S.z);
  return r * S.w;
}
// SDF морфа: смесь форм A→B по t, поворот rot, средний радиус R (px), центр c.
// Лепестки гаснут к центру как (ρ/R)²: иначе угловая производная ~1/ρ даёт
// «спицы» ложной кромки из центра (урок «Острова»). Оценка расстояния делится на
// |∇f| = √(1 + (r'/ρ)²), поэтому бортик и блик одной ширины на лепестке и во впадине.
float sdMorph(vec2 p, vec2 c, float R, vec4 A, vec2 Ae, vec4 B, vec2 Be, float t, float rot) {
  vec2 q = p - c;
  float rho = length(q);
  float th = atan(q.y, q.x) - rot;
  const float e = 0.01;
  float ra = mix(m3r(th, A, Ae), m3r(th, B, Be), t);
  float rb = mix(m3r(th + e, A, Ae), m3r(th + e, B, Be), t);
  float fade = min(rho / R, 1.0);
  fade *= fade;
  float r = R * (1.0 + (ra - 1.0) * fade);
  float dr = R * (rb - ra) / e * fade;
  return (rho - r) / sqrt(1.0 + dr * dr / max(rho * rho, 1.0));
}
`;

  /**
   * Цикл форм, как у индикатора загрузки M3 (LoadingIndicator.kt): прогресс 0→1
   * пружиной, слот не короче 650 мс, затем следующая форма, и с каждым шагом
   * поворот на четверть оборота, привязанный к прогрессу. Глобального вращения нет.
   */
  class Morph {
    constructor(seq = ['Cookie4', 'Cookie9', 'Clover4Leaf', 'Oval', 'Circle'], opts = {}) {
      this.seq = seq;
      this.slot = opts.slot == null ? 0.65 : opts.slot;
      this.turn = opts.turn == null ? Math.PI / 2 : opts.turn;
      // M3: dampingRatio 0.7, stiffness 200 → response 2π/√200 ≈ 0.444 с.
      this.p = new Spring(0, opts.response || 0.444, opts.damping || 0.7);
      this.reset();
    }
    reset() {
      this.idx = 0;
      this.p.snap(0);
      this.hold = 0;
      this.base = 0;
      return this;
    }
    /** rate > 1 — работа тяжелее, темп плотнее (DARVI.md). */
    step(dt, rate = 1) {
      this.p.set(1).step(dt);
      this.hold += dt * rate;
      if (this.hold >= this.slot && Math.abs(this.p.value - 1) < 0.02 && Math.abs(this.p.velocity) < 0.3) {
        this.idx = (this.idx + 1) % this.seq.length;
        this.p.snap(0);
        this.hold = 0;
        this.base += this.turn;
      }
      return this;
    }
    get from() { return this.seq[this.idx]; }
    get to() { return this.seq[(this.idx + 1) % this.seq.length]; }
    /** {A, Ae, B, Be, t, rot} — прямо в sdMorph. */
    get uniforms() {
      const [A, Ae] = LG.shapeVec(this.from);
      const [B, Be] = LG.shapeVec(this.to);
      return { A, Ae, B, Be, t: this.p.value, rot: this.base + this.turn * this.p.value };
    }
  }
  LG.Morph = Morph;

  // ---------------------------------------------------------------- свечение из-под пальца

  // У Apple стекло при касании светится изнутри мягким белым пятном вокруг пальца
  // (WWDC25/219). Здесь «палец» — источник голоса, значок микрофона. На белом фоне
  // белый свет не виден: там пятно поднимает яркость контента совсем чуть-чуть,
  // и голос над документом нужно дополнительно показывать формой или кромкой.
  LG.glsl.touch = `
// amount 0..1, radius — радиус пятна, px; cover — покрытие стеклом.
vec3 touchGlow(vec3 col, vec2 p, vec2 c, float radius, float amount, float cover) {
  if (amount < 0.002 || cover <= 0.0) return col;
  vec2 d = (p - c) / max(radius, 1.0);
  float k = exp(-dot(d, d) * 1.6) * clamp(amount, 0.0, 1.0) * cover;
  return col + (1.0 - col) * 0.6 * k;
}
`;

  // ---------------------------------------------------------------- темперамент

  /** Значение по темпераменту: s.temper 0 — кот (спокойный), 1 — живее. */
  LG.temper = (s, cat, lively) => cat + (lively - cat) * (s.temper || 0);
})();
