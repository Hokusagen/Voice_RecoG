/* «Ртуть», второй круг: тело Дарви — капля жидкого стекла.
 *
 * Вся жизнь — в топологии, материал — стекло Линзы без изменений: defaultGlass(),
 * толщина по размеру, как у Линзы, её лепесток света и материализация. Форма —
 * цепочка smin в фиксированном порядке: тело, потом до шести капель. И тело, и
 * капли — неравные капсулы (голова и хвост): одной фигурой пишутся капсула плашки,
 * круглая капля, капля с хвостом по скорости и тяжёлая капля грусти.
 *
 * Слушаю — бусина у значка микрофона набухает фразами в круглую голову выше и
 * длиннее капсулы (разница «говорю / молчу» видна силуэтом даже на белом), светится
 * изнутри, в речи медленно дышит, на вдохе между фразами выдыхает, и на ударных
 * местах отпускает микрокаплю: та скатывается по верхней кромке снаружи и
 * вливается обратно, текст не пересекает. Распознаю — деление клетки. Причёсываю —
 * бусы по очереди перетекают справа налево. Готово — одна круглая капля с
 * галочкой и затухающими модами Рэлея. Ошибка — капля выстреливает из торца и
 * лопается на ходу.
 */
(function () {
  'use strict';

  const H0 = 56;
  const R0 = 28;
  const K_REST = 5.25;    // вздутие smin в покое (RESEARCH.md → «Слияние капель»)
  const K_MAX = 10;       // выше — «вата»: перемычка шире капсулы
  const W_C = 64;         // компактная капсула «Распознаю»: короче не делится — нечего тянуть
  const BASE_W = 250;     // до этой ширины стекло паспортной толщины 13/41, как у Линзы
  const FIT_SLACK = 30;   // подпись влезает, когда до кромки остаётся ~8 px (как у Линзы)
  const LIGHT0 = -Math.PI / 4;
  const ND = 6;
  // Слоты закреплены за ролями: ядро smin неассоциативно, и капля, сменившая место
  // в цепочке посреди движения, дала бы скачок формы.
  const BEAD = 0;         // бусина у значка микрофона
  const DRIP = [1, 2];    // микрокапли «Слушаю», брызги радости
  const HALF = 3;         // вторая половина клетки, затем средняя бусина
  const TAILB = 4;        // правая бусина «Причёсываю»
  const SPARE = 5;        // капля ошибки, третий брызг
  // Где голова отпускает микрокаплю: на правом плече (−40°), у линии верхней
  // кромки капсулы, откуда капля сразу катится вправо.
  const DRIP_TH = (-40 * Math.PI) / 180;

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const clamp01 = (x) => clamp(x, 0, 1);
  const mix = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const deg = (a) => (a * Math.PI) / 180;

  // Копия нормированного smin основы: чтобы в JS знать, насколько вздулась кромка.
  function sminJS(a, b, k) {
    const kk = Math.max(k, 1e-4) * (16 / 3);
    const h = Math.max(kk - Math.abs(a - b), 0) / kk;
    return Math.min(a, b) - h * h * h * (4 - h) * kk / 16;
  }

  // Глубина «долины» между двумя пересекающимися кругами — от точки пересечения до
  // их общей внешней касательной. smin с k больше этой глубины выпирает за выпуклую
  // оболочку: две сильно перекрытые капли давали бы горб на стыке, а капля, почти
  // утонувшая в теле, — шишку. Поэтому k капли не больше долины: пока капли
  // разделены (мостик), k полное; по мере слияния оно само уходит к нулю.
  function valley(x1, y1, r1, x2, y2, r2) {
    const d = Math.hypot(x2 - x1, y2 - y1);
    if (d >= r1 + r2) return Infinity;
    if (d <= Math.abs(r1 - r2)) return 0;
    const x = (d * d + r1 * r1 - r2 * r2) / (2 * d);
    const y = Math.sqrt(Math.max(r1 * r1 - x * x, 0));
    const s = (r1 - r2) / d;
    const ny = Math.sqrt(Math.max(1 - s * s, 0));
    const depth = Math.max(0, r1 - (s * x + ny * y));
    // k у smin — в единицах поля расстояний, а не в px по вертикали: берём
    // расстояние от точки касательной над стыком до самих кругов. В шейке поле
    // растёт медленнее координаты, и «глубина в px» пускала горб за оболочку.
    const px = x + s * depth, py = y + ny * depth;
    return Math.max(0, Math.min(Math.hypot(px, py) - r1, Math.hypot(px - d, py) - r2));
  }

  function nearest(px, py, c) {
    const dx = c.bx - c.ax, dy = c.by - c.ay;
    const l2 = dx * dx + dy * dy;
    const t = l2 > 1e-6 ? clamp01(((px - c.ax) * dx + (py - c.ay) * dy) / l2) : 0;
    return { x: c.ax + dx * t, y: c.ay + dy * t, r: mix(c.ra, c.rb, t) };
  }

  // Капля целиком внутри компонента (с запасом 1 px) — утонула, её можно убрать.
  function inside(c, x, y, r) {
    const q = nearest(x, y, c);
    return Math.hypot(x - q.x, y - q.y) + r <= q.r - 1;
  }

  class Drop {
    constructor(S, i) {
      this.i = i;
      this.x = new S(0, 0.3, 0.8);
      this.y = new S(0, 0.3, 0.8);
      this.r = new S(0, 0.3, 0.8);
      this.seg = new S(0, 0.3, 0.9);   // половина длины вдоль x: половинка клетки — капсула
      this.on = false;
      this.role = '';
      this.merging = false;            // цель — слиться: утонула, значит исчезла
      this.noCap = false;              // бусина прирастает к торцу, её k не ограничиваем
      this.kBase = K_REST;             // k в покое; в движении — до 1.45× (RESEARCH.md)
      this.driven = false;             // x и seg ведёт расчёт (деление), пружины не шагают
      this.still = false;              // k без добавки за движение: шейка перед разрывом
      this.m = 0;                      // мера движения для k
      this.k = 0;                      // k этого кадра — чтобы знать, жив ли мостик
      this.tl = 0; this.tdx = -1; this.tdy = 0;   // хвост: длина и направление
      this.u = 0;
      this.age = 0;
      this.data = {};
    }
    spawn(role, x, y, r) {
      this.on = true; this.role = role; this.merging = false; this.noCap = false; this.driven = false; this.still = false;
      this.kBase = K_REST;
      this.x.snap(x); this.y.snap(y); this.r.snap(r); this.seg.snap(0);
      this.m = 0; this.tl = 0; this.u = 0; this.age = 0; this.data = {};
      return this;
    }
    kill() { this.on = false; this.role = ''; this.merging = false; this.driven = false; this.still = false; this.r.snap(0); this.seg.snap(0); }
    tune(resp, damp) {
      this.x.response = this.y.response = resp;
      this.x.damping = this.y.damping = damp;
      return this;
    }
    go(x, y) { this.x.set(x); this.y.set(y); return this; }
  }

  // Ведомая пружина: значение задаёт расчёт, скорость — из приращения. Когда расчёт
  // отпускает её, она продолжает с той же скоростью, без рывка.
  function drive(sp, v, dt) {
    sp.velocity = dt > 0 ? (v - sp.value) / dt : 0;
    sp.value = v;
    sp.target = v;
  }

  const SHAPE = `
uniform vec4 uBodyA;   // xy — начало оси тела, z — радиус там
uniform vec4 uBodyB;   // xy — конец оси тела, z — радиус там
uniform vec4 uBodyC;   // xy — центр мод, z — средний радиус
uniform vec4 uModes;   // моды Рэлея: n=2 (cos, sin) и n=3 (cos, sin), px
uniform vec4 uD[6];    // капли: xy — голова, z — её радиус, w — k (0 — без сглаживания)
uniform vec4 uT[6];    // xy — хвост, z — его радиус
uniform vec4 uBox;     // рамка формы: дальше неё только фон
uniform float uMat;
uniform float uBevel;
uniform float uAmp;
uniform float uSpec;
uniform vec2 uLight;
uniform vec4 uIcon;    // xy — центр значка, z — его непрозрачность, w — ореол: 1 светлый, −1 тёмный, 0 по фону
uniform vec4 uGlow;    // свечение голоса: xy — центр головы, z — сила, w — радиус, px

// Неравная капсула Килеса: круг ra в a, круг rb в b и касательные между ними.
// Одна фигура на всё: капсула плашки, круг, капля с хвостом, тяжёлая капля.
float sdUneven(vec2 p, vec2 a, vec2 b, float ra, float rb) {
  vec2 ba = b - a;
  float l = length(ba);
  if (l <= abs(ra - rb) + 1e-3) return ra >= rb ? length(p - a) - ra : length(p - b) - rb;
  vec2 u = ba / l;
  vec2 q = p - a;
  q = vec2(abs(q.x * u.y - q.y * u.x), dot(q, u));
  float s = (ra - rb) / l;
  float c = sqrt(1.0 - s * s);
  float k = dot(q, vec2(-s, c));
  if (k < 0.0) return length(q) - ra;
  if (k > c * l) return length(q - vec2(0.0, l)) - rb;
  return dot(q, vec2(c, s)) - ra;
}

// Тело и его собственные колебания. Моды гаснут к центру как (ρ/R)²: иначе угловая
// производная ~1/ρ дала бы «спицы» ложной кромки из центра (урок «Острова»).
float bodyD(vec2 p) {
  float d = sdUneven(p, uBodyA.xy, uBodyB.xy, uBodyA.z, uBodyB.z);
  if (dot(uModes, uModes) > 1e-4) {
    vec2 q = p - uBodyC.xy;
    float rho = length(q);
    float th = atan(q.y, q.x);
    float fade = min(rho / max(uBodyC.z, 1.0), 1.0);
    fade *= fade;
    d -= fade * (uModes.x * cos(2.0 * th) + uModes.y * sin(2.0 * th) + uModes.z * cos(3.0 * th) + uModes.w * sin(3.0 * th));
  }
  return d;
}

// Порядок цепочки фиксированный: тело, потом капли по слотам.
float shape(vec2 p) {
  float d = bodyD(p);
  for (int i = 0; i < 6; i++) {
    vec4 D = uD[i];
    if (D.z < 0.05) continue;
    float di = sdUneven(p, D.xy, uT[i].xy, D.z, uT[i].z);
    d = D.w > 0.02 ? smin(d, di, D.w) : min(d, di);
  }
  return d;
}

// Расстояние до ближайшей мелкой капли (брызг, осколок, микрокапля на излёте):
// вся такая капля — кромка в 1–2 толщины бортика, и расхождение каналов на ней
// рассыпалось цветными точками по тексту под ней.
float smallDrop(vec2 p) {
  float d = 1e5;
  for (int i = 0; i < 6; i++) {
    vec4 D = uD[i];
    if (D.z < 0.05 || D.z > 6.0) continue;
    d = min(d, sdUneven(p, D.xy, uT[i].xy, D.z, uT[i].z));
  }
  return d;
}
`;

  const MAIN = `
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Дальше рамки формы тень уже меньше 1/255: фон как есть, без выборок формы.
  if (uMat <= 0.001 || p.x < uBox.x - 70.0 || p.x > uBox.z + 70.0 || p.y < uBox.y - 60.0 || p.y > uBox.w + 80.0) {
    outColor = vec4(bg, 1.0);
    return;
  }
  Glass g = defaultGlass();
  g.bevel = uBevel;
  g.amplitude = uAmp;
  g.materialize = uMat;
  float d0 = shape(p);
  if (d0 > 1.5) {
    // Снаружи — только едва заметная тень общего стекла, без нормалей и размытия.
    float sd = shape(p - vec2(0.0, g.shadowY));
    float sh = uMat * g.shadow * exp(-max(sd, 0.0) / g.shadowBlur) * smoothstep(-g.shadowBlur, 0.0, sd);
    outColor = vec4(bg * (1.0 - sh), 1.0);
    return;
  }
  // Как у Линзы: лёгкое расхождение каналов только в кромке, в центре сдвига нет;
  // у капель мельче 6 px и на их шейках — без него.
  g.dispersion = (-d0 < uBevel + 1.0 && smallDrop(p) > d0 + 3.0) ? 0.035 : 0.0;
  vec4 glass = liquidGlass(p, g, bg);
  vec3 col = glass.rgb;
  float mc = clamp(uMat, 0.0, 1.0);
  const float wide = 1.8;
  bool nearRim = -d0 < wide + 0.5;
  if (glass.a > 0.0 && (nearRim || uStatus.x > 0.003)) {
    vec2 n;
    float inside = max(-shapeDist(p, n), 0.0);
    if (nearRim) {
      // Лепесток света Линзы в покое: узкая дуга у кромки со стороны источника
      // и вдвое слабее напротив. На светлом фоне свет читается тонкой тёмной линией.
      float c = dot(n, uLight);
      float lobe = pow(max(c, 0.0), 6.0) + 0.5 * pow(max(-c, 0.0), 6.0);
      float k = lobe * uSpec * glass.a * mc;
      float bright = smoothstep(0.5, 0.85, luma(col));
      float band = 1.0 - smoothstep(0.3, wide, inside);
      col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
      float edge = 1.0 - smoothstep(0.35, 1.25, inside);
      col *= 1.0 - 0.42 * bright * edge * k;
    }
    col = statusRim(col, p, inside, glass.a);
  }
  // Свечение голоса в голове бусины — «из-под пальца» (kit.js), как у «Линзы·Света».
  // Окно вокруг точки-значка — только на тёмном стекле: там подъём съедал бы её
  // контраст; треть света остаётся и в окне, иначе тёмное кольцо читалось зрачком.
  // На обоях точка темнее стекла, и светлое поле её, наоборот, выделяет.
  if (uGlow.z > 0.002 && glass.a > 0.0) {
    float dimGlass = 1.0 - smoothstep(0.35, 0.55, luma(col));
    float win = mix(0.3, 1.0, smoothstep(5.0, 14.0, length(p - uIcon.xy)));
    float hole = mix(1.0, win, dimGlass * clamp(uIcon.z, 0.0, 1.0));
    col = touchGlow(col, p, uGlow.xy, uGlow.w, uGlow.z, glass.a * mc * hole);
  }
  // Ореол под значком, как у Линзы: CSS-тень букв на SVG не ложится, и цветная
  // точка (в «Готово» — галочка) терялась на пёстром фоне. Тон ореола —
  // противоположный тону подписи; только в круге 20 px вокруг значка.
  vec2 di = p - uIcon.xy;
  float r2 = dot(di, di);
  if (uIcon.z > 0.01 && r2 < 400.0) {
    float lift = uIcon.w;
    if (abs(lift) < 0.5) {
      float mean = luma(sceneAt(uIcon.xy, 5.0) + sceneAt(uIcon.xy + vec2(-70.0, 0.0), 5.0) + sceneAt(uIcon.xy + vec2(70.0, 0.0), 5.0)) / 3.0;
      lift = mean > 0.45 ? 1.0 : -1.0;
    }
    float halo = exp(-r2 / 72.0) * uIcon.z * glass.a;
    col = lift > 0.0 ? col + (1.0 - col) * 0.45 * halo : col * (1.0 - 0.42 * halo);
  }
  outColor = vec4(col, 1.0);
}
`;

  LG.register({
    id: 'quicksilver',
    round: 2,

    setup(ctx) {
      const S = ctx.Spring;
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + SHAPE + ctx.glsl.glass + ctx.glsl.status + ctx.glsl.touch + MAIN);
      this.status = new LG.StatusFlash();
      this.mat = new S(0, 0.4, 0.82);
      this.shake = new S(0, 0.3, 0.38);
      this.body = {
        x: new S(0, 0.5, 0.85), y: new S(0, 0.5, 0.85),
        w: new S(160, 0.5, 0.85), h: new S(H0, 0.5, 0.85),
        sag: new S(0, 0.9, 1),
        // Моды Рэлея: ω_n² ∝ n(n−1)(n+2), поэтому третья вдвое чаще второй;
        // вязкость ∝ (n−1)(2n+1) — мелкая рябь гаснет втрое быстрее.
        c2: new S(0, 0.32, 0.2), s2: new S(0, 0.32, 0.2),
        c3: new S(0, 0.165, 0.42), s3: new S(0, 0.165, 0.42),
      };
      this.d = Array.from({ length: ND }, (_, i) => new Drop(S, i));
      this.stage = 'hidden';
      this.tmp = 0;
      this.env = 0;
      this.envHold = 0;
      this.quiet = 0;
      this.settle = new S(0, 0.3, 1);
      this.slow = 0.8;
      this.lastDrip = -9;
      this.lastSink = -9;
      // Свечение голоса: сила (огибающая фразы), акцент пика и где оно стоит.
      this.glowV = 0;
      this.glowS = 0;
      this.accent = new S(0, 0.55, 0.9);
      this.glowAt = null;
      // Тон подписи выбирает основа по фону; по нему — цвет галочки «Готово».
      this.labelEl = ctx.root ? ctx.root.querySelector('.lg-label') : null;
      this.ink = new S(0, 0.3, 1);
      this.toneKnown = false;
      this.split = null;
      this.phi = new S(0, 0.55, 0.8);
      this.divPhase = 0;
      this.polPhase = 0;
      this.polCycle = -1;
      this.textAt = null;
      this.react = {};
      this.err = {};
      this.comps = [];
      this.trace = {};
      this.bufD = new Float32Array(ND * 4);
      this.bufT = new Float32Array(ND * 4);
    },

    // Значение по темпераменту. Сам темперамент сглажен (0.25 с): переключатель на
    // странице меняет его скачком, а форма от него зависит напрямую — без
    // сглаживания длина грусти или вздутие бусины прыгнули бы.
    T(cat, lively) { return LG.temper({ temper: this.tmp }, cat, lively); },

    // Длина тяжёлой капли грусти, px: нужна и форме, и подписи (галочка едет с центром).
    SAG_L() { return this.T(14, 16); },

    tuneBody(resp, damp) {
      const B = this.body;
      for (const k of ['x', 'y', 'w', 'h']) { B[k].response = resp; B[k].damping = damp; }
    },

    // Ось тела: капсула шириной w и высотой h, в грусти — вертикальная тяжёлая капля.
    bodyComp(ox) {
      const B = this.body;
      const hx = Math.max(B.w.value - B.h.value, 0) / 2;
      const R = B.h.value / 2;
      const sag = Math.max(0, B.sag.value);
      // Тяжёлая капля: верх сужается, низ полнеет и уходит вниз; площадь ~та же.
      // Верх не уже 0.72R и длина не больше 16 px: дальше груша читается значком «слеза».
      const L = this.SAG_L() * sag;
      return {
        ax: B.x.value + ox - hx, ay: B.y.value - 0.3 * L, ra: R * (1 - 0.28 * sag),
        bx: B.x.value + ox + hx, by: B.y.value + 0.7 * L, rb: R * (1 + 0.04 * sag),
        cx: B.x.value + ox, cy: B.y.value, R,
      };
    },

    endSplit() {
      if (!this.split) return;
      this.split = null;
      const h = this.d[HALF];
      h.driven = false;
      h.still = false;
    },

    enter(s, G) {
      const from = this.stage;
      this.stage = s.stage;
      const B = this.body;
      this.textAt = null;
      if (s.stage !== 'transcribing') this.endSplit();
      if (s.stage === 'listening') {
        if (from === 'hidden' || this.mat.value < 0.05) {
          // Появление: форма сразу под текст, растёт линза, а не размер.
          B.x.snap(G.cx); B.y.snap(G.cy); B.w.snap(s.targetW); B.h.snap(H0); B.sag.snap(0);
          for (const k of ['c2', 's2', 'c3', 's3']) B[k].snap(0);
          for (const d of this.d) d.kill();
        }
        this.env = 0;
        this.envHold = 0;
        this.quiet = 0;
        this.settle.snap(0);
        this.slow = 0.8;
        this.lastDrip = -9;
        this.lastSink = -9;
      } else if (s.stage === 'transcribing') {
        this.split = null;
      } else if (s.stage === 'polishing') {
        this.polPhase = 0;
        this.polCycle = -1;
      } else if (s.stage === 'done') {
        this.react = { kicked: false, landed: false, landAt: 0, sp: [false, false], nod: false };
      } else if (s.stage === 'error') {
        this.err = { spawned: false, at: 0, popAt: null, burst: false };
      }
    },

    // ---------------------------------------------------------------- слушаю

    listening(s, G, dt) {
      const B = this.body;
      this.tuneBody(0.5, 0.85);
      B.x.set(G.cx); B.y.set(G.cy); B.w.set(s.targetW); B.h.set(H0); B.sag.set(0);
      // Огибающая фразы: уровень второго круга почти всегда 0.8–0.9 в речи и ноль
      // в паузе, поэтому бусина живёт фразами. Атака 100 мс, спад 320 мс — поверх
      // сглаживания основы слог уже не виден. Эта огибающая ведёт только «жизнь»
      // бусины (дыхание, покачивание): на вдохе она замирает.
      const v = s.level * s.speech;
      const a = v > this.env ? 1 - Math.exp(-dt / 0.1) : 1 - Math.exp(-dt / 0.32);
      this.env += (v - this.env) * a;
      const voice = smooth(0.08, 0.7, this.env);
      // Размер и вынос головы. Как только голос стих, голова выдыхает — оседает
      // на 35% размера (40% у «живее») пружиной без перелёта за ~0.2 с: горб над
      // кромкой уходит с ~13 px до ~3, и «молчу» видно боковым зрением уже на
      // вдохе между фразами (0.25–0.8 с). При выдохе 12% и удержании 0.45 с пауза
      // 0.5 с давала 15.8 → 9.1 px, а следующая фраза стояла на тех же 9–10 —
      // речь и пауза выходили одного размера. Сдувается до конца голова только в
      // настоящей паузе: огибающая держится 0.15 с (τ 1.3 с), дальше спадает
      // за 0.4 с (0.34 у «живее»). Порог тишины 0.5: даже тихая фраза держит
      // level·speech выше 0.6, а конец фразы ловится на ~0.1 с раньше, чем при 0.4.
      this.quiet = v < 0.5 ? this.quiet + dt : 0;
      const tauH = this.quiet < 0.15 ? 1.3 : this.T(0.4, 0.34);
      const ah = v > this.envHold ? 1 - Math.exp(-dt / 0.1) : 1 - Math.exp(-dt / tauH);
      this.envHold += (v - this.envHold) * ah;
      // Выдох — пружина без перелёта: начинается мягко, а не рывком экспоненты;
      // вдох на новой фразе быстрее, голос подхватывается сразу.
      const st = this.quiet > 0 ? 1 : 0;
      this.settle.response = st > this.settle.value ? this.T(0.3, 0.26) : 0.22;
      const settle = clamp01(this.settle.set(st).step(dt));
      const hold = smooth(0.08, 0.7, this.envHold) * (1 - this.T(0.35, 0.4) * settle);
      // Сила фразы — медленная огибающая уровня (атака 0.25 с, спад 0.6 с), и только
      // пока говорят: в паузе она держится, иначе каждая фраза начиналась бы «тихой».
      // Громкость фраз после окна дБ различается мало (тихая ~0.72, громкая ~0.87),
      // поэтому отрезок узкий.
      if (s.speech > 0.3) {
        const la = s.level > this.slow ? 1 - Math.exp(-dt / 0.25) : 1 - Math.exp(-dt / 0.6);
        this.slow += (s.level - this.slow) * la;
      }
      const loud = clamp01((this.slow - 0.7) / 0.2);
      const bead = this.d[BEAD];
      const hx = Math.max(B.w.value - B.h.value, 0) / 2;
      const capX = B.x.value - hx;
      if (!bead.on) bead.spawn('bead', capX, B.y.value, 12);
      // Бусина прирастает к торцу, а не сливается: k без потолка по долине. Круглая
      // голова вдвое толще прежней, и галтель 4.2 уже не растекается по кромке
      // (при 5.25 и бусине чуть толще капсулы она тянулась на 40 px и читалась
      // кособокой капсулой), а перехват у торца остаётся мягким.
      bead.noCap = true;
      bead.kBase = 4.2;
      // Бусина — поверхностное натяжение: упругая, у кота почти без перелёта.
      bead.r.response = this.T(0.42, 0.32);
      bead.r.damping = this.T(0.74, 0.56);
      // Импакт голоса — сама бусина: в речи у кота она выше кромки капсулы на
      // 13–17 px, а силуэт длиннее на 28–30 px (163 → 191–193). На белом документе
      // свет и преломление почти не видны, а длина и горб над кромкой видны
      // боковым зрением. Крупнее — уже головастик, а не капля.
      // rSpeak — нижний предел головы во фразе: горб не ниже ~12 px, и дыхание не
      // опускает её до уровня паузы (раньше тихая фраза на выдохе дыхания стояла
      // на 9 px — вровень с паузой).
      const rSpeak = this.T(41.5, 43);
      // Живая система, пока говорят: бусина медленно дышит (0.5 Гц), громкая фраза
      // крупнее тихой и центр её плавно покачивается вверх-вниз (0.3 Гц). Все
      // частоты ниже 1 Гц — слоги 3–8 Гц в форме не видны. Дыхание и громкость
      // только добавляют к пределу, а не вычитают: максимум головы тот же, что и
      // был (~44 px), а минимум во фразе поднят. Дыхание и покачивание идут от
      // быстрой огибающей: на вдохе они гаснут сразу, и бусина замирает.
      const breath = this.T(1.6, 2.0) * (0.5 + 0.5 * Math.sin(2 * Math.PI * 0.5 * s.time)) * voice;
      const phrase = this.T(1.5, 2.0) * loud * voice;
      const sway = this.T(1.0, 1.4) * Math.sin(2 * Math.PI * 0.3 * s.time + 0.8) * voice;
      bead.r.set(12 + (rSpeak - 12) * hold + breath + phrase);
      // Второй носитель голоса — свечение «из-под пальца» в голове (kit.js): на
      // тёмном и на обоях голова светится изнутри, пока говорят, и гаснет вместе с
      // выдохом. На белом документе белый свет не виден — там голос несёт силуэт.
      // Гаснет по выдоху, а не по медленной огибающей: иначе на вдохе 0.5 с
      // свечение держалось бы на трети силы и спорило с выдохом головы.
      this.glowV = voice * (1 - 0.75 * settle);
      // Бусина приросла к торцу (ведём её за ним, а не пружиной — при сжатии не
      // отстаёт) и тянется наружу, к голосу: выступает из торца каплей с
      // перехватом, а не утолщает капсулу. Подпись при этом стоит на месте.
      bead.driven = true;
      drive(bead.x, capX - this.T(14, 15) * hold, dt);
      drive(bead.y, B.y.value + sway, dt);
      // Свечение — из центра головы: до первой буквы от него ~36 px, и подпись
      // остаётся на спокойном стекле.
      this.glowAt = [bead.x.value, bead.y.value];
      for (const e of s.events) {
        if (e.type !== 'peak') continue;
        const st = e.strength == null ? 0.5 : e.strength;
        // Ударное место — короткий подъём свечения, как у «Линзы·Света».
        this.accent.velocity += this.T(13, 19) * (0.5 + 0.5 * st);
        this.onPeak(s, st);
      }
      for (const i of DRIP) {
        const d = this.d[i];
        if (d.on && d.role === 'drip') this.dripStep(d, s, dt);
      }
    },

    onPeak(s, strength) {
      // Микрокапля — редкий акцент, а не конвейер по кромке: только на сильном
      // пике, одна за раз, не чаще раза в 1.6 с у кота (1.2 с у «живее») и не
      // раньше 0.3 с после того, как утонула прошлая.
      if (strength < 0.5) return;
      if (s.time - this.lastDrip < this.T(1.6, 1.2) || s.time - this.lastSink < 0.3) return;
      if (DRIP.some((i) => this.d[i].on)) return;
      const d = this.d[DRIP[0]];
      const bead = this.d[BEAD];
      if (bead.r.value < 30) return;   // сдувшаяся бусина капель не роняет
      this.lastDrip = s.time;
      // 8–9 px: у капли есть своё тело с бликом и кромкой, а не острый «шатёр»
      // над кромкой, как было при 6 px.
      const rm = this.T(8, 9) + 0.6 * clamp01(strength);
      const rb = bead.r.value;
      const th = DRIP_TH;
      const rho = Math.max(rb - rm - 3, 0);
      d.spawn('drip', bead.x.value + Math.cos(th) * rho, bead.y.value + Math.sin(th) * rho, rm);
      // Бусина вынесена на 14–15 px наружу, а капля рождается на плече, поэтому
      // путь длиннее: по кромке она катится те же ~40 px, что и раньше.
      d.data = { T: this.T(1.1, 0.85), rm, run: this.T(80, 88), melt: false };
      d.tune(0.12, 0.85);
      // Бусина отдаёт объём: короткое втягивание, натяжение возвращает её.
      bead.r.velocity -= this.T(10, 16);
    },

    // Путь микрокапли: почкуется на верхушке бусины, скатывается по её плечу на
    // верхнюю кромку капсулы и катится вправо снаружи, держась за кромку тонким
    // мениском, потом тонет в кромке. Центр всегда выше кромки на радиус — текст
    // посреди капсулы она не пересекает.
    dripStep(d, s, dt) {
      const bead = this.d[BEAD];
      d.u += dt / d.data.T;
      const u = d.u;
      const rm = d.data.rm;
      const bx = bead.x.value, by = bead.y.value;
      const rb = Math.max(bead.r.value, R0);
      const top = this.body.y.value - this.body.h.value / 2;
      // Поверхность, по которой катится капля: плечо бусины, дальше верхняя кромка
      // капсулы (без покачивания бусины — иначе капля плавала бы над кромкой).
      const surf = (x) => Math.min(top, by - Math.sqrt(Math.max(rb * rb - (x - bx) * (x - bx), 0)));
      const th = DRIP_TH;
      // Зазор до кромки — тонкий мениск: капля катится по стеклу, а не бежит волной.
      // 4 px при k 1.8: перемычка живёт, только пока капля движется (k ×1.45), и
      // остаётся шейкой, а не сходится с кромкой в острие.
      const gap = 4;
      const x0 = bx + Math.cos(th) * (rb + rm + gap);
      const x1 = Math.max(bx + d.data.run, x0 + 20);
      // Почкование короткое (0.12 хода) и на плече головы, у линии верхней кромки:
      // на макушке капля торчала на шейке «хвостиком тыквы». Конец почкования —
      // сразу точка начала пути по кромке, без излома траектории.
      const U_BUD = 0.12;
      let tx, ty;
      if (u < U_BUD) {
        const q = smooth(0, U_BUD, u);
        const rho = Math.max(rb - rm - 3, 0);
        tx = mix(bx + Math.cos(th) * rho, x0, q);
        ty = mix(by + Math.sin(th) * rho, surf(x0) - rm - gap, q);
      } else if (u < 0.82) {
        tx = mix(x0, x1, easeInOut((u - U_BUD) / (0.82 - U_BUD)));
        ty = surf(tx) - rm - gap;
      } else {
        // Тонет: капля тает (радиус к 0.55) и уходит под кромку круглой, а не
        // расплывается галтелью шире себя — у 8 px с k слияния 7.6 выходил «шатёр».
        // Ведём нижний край, а не центр: тающая капля иначе отрывалась от кромки и
        // на пару кадров повисала над ней отдельной точкой.
        const q = smooth(0.82, 1, u);
        if (!d.data.melt && u > 0.84) {
          d.data.melt = true;
          d.r.response = 0.12; d.r.damping = 1;
          d.r.set(0.55 * rm);
        }
        tx = x1 + 3 * q;
        const bottom = mix(surf(x1) - gap, top + 1.1 * rm + 2, q);
        ty = bottom - Math.max(d.r.value, 0.5);
        d.merging = true;
      }
      // Пока катится — тугой мениск (k 1.8); к концу хода натяжение растит k к 5.25
      // (капля замедляется, и мениск при k 1.8 рвался бы), но потолок в кадре
      // держит галтель не шире половины капли.
      d.kBase = mix(1.8, K_REST, smooth(0.76, 0.95, u));
      d.go(tx, ty);
      if (u > 1.3) { d.kill(); this.lastSink = s.time; }
    },

    // ---------------------------------------------------------------- распознаю

    transcribing(s, G, dt) {
      const B = this.body;
      const t = s.t;
      // Подпись гаснет раньше, чем форма начнёт сжиматься: иначе старый текст
      // на миг торчал бы из сжимающейся капсулы.
      const hold = 0.16;
      this.absorbExcept(s, [HALF], G);
      if (!this.split) {
        this.tuneBody(0.42, 0.85);
        B.x.set(G.cx); B.y.set(G.cy); B.h.set(H0); B.sag.set(0);
        if (t > hold) B.w.set(W_C);
        const ready = t > hold && Math.abs(B.w.value - W_C) < 2.5 && Math.abs(B.w.velocity) < 60;
        if (ready || t > 0.8) this.handoff(s);
        return;
      }
      // Деление клетки. φ — фаза: 0 — одна компактная капсула, 1 — две капли.
      const sp = this.split;
      const P = this.T(2.0, 1.7);
      const cycle = Math.floor(this.divPhase);
      this.divPhase += dt / P;
      const u = this.divPhase - Math.floor(this.divPhase);
      if (Math.floor(this.divPhase) !== cycle) { sp.goal = 1; sp.brokeAt = null; }
      // Цель «разделиться» — только до разрыва шейки и 0.07 с после него: дальше
      // половинки сразу срастаются пружиной 0.5/0.7. Две разошедшиеся круглые капли,
      // которые стоят рядом, читались двумя точками загрузки, а не делящейся
      // клеткой, — порознь они теперь ~0.1 с. Страховка — треть цикла.
      if (sp.goal === 1 && ((sp.brokeAt != null && s.time - sp.brokeAt > 0.07) || u > 0.35)) sp.goal = 0;
      if (sp.goal === 1) {
        this.phi.response = this.T(0.6, 0.5);
        this.phi.damping = this.T(0.78, 0.66);
        this.phi.set(1);
      } else {
        this.phi.response = this.T(0.5, 0.44);
        this.phi.damping = this.T(0.7, 0.62);
        // Предвосхищение: во второй половине паузы клетка уже собирается делиться —
        // плавно вытягивается на ~7 px (цель φ 0.16, пружина успевает до ~0.14), и
        // форма остаётся статусом весь цикл, а не стоит овалом 1.2 с из 2.
        this.phi.set(0.16 * smooth(0.5, 1.0, u));
      }
      const phi = this.phi.step(dt);
      // Перелёт фазы за единицу (у «живее» ζ 0.66 — до 1.06) мягко насыщается: иначе
      // половинки разбегались бы на 12 px, а зазор держим в 8–10.
      const pp = phi > 1 ? 1 + 0.02 * Math.tanh((phi - 1) / 0.02) : Math.max(phi, 0);
      const pn = Math.min(phi, 0);
      // Между делениями форма не замирает: дышит вдоль и поперёк в противофазе
      // (0.5 Гц, ~1.2 px), площадь та же — «думающая» капля собирается к делению.
      const rest = 1 - smooth(0.05, 0.3, Math.abs(phi));
      const br = this.T(1.2, 1.5) * Math.sin(2 * Math.PI * 0.5 * s.time) * rest;
      // Площадь сохраняется: две капли меньше одной. Перелёт при срастании (φ < 0)
      // — не вмятина, а короткое сплющивание: капсула короче и выше.
      const r = mix(sp.r0, sp.rS, smooth(0.1, 0.9, pp)) * (1 - 0.35 * pn) - 0.5 * br;
      const L = sp.L0 * (1 - smooth(0, 0.7, pp)) + 0.5 * br;
      // Полный разрыв — зазор не больше 10 px (в пределах 2k при k 5.25): половинки
      // расходятся ровно настолько, чтобы шейка порвалась, и не разбегаются.
      const c = mix(sp.L0, sp.rS + 4.5, pp) + 16 * pn + 0.5 * br;
      const m = G.cx;
      drive(B.x, m - c, dt);
      drive(B.w, 2 * L + 2 * r, dt);
      drive(B.h, 2 * r, dt);
      drive(B.y, G.cy, dt);
      const h = this.d[HALF];
      h.driven = true;
      drive(h.x, m + c, dt);
      drive(h.seg, L, dt);
      drive(h.r, r, dt);
      drive(h.y, G.cy, dt);
      // Шейка тоньшает перед разрывом, как жидкая перемычка (Рэлей — Плато): k к
      // концу вытягивания спадает с 5.25 до 3.4 и без добавки за движение. Иначе
      // мостик при k 7.6 жил бы до зазора ~15 px, и половинки расходились бы на 16.
      // После разрыва остаток перемычки smin — острые «носики» у половинок;
      // натяжение скругляет их за ~80 мс: k быстро спадает до 2.4. Срастание —
      // щелчком: как только половинки пошли навстречу и зазор меньше 2·5.25, k
      // возвращается к 5.25 (в движении до 7.6), и мостик возникает сам.
      const gap = 2 * c - 2 * L - 2 * r;
      const pinch = sp.goal === 1 && !sp.broken;
      h.still = pinch;
      const kT = sp.broken ? 2.4 : pinch ? mix(K_REST, 3.4, smooth(0.75, 0.95, pp)) : K_REST;
      h.kBase += (kT - h.kBase) * (1 - Math.exp(-dt / (sp.broken ? 0.03 : 0.06)));
      if (!sp.broken && gap > 2 * h.k + 0.5) { sp.broken = true; sp.brokeAt = s.time; }
      else if (sp.broken && sp.goal === 0 && this.phi.velocity < 0 && gap < 2 * K_REST) sp.broken = false;
      this.trace.split = phi;
      this.trace.gap = gap;
    },

    // Капсула уже компактная: делим её на две половинки, чей союз — ровно она сама
    // (k на стыке ноль по долине), и дальше ведём их фазой деления.
    handoff(s) {
      const B = this.body;
      const hx = Math.max(B.w.value - B.h.value, 0) / 2;
      const r0 = B.h.value / 2;
      const m = B.x.value;
      const area = 4 * hx * r0 + Math.PI * r0 * r0;
      this.split = { r0, L0: hx / 2, rS: Math.sqrt(area / (2 * Math.PI)), broken: false, goal: 1, brokeAt: null };
      B.x.snap(m - hx / 2); B.w.snap(hx + 2 * r0);
      const h = this.d[HALF];
      h.spawn('half', m + hx / 2, B.y.value, r0);
      h.seg.snap(hx / 2);
      h.driven = true;
      this.phi.snap(0);
      this.divPhase = 0;
    },

    // ---------------------------------------------------------------- причёсываю

    polishing(s, G, dt) {
      const B = this.body;
      const m = G.cx, cy = G.cy;
      // Цикл без паузы: одна капля живёт лишь миг и снова выпускает бусы. Иначе
      // «Причёсываю» кончалось бы готовой каплей, и слияния в «Готово» не было бы видно.
      const P2 = this.T(1.25, 1.05);
      this.polPhase += dt / P2;
      const n = Math.floor(this.polPhase);
      const u = this.polPhase - n;
      const resp = this.T(0.36, 0.3), damp = this.T(0.8, 0.68);
      this.tuneBody(resp, damp);
      B.sag.set(0);
      const bB = this.d[HALF], bC = this.d[TAILB];
      this.absorbExcept(s, [HALF, TAILB], G);
      if (n !== this.polCycle) {
        this.polCycle = n;
        // Новые бусины рождаются внутри тела — невидимы — и выкатываются вправо.
        if (!bB.on) bB.spawn('bead', B.x.value, cy, Math.min(16, B.h.value / 2 - 2));
        if (!bC.on) bC.spawn('bead', bB.x.value, cy, Math.min(11, bB.r.value - 2));
        bB.merging = false; bC.merging = false;
      }
      // Бусы: три капли с перемычками, крупная слева. Площади складываются в круг 28.
      // Перетекание — не шаг цели, а плавный ход: правая вливается в среднюю,
      // средняя (уже полная) неспешно перетекает в левую до самого конца цикла.
      const q1 = easeInOut(clamp01((u - 0.26) / 0.24));
      const q2 = easeInOut(clamp01((u - 0.5) / 0.46));
      const cxp = mix(m + 40, m + 16, q1);
      const bx = mix(mix(m + 8, m + 14, q1), m - 3, q2);
      const br = mix(16, 20, q1);
      const ax = mix(m - 32, m - 3, q2);
      const ar = mix(20, 28.3, q2);
      if (u >= 0.26) bC.merging = true;
      if (u >= 0.5) bB.merging = true;
      // Одна круглая капля — только миг в конце цикла: «Готово» почти всегда
      // застаёт, что слить.
      B.x.set(ax); B.y.set(cy); B.w.set(2 * ar); B.h.set(2 * ar);
      if (bB.on) { bB.tune(resp, damp).go(bx, cy); bB.r.set(br); bB.seg.set(0); }
      if (bC.on) { bC.tune(resp, damp).go(cxp, cy); bC.r.set(11); }
      this.trace.split = u;
    },

    // Капли, которые этой стадии не нужны, тонут в теле: цель — ось тела под ними.
    absorbExcept(s, keep, G) {
      const bc = this.bodyComp(0);
      for (const d of this.d) {
        if (!d.on || keep.includes(d.i)) continue;
        if (d.role === 'drip' && s.stage === 'listening') continue;
        if (d.role === 'splash' || d.role === 'err' || d.role === 'pop') continue;
        const q = nearest(d.x.value, d.y.value, bc);
        d.merging = true;
        d.driven = false;
        d.seg.set(0);
        if (d.role === 'bead' && d.i === BEAD) d.r.set(10);
        d.go(q.x, q.y);
      }
    },

    // ---------------------------------------------------------------- готово

    done(s, G, dt) {
      const B = this.body;
      const R = this.react;
      // Пружина bouncy: 0.5 с, отскок 0.3.
      this.tuneBody(0.5, 0.7);
      B.x.set(G.cx); B.w.set(H0); B.h.set(H0);
      let yT = G.cy;
      for (const d of this.d) {
        if (!d.on || d.role === 'splash' || d.role === 'pop') continue;
        d.merging = true;
        d.driven = false;
        d.tune(0.5, 0.7).go(B.x.value, B.y.value);
        d.seg.set(0);
      }
      const joy = s.emotion === 'joy', sad = s.emotion === 'sad';
      if (!joy && !sad && !R.nod && s.t > 0.26) {
        // Кивок: удовлетворённо оседает на ~3 px и возвращается без перелёта.
        R.nod = true;
        B.y.velocity += this.T(95, 130);
      }
      if (!joy) { B.y.response = 0.5; B.y.damping = sad ? 1 : 0.8; }
      if (joy) this.joy(s, G);
      B.sag.response = this.T(0.9, 0.75);
      B.sag.damping = 1;
      if (sad) {
        // Грусть: вытягивается вниз тяжёлой каплей и медленно стекает, без перелёта;
        // после первой секунды отпускает не до конца — дольше затихает.
        const tgt = s.t < 0.3 ? 0 : s.t < 1.05 ? 1 : this.T(0.3, 0.4);
        B.sag.set(tgt);
        yT += this.T(5, 6) * Math.max(0, B.sag.value);
      } else {
        B.sag.set(0);
      }
      B.y.set(yT);
      // Мода 2 звенит 2–3 качка и гаснет к ~0.6 с, мода 3 — втрое быстрее. В
      // грусти звон гасится до того, как капля начнёт стекать: иначе груша
      // выходила кривой, с заваленной вбок верхушкой.
      const z2 = sad && s.t > 0.3 ? 0.8 : this.T(0.24, 0.18);
      B.c2.damping = B.s2.damping = z2;
      B.c3.damping = B.s3.damping = sad && s.t > 0.3 ? 0.8 : 0.42;
      B.c2.response = B.s2.response = this.T(0.33, 0.29);
      B.c3.response = B.s3.response = this.T(0.17, 0.15);
    },

    joy(s, G) {
      const B = this.body;
      const R = this.react;
      B.y.response = this.T(0.5, 0.44);
      B.y.damping = this.T(0.72, 0.62);
      if (!R.kicked && s.t >= this.T(0.28, 0.26)) {
        R.kicked = true;
        B.y.velocity -= this.T(250, 440);
      }
      // Растяжение по скорости: в полёте капля вытягивается вверх-вниз, на
      // приземлении мода сама проскакивает в сплющивание.
      if (R.kicked) B.c2.set(-clamp(Math.abs(B.y.velocity) * this.T(0.006, 0.009), 0, 2.4));
      if (R.kicked && !R.landed && B.y.velocity > 0 && B.y.value > G.cy - 1.5) {
        R.landed = true;
        R.landAt = s.t;
        R.sp = [false, false];
        B.c2.set(0);
      }
      if (R.landed) {
        // Брызги: пара микрокапель с боков, где капля «приземлилась». Летят дугой
        // наружу-вверх с лёгкой тяжестью, отрываются и падают обратно. С верхушки
        // не брызжет: три лучика читались ушами и плавниками, а не жидкостью.
        // Рождаются снаружи кромки, на 20° ниже экватора — от удара о «землю», а не
        // крыльями по экватору; шейка у них тонкая (k 1.5) и живёт 2–3 кадра.
        const bc = this.bodyComp(0);
        // Брызги не зеркальны: левый короче и раньше, правый дальше, ниже по боку
        // (25° против 20°) и на 60 мс позже. Два одинаковых брызга, прилипших к
        // бокам в один кадр, складывались в симметричный силуэт — «Сатурн» на
        // экваторе, колокол ниже, уши выше, а при сдвиге 25 мс (полтора кадра) —
        // «ручки чашки»; вразнобой это читается жидкостью.
        [[160, 0.85, 0.92, 0], [25, 1.15, 1.1, 0.06]].forEach(([ang, sOut, sT, lag], i) => {
          const d = this.d[DRIP[i]];
          if (R.sp[i] || s.t < R.landAt + lag) return;
          R.sp[i] = true;
          if (d.on) return;
          const rs = this.T(3.4, 4.2);
          const out = this.T(15, 22) * sOut;     // вылет вбок, px
          const apex = this.T(7, 12) * sOut;     // высота дуги, px
          const Tf = this.T(0.26, 0.32) * sT;    // время полёта, с
          const g = (8 * apex) / (Tf * Tf);
          const a = deg(ang);
          const c = Math.cos(a), sn = Math.sin(a);
          d.spawn('splash', bc.cx + c * (bc.R + 1), bc.cy + sn * (bc.R + 1), rs);
          // Возврат — в точку у самой кромки (центр на R − rs), а не внутрь по
          // экватору: брызг касается кромки и тает, не протаскивая перемычку.
          d.data = { x0: d.x.value, dir: Math.sign(c), out, vy: -g * Tf / 2, g, T: Tf, rs, touch: false, ax: c * (bc.R - rs), ay: sn * (bc.R - rs) };
          d.driven = true;
          d.kBase = 1.5;
          d.tune(0.3, 0.8);
        });
      }
    },

    // ---------------------------------------------------------------- ошибка

    error(s, G, dt) {
      const B = this.body;
      const E = this.err;
      this.tuneBody(0.45, 0.8);
      B.x.set(G.cx); B.y.set(G.cy); B.w.set(s.targetW); B.h.set(H0); B.sag.set(0);
      this.absorbExcept(s, [SPARE], G);
      const e = this.d[SPARE];
      if (!E.spawned && s.t >= 0.2) {
        E.spawned = true;
        E.at = s.t;
        const bc = this.bodyComp(0);
        if (e.on) e.kill();
        // Капля рождается у самой кромки правого торца (почти целиком внутри —
        // k по долине ноль, горба нет) и выстреливает: стартовая скорость, а не
        // цель, поэтому шейка рвётся за ~60 мс, а не тянет из торца «бутылку».
        // Пружина (0.36 с, ζ 0.9) только тормозит её — без стояния точкой.
        const a = deg(-10);
        const v0 = this.T(340, 380);
        const run = this.T(44, 50);
        e.spawn('err', bc.bx + 17, bc.by, 10.5);
        e.tune(0.36, 0.9);
        e.go(e.x.value + Math.cos(a) * run, e.y.value + Math.sin(a) * run);
        e.x.velocity = v0 * Math.cos(a);
        e.y.velocity = v0 * Math.sin(a);
        // Отдача: капсула вздрагивает влево на ~4 px (у «живее» ~6) и раз-другой
        // качается (ζ 0.38) — смущённо «мотает головой».
        this.shake.velocity -= this.T(140, 200);
      }
      if (e.on && e.role === 'err') {
        const age = s.t - E.at;
        // Натяжение рвёт шейку: k спадает до 1.2 за ~60 мс — у торца не остаётся
        // носика, а капля уходит круглой.
        e.kBase += (1.2 - e.kBase) * (1 - Math.exp(-dt / 0.03));
        // Лопается на ходу, не успев повиснуть: вздувается на 15% за 50 мс,
        // потом схлопывается за ~80 мс, и в разлёт уходят две микрокапли.
        if (age >= this.T(0.22, 0.2) && E.popAt == null) {
          E.popAt = s.t;
          e.r.response = 0.1; e.r.damping = 0.75;
          e.r.set(10.5 * 1.15);
        }
        if (E.popAt != null && !E.burst && s.t - E.popAt >= 0.05) {
          E.burst = true;
          e.r.response = 0.08; e.r.damping = 1;
          e.r.set(0);
          this.burst(e);
        }
        if (E.burst && e.r.value < 0.3) e.kill();
      }
    },

    // Осколки лопнувшей капли: две микрокапли по 2 px разлетаются на ~6 px по
    // ходу движения и тают. Не сливаются ни с чем (k 0) — это брызги, не жидкость.
    burst(e) {
      const ang = Math.atan2(e.y.velocity, e.x.velocity);
      [-0.9, 0.9].forEach((da, i) => {
        const d = this.d[DRIP[i]];
        if (d.on) d.kill();
        d.spawn('pop', e.x.value, e.y.value, 2);
        d.driven = true;
        d.kBase = 0;
        d.data = { x0: e.x.value, y0: e.y.value, dx: Math.cos(ang + da) * 6 + e.x.velocity * 0.05, dy: Math.sin(ang + da) * 6 + e.y.velocity * 0.05 };
        d.r.response = 0.16; d.r.damping = 1;
        d.r.set(0);
      });
    },

    hidden(s, G, dt) {
      // Обратная материализация: форма стоит, линза гаснет. Летящие брызги и капля
      // ошибки дотекают как есть.
      const e = this.d[SPARE];
      if (e.on && e.role === 'err') { e.r.response = 0.09; e.r.damping = 1; e.r.set(0); if (e.r.value < 0.3) e.kill(); }
    },

    // ---------------------------------------------------------------- кадр

    frame(ctx, s) {
      const dt = s.dt;
      const cx0 = ctx.W / 2, cy0 = ctx.H / 2;
      this.tmp += ((s.temper || 0) - this.tmp) * (1 - Math.exp(-dt / 0.25));
      const G = { cx: cx0, cy: cy0 };
      if (s.stage !== this.stage) this.enter(s, G);
      this.status.step(s);
      this.trace = { split: 0 };

      // Материализация, как у Линзы: на уходе быстрее и без перелёта.
      if (s.shown) { this.mat.response = 0.4; this.mat.damping = 0.82; }
      else { this.mat.response = 0.32; this.mat.damping = 1.0; }
      const m = this.mat.set(s.shown ? 1 : 0).step(dt);
      const mc = clamp01(m);

      if (s.stage === 'listening') this.listening(s, G, dt);
      else if (s.stage === 'transcribing') this.transcribing(s, G, dt);
      else if (s.stage === 'polishing') this.polishing(s, G, dt);
      else if (s.stage === 'done') this.done(s, G, dt);
      else if (s.stage === 'error') this.error(s, G, dt);
      else this.hidden(s, G, dt);

      // ---- свечение голоса: в «Слушаю» идёт за огибающей фразы, после — гаснет
      // за ~0.1 с, чтобы не висело на месте бусины, когда та уже тонет в теле.
      const hearing = s.stage === 'listening';
      if (!hearing) this.glowV = 0;
      this.glowS += (this.glowV - this.glowS) * (1 - Math.exp(-dt / (hearing ? 0.03 : 0.08)));
      // Акцент пика после «Слушаю» тоже гаснет быстро и без перелёта.
      this.accent.response = hearing ? this.T(0.55, 0.42) : 0.15;
      this.accent.damping = hearing ? 0.9 : 1;
      const acc = Math.max(0, this.accent.set(0).step(dt));

      // ---- шаг пружин
      const B = this.body;
      if (!this.split) { B.x.step(dt); B.w.step(dt); B.h.step(dt); }
      B.y.step(dt); B.sag.step(dt);
      for (const k of ['c2', 's2', 'c3', 's3']) B[k].step(dt);
      const ox = this.shake.set(0).step(dt);
      for (const d of this.d) {
        if (!d.on) continue;
        d.age += dt;
        if (!d.driven) { d.x.step(dt); d.y.step(dt); d.seg.step(dt); }
        if (!(d.driven && this.split && d.i === HALF)) d.r.step(dt);
        if (d.role === 'splash') {
          const D = d.data;
          if (d.age < D.T) {
            // Полёт — баллистика: мениск тугой, шейка рвётся, брызг летит каплей.
            // Вбок — с резким стартом (ease-out): шейка рвётся за ~70 мс, и
            // брызг не висит на ней ушком; вверх-вниз — дуга с лёгкой тяжестью.
            D.vy += D.g * dt;
            const q = clamp01(d.age / D.T);
            drive(d.x, D.x0 + D.dir * D.out * (1 - Math.pow(1 - q, 3)), dt);
            drive(d.y, d.y.value + D.vy * dt, dt);
            d.kBase = d.age < 0.04 ? 1.5 : 2.0;
          } else {
            // Назад — пружиной к своей точке у кромки тела. k слияния не растёт:
            // с k 5.25 у брызга в 3–4 px перемычка выходила шире него самого, и
            // капля на миг становилась «Сатурном» с полями по экватору.
            const bc = this.bodyComp(0);
            d.driven = false;
            d.go(bc.cx + D.ax, bc.cy + D.ay);
            d.merging = true;
            d.kBase = 2.0;
            // Подлетел к кромке — тает радиусом (0.09 с без перелёта): натяжение
            // втягивает брызг в тело, а не растягивает его юбкой, и прилипший брызг
            // виден всего 2–3 кадра.
            const q = nearest(d.x.value, d.y.value, bc);
            if (!D.touch && Math.hypot(d.x.value - q.x, d.y.value - q.y) - q.r - d.r.value < 1.5) {
              D.touch = true;
              d.r.response = 0.09; d.r.damping = 1; d.r.set(0);
            }
          }
          if (D.touch && d.r.value < 0.3) {
            this.excite(d, this.bodyComp(0), D.rs);
            d.kill();
            continue;
          }
        } else if (d.role === 'pop') {
          // Осколок: короткий разлёт с торможением и таяние радиусом.
          const D = d.data;
          const q = 1 - Math.pow(1 - clamp01(d.age / 0.15), 3);
          drive(d.x, D.x0 + D.dx * q, dt);
          drive(d.y, D.y0 + D.dy * q, dt);
          if (d.r.value < 0.2) { d.kill(); continue; }
        }
      }

      // ---- компоненты цепочки, k по движению и по долине
      const body = this.bodyComp(ox);
      const comps = [body];
      const U = this.bufD, TT = this.bufT;
      U.fill(0); TT.fill(0);
      let bx0 = Math.min(body.ax - body.ra, body.bx - body.rb), bx1 = Math.max(body.ax + body.ra, body.bx + body.rb);
      let by0 = Math.min(body.ay - body.ra, body.by - body.rb), by1 = Math.max(body.ay + body.ra, body.by + body.rb);
      let kMax = 0;
      // Ширина силуэта вместе с перемычками: тело с модами (на экваторе мода 3
      // даёт +c3 справа и −c3 слева) и прилипшие капли.
      let wc0 = Math.min(body.ax - body.ra, body.bx - body.rb) - (B.c2.value - B.c3.value);
      let wc1 = Math.max(body.ax + body.ra, body.bx + body.rb) + (B.c2.value + B.c3.value);
      for (const d of this.d) {
        if (!d.on) continue;
        const r = Math.max(0, d.r.value);
        if (r < 0.05) continue;
        const vx = d.x.velocity, vy = d.y.velocity;
        const speed = Math.hypot(vx, vy);
        // Мера движения для k: быстро вверх, медленнее вниз — мостик живёт, пока
        // идёт движение, как у Apple (k в движении в 1.3–1.5 раза больше).
        const mT = clamp01(speed / 90);
        d.m += (mT - d.m) * (mT > d.m ? 1 - Math.exp(-dt / 0.05) : 1 - Math.exp(-dt / 0.18));
        // Хвост по скорости: капля вытягивается назад, голова ведёт.
        let hxp = d.x.value, hyp = d.y.value, txp = hxp, typ = hyp, r1 = r, r2 = r;
        const seg = Math.max(0, d.seg.value);
        if (seg > 0.05) {
          hxp = d.x.value - seg; txp = d.x.value + seg;
        } else if (d.role !== 'bead' || d.i !== BEAD) {
          let tl = clamp(speed * (d.role === 'splash' ? 0.025 : 0.04), 0, 1.3 * r);
          if (d.role === 'splash') {
            // Брызг у самой кромки хвоста не тянет: на отрыве хвост смотрел в тело,
            // на возврате — наружу, и конус вместе с мениском читался «крыльями»
            // и юбкой. Хвост — только в свободном полёте.
            const q = nearest(d.x.value, d.y.value, comps[0]);
            const free = Math.hypot(d.x.value - q.x, d.y.value - q.y) - q.r - r;
            tl *= smooth(3, 9, free);
          }
          // Микрокапля тонет вниз, в кромку: хвост по скорости смотрел бы вверх и
          // вместе с галтелью складывался в острый конус над кромкой.
          if (d.role === 'drip') tl *= 1 - smooth(0.78, 0.84, d.u);
          d.tl += (tl - d.tl) * (1 - Math.exp(-dt / 0.05));
          // У кромки хвост брызга и тонущей капли убирается сразу, без запаздывания
          // сглаживания.
          if (d.role === 'splash' || d.role === 'drip') d.tl = Math.min(d.tl, tl);
          if (speed > 5) {
            d.tdx += (-vx / speed - d.tdx) * (1 - Math.exp(-dt / 0.04));
            d.tdy += (-vy / speed - d.tdy) * (1 - Math.exp(-dt / 0.04));
          }
          const dl = Math.hypot(d.tdx, d.tdy) || 1;
          const f = d.tl / (1.3 * r + 1e-3);
          r1 = r * (1 - 0.1 * f);
          r2 = r * mix(1, 0.5, f);
          txp = hxp + (d.tdx / dl) * d.tl;
          typ = hyp + (d.tdy / dl) * d.tl;
        }
        const c = { ax: hxp, ay: hyp, ra: r1, bx: txp, by: typ, rb: r2 };
        let k = d.kBase * (1 + 0.45 * (d.still ? 0 : d.m));
        if (!d.noCap) {
          let cap = Infinity;
          for (const o of comps) {
            const q1 = nearest(hxp, hyp, o);
            const q2 = nearest(txp, typ, o);
            cap = Math.min(cap, valley(hxp, hyp, r1, q1.x, q1.y, q1.r), valley(txp, typ, r2, q2.x, q2.y, q2.r));
          }
          k = Math.min(k, cap + 0.5);
        }
        // Мостик не толще самой капли: калибровка k (5.25–7.6) — для капсулы 56 px, а
        // брызг в 3–4 px с таким k сливался бы юбкой шире себя.
        k = Math.min(k, K_MAX, 1.1 * r + 0.5);
        // Брызг радости держится за тело только тонким мениском (≤ 0.6 его радиуса).
        if (d.role === 'splash') k = Math.min(k, 0.6 * d.data.rs);
        // Микрокапля и тонет с галтелью не шире половины своего радиуса: так она
        // уходит в кромку круглой каплей, а не бугром с вогнутыми боками.
        if (d.role === 'drip') k = Math.min(k, 0.5 * d.data.rm);
        d.k = k;
        // Слилась — исчезла. Моды тела получают толчок вдоль направления слияния.
        if (d.merging) {
          let sunk = false;
          for (const o of comps) if (inside(o, hxp, hyp, r1) && inside(o, txp, typ, r2)) { sunk = true; break; }
          if (sunk) {
            // Толчок мод — только круглому телу: капсулу с текстом не раскачиваем.
            if ((s.stage === 'done' || s.stage === 'polishing') && inside(comps[0], hxp, hyp, r1)) this.excite(d, body, r);
            if (d.role === 'drip') this.lastSink = s.time;
            d.kill();
            continue;
          }
        }
        comps.push(c);
        // Для трассы: капля, чей мостик с телом ещё жив (зазор меньше 2k), —
        // часть силуэта; оторвавшаяся — уже нет.
        {
          const q = nearest(hxp, hyp, body);
          if (Math.hypot(hxp - q.x, hyp - q.y) - q.r - r1 < 2 * k) {
            wc0 = Math.min(wc0, hxp - r1, txp - r2);
            wc1 = Math.max(wc1, hxp + r1, txp + r2);
          }
        }
        const j = d.i * 4;
        U[j] = hxp; U[j + 1] = hyp; U[j + 2] = r1; U[j + 3] = k;
        TT[j] = txp; TT[j + 1] = typ; TT[j + 2] = r2;
        kMax = Math.max(kMax, k);
        bx0 = Math.min(bx0, hxp - r1, txp - r2); bx1 = Math.max(bx1, hxp + r1, txp + r2);
        by0 = Math.min(by0, hyp - r1, typ - r2); by1 = Math.max(by1, hyp + r1, typ + r2);
      }
      this.comps = comps;

      // ---- масштаб материализации 0.96 → 1 вокруг центра холста, как у Линзы
      const sc = 0.96 + 0.04 * m;
      const X = (x) => cx0 + (x - cx0) * sc;
      const Y = (y) => cy0 + (y - cy0) * sc;
      for (let i = 0; i < ND; i++) {
        const j = i * 4;
        if (U[j + 2] <= 0) continue;
        U[j] = X(U[j]); U[j + 1] = Y(U[j + 1]); U[j + 2] *= sc;
        TT[j] = X(TT[j]); TT[j + 1] = Y(TT[j + 1]); TT[j + 2] *= sc;
      }
      const modeAmp = Math.hypot(B.c2.value, B.s2.value) + Math.hypot(B.c3.value, B.s3.value);
      const pad = kMax + modeAmp + 3;
      const box = [X(bx0) - pad, Y(by0) - pad, X(bx1) + pad, Y(by1) + pad];

      // ---- оптика: толщина по размеру, как у Линзы; голос и стадия её не трогают.
      // Кромка сужается вместе с материализацией, A на уходе идёт как m³.
      // Толщина — от тела, без свободных капель: летящая капля ошибки не должна
      // утолщать кромку всей капсулы, а в кадр её исчезновения A — прыгать назад.
      const bodyW = Math.max(body.ax + body.ra, body.bx + body.rb) - Math.min(body.ax - body.ra, body.bx - body.rb);
      const thick = Math.pow(Math.max(Math.max(B.w.value, bodyW) / BASE_W, 1), 0.3);
      const fade = s.shown ? mc : mc * mc;
      const amp = 41 * thick * fade;
      const bevel = 13 * thick * (0.35 + 0.65 * mc);

      // ---- подпись
      let opacity = 0, blur = 0, hide = false;
      let lx = X(B.x.value + ox), ly = Y(B.y.value);
      if (s.stage === 'listening' || s.stage === 'error') {
        const fits = B.w.value >= s.targetW - FIT_SLACK && mc > 0.8 && !this.split;
        if (fits && this.textAt == null) this.textAt = s.time;
        if (this.textAt != null) {
          const k = s.time - this.textAt;
          opacity = smooth(0, 0.22, k) * smooth(0.8, 0.97, mc);
          blur = 2.5 * (1 - smooth(0, 0.26, k));
        }
      } else if (s.stage === 'done') {
        // Галочка проступает, когда капля уже одна и круглая.
        const loose = this.d.some((d) => d.on && d.role !== 'splash');
        const round = !loose && B.w.value < 66;
        if ((round || s.t > 0.45) && this.textAt == null) this.textAt = s.time;
        if (this.textAt != null) {
          const k = s.time - this.textAt;
          opacity = smooth(0, 0.2, k) * smooth(0.8, 0.97, mc);
          blur = 3 * (1 - smooth(0, 0.26, k));
        }
        ly = Y(B.y.value + 0.3 * this.SAG_L() * Math.max(0, B.sag.value));
      } else if (s.stage === 'hidden') {
        opacity = 0;
      } else {
        hide = true;
      }

      // ---- галочка: единственное содержимое «Готово», ей нужен контраст значка
      // (3:1). Зелёный основы #4FDCA6 на тёмном коде даёт ~6:1, а на белом листе и
      // светлых обоях ~1.5. Там галочка тёмно-зелёная #07472F — всё ещё зелёный
      // итога, а сам цвет статуса несёт кромка. Пока галочка едва проступает (или тон
      // ещё не выбран — «Готово» сразу из невидимого), цвет встаёт сразу и на глазах
      // не перекрашивается; пружина — только если плашка переехала на другой фон.
      const done = s.stage === 'done';
      const tone = this.labelEl ? this.labelEl.dataset.tone : '';
      const inkT = done && tone === 'dark' ? 1 : 0;
      if (opacity < 0.35 || !this.toneKnown) this.ink.snap(inkT); else this.ink.set(inkT).step(dt);
      this.toneKnown = !!tone && s.shown;
      const ink = clamp01(this.ink.value);
      const mixc = (a, b) => Math.round(a + (b - a) * ink);
      const iconColor = done ? `rgb(${mixc(79, 7)}, ${mixc(220, 71)}, ${mixc(166, 47)})` : undefined;
      // Значок основы стоит слева в строке подписи (16 px, центр в 8 px от начала);
      // в «Готово» строка — один значок, он в центре капли.
      const iconX = lx - s.contentW / 2 + 8;
      const haloTone = tone === 'dark' ? 1 : tone === 'light' ? -1 : 0;
      // В «Готово» ореола под значком нет: галочка ×1.4 и так держит контраст
      // ядра, а светлое пятно под штрихом делало её не похожей на галочку
      // «Линзы·Света» — рядом это читалось двумя разными «Готово».
      const haloA = hide || done ? 0 : opacity;
      // Свечение: сила — фраза плюс акцент пика, радиус 18–29 px (как у «Линзы·Света»).
      const glowA = this.glowAt ? Math.min(1, 0.64 * this.glowS + 0.36 * acc) : 0;
      const glowR = 18 + 6 * this.glowS + 5 * acc;
      const gAt = this.glowAt || [cx0, cy0];

      if (!ctx.skipping) {
        const gl = ctx.gl;
        gl.useProgram(this.prog.prog);
        // Массивы vec4 основа не ставит (uniform1fv для длины > 4) — ставим сами:
        // значения юниформ живут в программе и доживут до ctx.draw.
        gl.uniform4fv(this.prog.uniforms.uD, U);
        gl.uniform4fv(this.prog.uniforms.uT, TT);
        ctx.draw(this.prog, {
          uBodyA: [X(body.ax), Y(body.ay), body.ra * sc, 0],
          uBodyB: [X(body.bx), Y(body.by), body.rb * sc, 0],
          uBodyC: [X(body.cx), Y(body.cy), body.R * sc, 0],
          uModes: [B.c2.value * sc, B.s2.value * sc, B.c3.value * sc, B.s3.value * sc],
          uBox: box, uMat: m, uBevel: bevel, uAmp: amp, uSpec: 0.2,
          uLight: [Math.cos(LIGHT0), Math.sin(LIGHT0)],
          uStatus: this.status.uniform,
          uIcon: [iconX, ly, haloA, haloTone],
          uGlow: [X(gAt[0]), Y(gAt[1]), glowA, glowR * sc],
        });
      }

      // ---- трасса главного движения
      const bead = this.d[BEAD];
      const tr = this.trace;
      tr.w = X(bx1) - X(bx0);
      // Вздутие бусины над кромкой капсулы: поле тела и бусины в точке кромки над
      // центром бусины, через тот же smin, что в шейдере.
      if (bead.on && s.stage === 'listening') {
        const capX = B.x.value - Math.max(B.w.value - B.h.value, 0) / 2;
        const top = B.y.value - R0;
        const pill = Math.hypot(Math.max(capX - bead.x.value, 0), R0) - R0;
        tr.swell = Math.max(0, -sminJS(pill, Math.abs(top - bead.y.value) - bead.r.value, bead.k));
      } else tr.swell = 0;
      tr.drip = Math.max(0, ...DRIP.map((i) => (this.d[i].on && this.d[i].role === 'drip' ? Math.min(1, this.d[i].u) : 0)));
      tr.dy = B.y.value - cy0;
      tr.wob = Math.hypot(B.c2.value, B.s2.value);

      return {
        cx: lx, cy: ly, labelOpacity: opacity, labelBlur: blur, hideLabel: hide, iconColor,
        // Галочка — всё содержимое «Готово»: ×1.4 (~40% диаметра капли, как у
        // системных галочек Apple и у «Линзы·Света»). Основа масштабирует вокруг
        // cx/cy — центра капли.
        labelScale: done ? 1.4 : 1,
        // w — рамка формы, wc — ширина силуэта с живыми перемычками, swell — горб
        // бусины над кромкой, drip — ход микрокапли,
        // split — фаза деления или бус, gap — зазор между половинками клетки,
        // dy — реакция Дарви, wob — мода n=2, dx — отдача ошибки, ink — доля
        // тёмно-зелёного в галочке, glow — сила свечения голоса.
        trace: { w: tr.w, wc: (wc1 - wc0) * sc, swell: tr.swell, drip: tr.drip, split: tr.split, gap: this.trace.gap || 0, dy: tr.dy, wob: tr.wob, dx: ox, ink, glow: glowA },
      };
    },

    // Толчок собственных колебаний: мода 2 вытягивает вдоль направления слияния,
    // мода 3 вдвое слабее. Толчок — скоростью, а не смещением: форма не прыгает.
    excite(d, body, r) {
      const B = this.body;
      const ang = Math.atan2(d.y.value - body.cy, d.x.value - body.cx);
      // Амплитуда по радиусу капли: бусина 20 px даёт ~3 px, мелкая — ~1.6 px
      // (дыхание для 56 px не больше 3–4 px, RESEARCH.md → «Движение»).
      const w = r / R0;
      const a2 = this.T(4.2, 5.0) * w;
      const a3 = 0.5 * a2;
      const w2 = (2 * Math.PI) / B.c2.response;
      const w3 = (2 * Math.PI) / B.c3.response;
      B.c2.velocity += a2 * w2 * Math.cos(2 * ang);
      B.s2.velocity += a2 * w2 * Math.sin(2 * ang);
      B.c3.velocity += a3 * w3 * Math.cos(3 * ang);
      B.s3.velocity += a3 * w3 * Math.sin(3 * ang);
    },
  });

})();
