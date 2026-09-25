// «Сияние»: прозрачная стеклянная капсула и свет Apple Intelligence, который живёт
// только в тонкой полосе внутри кромки. Форма не меняет топологию — вся жизнь в свете.
(function () {
  const SHAPE = `
uniform vec2 uCenter; uniform vec2 uSize;
float shape(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
`;

  const MAIN = `
uniform float uMat;      // материализация линзы 0..1
uniform float uBand;     // ширина полосы света, px
uniform float uGlow;     // яркость света
uniform float uFront;    // фронт рождения: сколько px дуги от левого торца уже залито
uniform float uBirth;    // вспышка у иконки в момент рождения
uniform float uPhase;    // накопленная фаза течения палитры, обороты
uniform float uCool;     // сдвиг палитры к фиолетово-синему (причёсываю)
uniform float uGreen;    // стягивание в зелёный (готово)
uniform float uRed;      // покраснение (ошибка)
uniform float uDisp;     // лёгкое расхождение каналов в кромке
uniform vec4 uPulseX;    // положения слоговых импульсов вдоль дуги, px
uniform vec4 uPulseA;    // их сила
uniform vec4 uLabel;     // прямоугольник подписи: центр xy, полуразмер zw, px
uniform float uLabelFrost; // доразмытие фона под подписью, px

const vec3 C0 = vec3(1.000, 0.624, 0.263);  // #FF9F43
const vec3 C1 = vec3(1.000, 0.310, 0.639);  // #FF4FA3
const vec3 C2 = vec3(0.557, 0.424, 1.000);  // #8E6CFF
const vec3 C3 = vec3(0.247, 0.635, 1.000);  // #3FA2FF
const vec3 C4 = vec3(0.216, 0.902, 0.847);  // #37E6D8
const vec3 GREEN = vec3(0.310, 0.863, 0.651); // #4FDCA6
const vec3 RED = vec3(1.000, 0.420, 0.455);   // #FF6B74

// Палитра туда-обратно (оранжевый → бирюзовый → оранжевый): прямой переход
// бирюзовый→оранжевый проходит через грязно-серый, поэтому кольца нет.
vec3 warmPal(float x) {
  float y = 4.0 - abs(mod(x, 8.0) - 4.0);
  float f = smoothstep(0.0, 1.0, fract(y));
  if (y < 1.0) return mix(C0, C1, f);
  if (y < 2.0) return mix(C1, C2, f);
  if (y < 3.0) return mix(C2, C3, f);
  return mix(C3, C4, f);
}
// Холодная палитра причёсывания: фиолетовый ↔ синий, розовый едва заметен.
vec3 coolPal(float x) {
  float y = 0.5 + 0.5 * sin(x * 1.5708);
  vec3 c = mix(C2, C3, smoothstep(0.1, 0.9, y));
  return mix(c, vec3(0.44, 0.47, 1.0), 0.35 * (1.0 - abs(2.0 * y - 1.0)));
}

// Дуга капсулы от самой левой точки: x — px по кромке (сверху и снизу одинаково,
// 0 у левого торца, halfL у правого), y — сторона (+1 верх, −1 низ). Именно дуга,
// а не atan2 от центра: иначе на длинных прямых цвет растягивается.
vec2 arcOf(vec2 p, out float halfL) {
  vec2 q = p - uCenter;
  float r = uSize.y * 0.5;
  float a = max(uSize.x * 0.5 - r, 0.0);
  halfL = 3.14159265 * r + 2.0 * a;
  float ay = abs(q.y);
  float s;
  if (q.x < -a) s = r * atan(ay, -(q.x + a));
  else if (q.x > a) s = r * 1.5707963 + 2.0 * a + r * atan(q.x - a, ay);
  else s = r * 1.5707963 + (q.x + a);
  return vec2(s, q.y <= 0.0 ? 1.0 : -1.0);
}

void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  float d0 = shape(p);
  // Дальние пиксели — одна выборка фона: тень стекла дальше 44 px неразличима.
  if (d0 > 44.0 || uMat < 0.002) { outColor = vec4(bg, 1.0); return; }

  Glass g = defaultGlass();
  g.materialize = uMat;
  // Под подписью фон доразмыт: стекло вокруг остаётся прозрачным, а буквы фона
  // того же кегля не спорят с буквами плашки. Стоит столько же: blur идёт по mip.
  if (uLabelFrost > 0.0) {
    vec2 lq = abs(p - uLabel.xy) - uLabel.zw;
    float ld = length(max(lq, 0.0)) + min(max(lq.x, lq.y), 0.0);
    g.frost = mix(g.frost, max(g.frost, uLabelFrost), 1.0 - smoothstep(-2.0, 10.0, ld));
  }
  // Расхождение каналов нужно только в кромке: в плоской середине оно втрое дороже и не видно.
  g.dispersion = -d0 < g.bevel + 1.0 ? uDisp : 0.0;
  vec4 gc = liquidGlass(p, g, bg);
  vec3 col = gc.rgb;

  float ins = -d0;
  float reach = uBand * 1.7 + 6.0;
  if (gc.a > 0.0 && ins < reach && uGlow + uBirth > 0.003) {
    float halfL;
    vec2 as = arcOf(p, halfL);
    float s = as.x;
    // Полный обход 0..1 по часовой стрелке — для палитры и шума без шва.
    float theta = (as.y > 0.0 ? s : 2.0 * halfL - s) / (2.0 * halfL);
    float ang = theta * 6.2831853;
    float R = halfL / 3.14159265;
    // Шум на окружности длины периметра: шва нет, а уход вглубь стекла уменьшает
    // радиус — волокна света вытягиваются внутрь, как шёлк.
    vec2 np = vec2(cos(ang), sin(ang)) * (R - ins * 0.9) / 30.0;
    // Ширину ведёт шум пониже частотой и с узким разбросом: край дышит длинными
    // волнами, а не рвётся комками. Волокна шёлка живут в яркости (n2) и цвете.
    float n1 = fbm(np / 1.6 + vec2(uTime * 0.07, -uTime * 0.05));
    float n2 = fbm(np * 1.8 + vec2(-uTime * 0.14, uTime * 0.11) + 7.3);

    // Слоговые импульсы бегут от левого торца одновременно по верху и низу.
    float pulse = 0.0;
    for (int i = 0; i < 4; i++) {
      float z = (s - uPulseX[i]) / 34.0;
      pulse += uPulseA[i] * exp(-z * z);
    }
    float icon = exp(-s / 70.0);                       // у иконки микрофона свет гуще
    float front = smoothstep(uFront + 6.0, uFront - 70.0, s);
    float birth = uBirth * exp(-s / 80.0);

    float width = uBand * (0.8 + 0.4 * n1) * (1.0 + 0.8 * pulse + 1.0 * birth + 0.25 * icon);
    float prof = pow(1.0 - smoothstep(0.0, width, ins), 1.7);
    float line = 1.0 - smoothstep(0.0, 2.0, ins);    // тонкая яркая жилка у самой кромки
    // Вспышка у иконки загорается раньше фронта: свет рождается там и уже потом течёт.
    float lit = max(front, min(1.0, uBirth * 3.0) * exp(-s / 60.0));
    float I = (0.74 * prof + 0.26 * line) * lit;
    float bright = uGlow * (0.95 + 0.5 * icon) * (0.68 + 0.64 * n2) + 1.0 * pulse + 2.4 * birth;

    float x = theta * 8.0 + uPhase * 8.0 + (n1 - 0.5) * 2.6;
    vec3 lc = mix(warmPal(x), coolPal(x + n2), uCool);
    // Зелёный и красный не заливают разом, а стягиваются пятнами по шуму.
    float gm = smoothstep(0.0, 1.0, clamp(uGreen * 1.5 - 0.5 * n2, 0.0, 1.0));
    lc = mix(lc, GREEN, gm);
    float rm = smoothstep(0.0, 1.0, clamp(uRed * 1.5 - 0.5 * n2, 0.0, 1.0));
    lc = mix(lc, RED, rm);

    // Свет полупрозрачный: часть — подмес цвета (видно на белом), часть — сложение
    // (светится на тёмном). Потолок 0.9 — фон всегда проглядывает.
    // Мягкий потолок вместо обрезки: у кромки свет не упирается в предел, и импульс
    // слога заметен даже на громкой речи.
    // На светлом фоне сложение только белит — там работает подмес, и его больше,
    // иначе свет выцветает в пастель; на тёмном — свечение.
    float lum = luma(col);
    float dark = 1.0 - smoothstep(0.35, 0.9, lum);
    float light = smoothstep(0.6, 0.8, lum);
    float a = min(0.9, 0.9 * (1.0 - exp(-1.5 * I * bright)) * (1.0 + 0.3 * light)) * gc.a;
    col = mix(col, lc, a * mix(mix(0.72, 0.9, light), 0.58, dark)) + lc * a * 0.34 * dark;
  }
  outColor = vec4(col, 1.0);
}
`;

  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const smooth = (a, b, v) => { const t = clamp01((v - a) / (b - a)); return t * t * (3 - 2 * t); };

  LG.register({
    id: 'aura',
    setup(ctx) {
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + SHAPE + ctx.glsl.glass + MAIN);
      this.w = new ctx.Spring(260, 0.5, 0.85);        // ширина под текст: snappy
      this.scale = new ctx.Spring(0.94, 0.42, 0.78);  // лёгкий рост при материализации
      this.mat = new ctx.Spring(0, 0.5, 0.86);
      this.band = new ctx.Spring(0, 0.22, 0.9);
      this.glow = new ctx.Spring(0, 0.14, 1.0);
      this.front = new ctx.Spring(-40, 0.9, 1.0);
      this.speed = new ctx.Spring(0.035, 0.8, 1.0);
      this.cool = new ctx.Spring(0, 0.6, 1.0);
      // Перекраска в итог быстрая: полоса успевает сменить цвет, пока ещё горит.
      this.green = new ctx.Spring(0, 0.12, 1.0);
      this.red = new ctx.Spring(0, 0.12, 1.0);
      this.shake = new ctx.Spring(0, 0.2, 0.28);
      this.phase = Math.random();
      this.slow = 0;          // медленная огибающая голоса: для ширины полосы
      this.pulses = [];
      this.lastRaw = 0;
      this.rising = false;
      this.sinceOnset = 1;
      this.stage = 'hidden';
      this.flashT = -1;
      this.birthT = -1;
      this.sinceBirth = 9;
      this.glowOut = 0;       // яркость, ушедшая в шейдер прошлым кадром
      this.held = 0;          // её уровень на входе в итог: свет не гаснет перед вспышкой
    },

    enter(stage, s) {
      const fromHidden = this.stage === 'hidden' || this.mat.value < 0.25;
      if (stage !== 'hidden' && fromHidden) {
        // Рождение: фронт света заново от левого торца, линза с нуля.
        this.front.snap(-40);
        this.birthT = 0;
        this.sinceBirth = 0;
        this.w.snap(s.targetW - 26);
        this.scale.snap(0.94);
        this.green.snap(0);
        this.red.snap(0);
        this.cool.snap(0);
        this.pulses = [];
        this.phase = 0;   // у левого торца рождение всегда тёплое, оранжевое
      }
      if (stage === 'listening') { this.green.snap(0); this.red.snap(0); }
      if (stage === 'done' || stage === 'error') {
        // Та же полоса перекрашивается, вспыхивает и уходит — без провала «выкл → вкл».
        this.flashT = 0;
        this.held = this.glowOut;
        this.glow.snap(0);
      }
      if (stage === 'error') this.shake.velocity = -170;  // одно лёгкое встряхивание
      this.stage = stage;
    },

    frame(ctx, s) {
      const dt = s.dt;
      if (s.stage !== this.stage) this.enter(s.stage, s);
      const st = s.stage;
      const t = s.t;

      // Медленная огибающая для толщины: атака 70 мс, спад 320 мс — полоса дышит
      // фразами, а не дрожит на каждом слоге (яркость берёт быструю s.level).
      const lvl = st === 'listening' ? s.level : 0;
      this.slow += (lvl - this.slow) * (1 - Math.exp(-dt / (lvl > this.slow ? 0.07 : 0.32)));

      // Слоги: начало роста сырого уровня после спада — новый мягкий импульс.
      this.sinceOnset += dt;
      if (st === 'listening') {
        if (s.raw > this.lastRaw + 1e-4) {
          if (!this.rising && this.sinceOnset > 0.16 && s.raw > 0.12) {
            this.pulses.push({ age: 0, amp: 0.35 + 0.6 * Math.min(1, s.raw + 0.25) });
            if (this.pulses.length > 4) this.pulses.shift();
            this.sinceOnset = 0;
          }
          this.rising = true;
        } else if (s.raw < this.lastRaw - 1e-4 || s.raw === 0) this.rising = false;
      }
      this.lastRaw = s.raw;

      const breath = 0.5 + 0.5 * Math.sin((2 * Math.PI * t) / 2.6);
      let flash = 0, held = 0;
      if (this.flashT >= 0) {
        this.flashT += dt;
        const ft = this.flashT;
        // Прежний свет держится 150 мс, пока пружина перекрашивает его, затем тает;
        // вспышка растёт с 100 мс поверх ещё горящей полосы.
        held = this.held * (ft < 0.15 ? 1 : Math.exp(-(ft - 0.15) / 0.35));
        const fz = Math.max(0, ft - 0.1);
        flash = (1 - Math.exp(-fz / 0.05)) * Math.exp(-fz / 0.36) * 1.5;
        if (ft > 2.5) this.flashT = -1;
      }
      let birth = 0;
      this.sinceBirth += dt;
      if (this.birthT >= 0) {
        this.birthT += dt;
        birth = (1 - Math.exp(-this.birthT / 0.04)) * Math.exp(-this.birthT / 0.26);
        if (this.birthT > 1.5) this.birthT = -1;
      }

      let glowT = 0, bandT = 0, speedT = 0.035;
      if (st === 'listening') { glowT = 0.35 + 0.65 * s.level; bandT = 4 + 10 * this.slow; speedT = 0.035; }
      // Пол ширины 5–6 px: тоньше полоса над белым рвётся в цветную нить.
      else if (st === 'transcribing') { glowT = 0.42 + 0.2 * breath; bandT = 5 + 1.6 * breath; speedT = 0.03; }
      else if (st === 'polishing') { glowT = 0.47 + 0.2 * breath; bandT = 5.5 + 1.8 * breath; speedT = 0.075; }
      else if (st === 'done' || st === 'error') { glowT = 0; bandT = 6 + 5 * Math.min(1, flash); speedT = 0.05; }
      this.glow.set(glowT).step(dt);
      this.band.set(Math.max(bandT, 0.5)).step(dt);
      this.phase += this.speed.set(speedT).step(dt) * dt;
      this.cool.set(st === 'polishing' ? 1 : st === 'done' || st === 'error' ? this.cool.target : 0).step(dt);
      this.green.set(st === 'done' ? 1 : 0).step(dt);
      this.red.set(st === 'error' ? 1 : 0).step(dt);

      this.w.set(s.targetW).step(dt);
      const mat = clamp01(this.mat.set(s.shown ? 1 : 0).step(dt));
      const sc = this.scale.set(s.shown ? 1 : 0.95).step(dt);
      const dx = this.shake.set(0).step(dt);
      const w = Math.max(56, this.w.value) * sc;
      const h = 56 * sc;
      const cx = ctx.W / 2 + dx;
      const cy = ctx.H / 2;
      const halfL = Math.PI * h / 2 + 2 * Math.max(0, w / 2 - h / 2);
      // Фронт ведёт пружина только пока идёт рождение; дальше он просто за правым
      // торцом, иначе растущая под результат капсула обгоняет его и справа тёмный срез.
      if (this.birthT >= 0 && this.birthT < 0.9) this.front.set(halfL + 70).step(dt);
      else if (s.shown) this.front.snap(halfL + 200);

      const px = [0, 0, 0, 0], pa = [0, 0, 0, 0];
      this.pulses = this.pulses.filter((p) => (p.age += dt) < 1.0);
      this.pulses.forEach((p, i) => {
        // 600 px/с: при 5 слогах в секунду импульсы идут через ~120 px и читаются
        // по отдельности, а не сливаются в сплошную полосу.
        px[i] = -10 + p.age * 600;
        pa[i] = p.amp * Math.exp(-p.age * 2.6) * (1 - Math.exp(-p.age / 0.03));
      });

      const glow = st === 'done' || st === 'error' ? Math.max(held, flash) : this.glow.value * mat + flash;
      this.glowOut = glow;

      // Текст виден, только когда капсула уже вмещает его: при росте под длинный
      // результат он проявляется, как только ширина догнала, — вылезти не может.
      // На рождении подпись ждёт ~300 мс: сначала свет, потом слова.
      const fit = smooth(s.targetW - 44, s.targetW - 8, w);
      const op = smooth(0.3, 0.85, mat) * fit * smooth(0.25, 0.45, this.sinceBirth);
      const final = st === 'done' || st === 'error';
      ctx.draw(this.prog, {
        uCenter: [cx, cy], uSize: [w, h], uMat: mat,
        uBand: this.band.value, uGlow: Math.max(0, glow), uFront: this.front.value,
        // Вспышка рождения не ждёт линзу: свет появляется первым.
        uBirth: birth * Math.sqrt(mat), uPhase: this.phase,
        uCool: clamp01(this.cool.value), uGreen: clamp01(this.green.value), uRed: clamp01(this.red.value),
        uDisp: 0.04, uPulseX: px, uPulseA: pa,
        uLabel: [cx, cy, Math.max(0, Math.min(s.targetW, w) / 2 - 26), 9],
        uLabelFrost: op * (final ? 8 : 6),
      });
      return { cx, cy, labelOpacity: op, labelBlur: (1 - op) * 3 };
    },
  });
})();
