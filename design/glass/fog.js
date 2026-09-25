// «Запотевание»: состояние плашки — это степень запотевания стекла.
// Форма почти неподвижна; меняется прозрачность материала: чистая линза,
// облачка дыхания, матовый туман, протирка, красноватая вспышка ошибки.
(function () {
  'use strict';

  const PUFFS = 8;          // одновременно живущих облачков дыхания (5 слогов/с × 1.2 с + запас)
  const PUFF_LIFE = 1.25;   // с: облачко испаряется от краёв к центру за это время
  const FONT = '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif';

  const FRAG = `
uniform vec2 uCenter;
uniform vec2 uSize;
uniform float uMat;        // материализация 0..1 (клампится)
uniform float uAmp;        // амплитуда линзы: перелёт пружины появления уходит сюда
uniform vec4 uPuff[${PUFFS}];   // x, y, радиус, порог испарения
uniform float uPuffA[${PUFFS}]; // плотность облачка, 0 — слот пуст
uniform float uFront;      // туман от краёв к центру 0..1
uniform float uBreath;     // 0..1: насколько плотность тумана «дышит» (ожидание)
uniform float uWipe;       // x линии протирки, CSS px; далеко слева — протирки нет
uniform float uWipeGlow;
uniform float uStreakFrom; // мокрые следы видны левее этой линии (позади протирки)
uniform float uStreakDry;  // 0..1 высыхание следов
uniform float uStreakVis;
uniform vec2 uStreakX;     // границы капсулы на момент протирки: следы не выходят за них
uniform float uErr;        // вспышка тумана ошибки 0..1
uniform float uErrThr;     // порог испарения тумана ошибки
uniform float uFlash;      // короткий подъём яркости на вспышке
uniform vec3 uErrColor;

float shape(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
`;

  const MAIN = `
// Поле запотевания. Шум привязан к стеклу, а не к фону: у настоящего стекла
// центры конденсации одни и те же, поэтому каждое облачко ложится тем же узором.
float fogField(vec2 p, out float errShare, out float ringGate, out float frontEdge) {
  vec2 lp = p - uCenter;
  float n1 = fbm(lp * 0.034 + vec2(uTime * 0.12, 0.0));
  vec2 q = lp / (uSize * 0.5);
  float rho = length(q);

  // Дыхание: профиль 1 в центре облачка → 0 на краю, край рваный от шума.
  // Порог испарения растёт с возрастом — сначала пропадают края.
  // Второй, более крупный шум: у каждого облачка своя смесь двух узоров,
  // чтобы выдохи не ложились одним и тем же штампом.
  float n2 = vnoise(lp * 0.05 + 13.0) * 0.6 + vnoise(lp * 0.12 + 5.0) * 0.4;
  float keep = 1.0;
  ringGate = 0.0;
  for (int i = 0; i < ${PUFFS}; i++) {
    float a = uPuffA[i];
    if (a <= 0.0) continue;
    vec4 P = uPuff[i];
    float nn = mix(n1, n2, fract(float(i) * 0.618 + 0.2));
    float d = length(p - P.xy) / max(P.z, 1.0);
    float prof = 1.0 - d * (0.68 + 0.7 * nn);
    keep *= 1.0 - a * smoothstep(P.w, P.w + 0.32, prof);
    // Край высыхания рисуем только у облачка, в котором ещё есть плотное ядро:
    // у почти испарившегося контур остался бы кольцом без пятна внутри.
    float peak = a * smoothstep(P.w, P.w + 0.32, 1.0);
    ringGate = max(ringGate, smoothstep(0.15, 0.4, peak) * (1.0 - smoothstep(1.3, 1.9, d)));
  }
  float fPuff = 1.0 - keep;

  // Фронт от краёв: эллиптическая глубина + шум, порог сдвигается к центру.
  float fFront = 0.0;
  frontEdge = 0.0;
  if (uFront > 0.001) {
    // Площадь эллипса растёт как квадрат радиуса: корень делает покрытие
    // площади примерно пропорциональным uFront, фронт ползёт равномерно.
    float thr = 1.05 - 1.5 * (1.0 - sqrt(max(1.0 - uFront, 0.0)));
    float sp = rho + (n1 - 0.5) * 0.35;
    // Широкий мягкий край и умеренный шум: островок чистого стекла
    // проясняется, а не выглядит рваной дырой.
    fFront = smoothstep(thr - 0.15, thr + 0.3, sp) * min(1.0, uFront * 4.0) * 0.96;
    // Своя светотень кромки фронта: на гладком фоне размытие ничего не меняет,
    // и без неё наползание тумана не видно.
    frontEdge = (1.0 - smoothstep(0.0, 0.1, abs(sp - thr - 0.02))) * min(1.0, uFront * 4.0);
    // Середина тоже понемногу мутнеет, иначе последний чистый островок
    // смотрится грязным пятном на фоне уже матового стекла.
    fFront = max(fFront, uFront * uFront * uFront * 0.9);
    // Долгое ожидание не должно застывать: плотность медленно «дышит»
    // пятнами, как испарина, которую то подсушивает, то снова наносит.
    fFront *= 1.0 - uBreath * (0.08 - 0.08 * sin(uTime * 1.6 + n1 * 6.0));
  }

  // Ошибка: весь туман разом, испаряется крупными пятнами, центр держится дольше краёв.
  float fErr = 0.0;
  if (uErr > 0.001) {
    float big = vnoise(lp * 0.02 + 3.0) * 0.7 + n1 * 0.3;
    float field = big * 0.6 + (1.0 - clamp(rho, 0.0, 1.0)) * 0.4;
    // Потолок 0.8: даже во вспышке сквозь стекло угадывается фон.
    fErr = 0.8 * uErr * smoothstep(uErrThr - 0.05, uErrThr + 0.3, field);
  }

  float f = 1.0 - (1.0 - fPuff) * (1.0 - fFront) * (1.0 - fErr);
  errShare = fErr / max(f, 1e-3);
  // Протирка: всё, что осталось позади полосы, чистое.
  float xw = p.x + 0.32 * (p.y - uCenter.y) + (n1 - 0.5) * 8.0;
  float wiped = smoothstep(uWipe - 2.0, uWipe + 10.0, xw);
  f *= wiped;
  frontEdge *= wiped;
  return clamp(f, 0.0, 1.0);
}

// Мокрые следы ладони: пара почти горизонтальных полос вдоль движения протирки.
// Вода прозрачна, поэтому это не туман, а тонкая линза: 0..1 толщина плёнки.
// Сохнут от краёв к середине — порог растёт со временем.
float wetField(vec2 p) {
  vec2 lp = p - uCenter;
  float n = vnoise(lp * 0.07 + 21.0);
  float xw = p.x + 0.32 * (p.y - uCenter.y) + (n - 0.5) * 8.0;
  float behind = 1.0 - smoothstep(uStreakFrom - 26.0, uStreakFrom - 4.0, xw);
  // Следы лежат только там, где стекло было на момент протирки.
  behind *= smoothstep(uStreakX.x + 8.0, uStreakX.x + 24.0, p.x) * (1.0 - smoothstep(uStreakX.y - 24.0, uStreakX.y - 8.0, p.x));
  if (behind <= 0.0) return 0.0;
  float sy = lp.y - 0.09 * lp.x;
  float s1 = exp(-pow((sy + 10.0) / 4.5, 2.0)) * (0.55 + 0.45 * vnoise(vec2(p.x * 0.045, 3.0)));
  float s2 = exp(-pow((sy - 9.0) / 3.5, 2.0)) * (0.45 + 0.55 * vnoise(vec2(p.x * 0.06, 9.0)));
  float sp = max(s1, s2) * (0.75 + 0.25 * n);
  float thr = -0.15 + 1.15 * uStreakDry;
  return smoothstep(thr, thr + 0.3, sp) * behind * uStreakVis;
}

// Капли конденсата: редкие точки-линзы только в плотном тумане.
// x — диск с учётом видимости, y — сторона: +1 сверху (блик), −1 снизу (тень).
// Крупная редкая сетка и разный размер: частая мелкая читалась как шум сенсора.
vec2 condensate(vec2 lp, float f) {
  float vis = smoothstep(0.75, 0.92, f);
  if (vis <= 0.0) return vec2(0.0);
  vec2 cell = floor(lp / 10.0);
  float h = hash21(cell);
  if (h > 0.2) return vec2(0.0);
  vec2 c = (cell + 0.25 + 0.5 * vec2(hash21(cell + 3.1), hash21(cell + 7.7))) * 10.0;
  float r = 0.6 + 1.0 * hash21(cell + 11.3);
  vec2 d = lp - c;
  float disk = 1.0 - smoothstep(r - 0.5, r + 0.5, length(d));
  float side = clamp(-d.y / max(r, 0.6), -1.0, 1.0);
  return vec2(disk * vis, side);
}

void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  float sd = shape(p);
  // Далеко от формы нет ни стекла, ни заметной тени: одна выборка фона.
  if (sd > 90.0 || uMat <= 0.0) { outColor = vec4(bg, 1.0); return; }

  float m = clamp(uMat, 0.0, 1.0);
  float errShare = 0.0, ringGate = 0.0, frontEdge = 0.0;
  float fe = sd < 1.5 ? fogField(p, errShare, ringGate, frontEdge) * m : 0.0;
  // Градиент поля до мелкой пятнистости: по нему рисуется «край высыхания».
  float grad = length(vec2(dFdx(fe), dFdy(fe))) * uDpr;
  vec2 lp = p - uCenter;
  // Туман не бывает ровным: мелкая пятнистость плотности.
  float f = fe * (0.86 + 0.14 * vnoise(lp * 0.16 + 7.0));

  Glass g = defaultGlass();
  g.materialize = m;
  g.amplitude = uAmp;
  // Туман — это рассеяние в тонком слое: радиус размытия растёт с плотностью
  // (диск r ≈ 2σ, до σ ≈ 13).
  // Туман ошибки размывает слабее: это вспышка поверх того же стекла,
  // и сквозь неё должен угадываться текст под плашкой.
  g.frost = mix(2.4, 26.0, pow(f * (1.0 - 0.45 * errShare), 0.85));
  // Подъём яркости базового стекла не складывается с туманом: туман сам
  // осветляет через screen ниже, иначе на тёмном фоне выходит серый пластик.
  g.lift = 0.086 * (1.0 - f);
  vec4 glass = liquidGlass(p, g, bg);
  vec3 col = glass.rgb;
  // Мокрые следы: плёнка воды — прозрачная линза. Сдвигает фон на свой уклон
  // (≤1.5 px) и почти не размывает; блик/тень по уклону. Только вдали от кромки,
  // где стекло своё смещение уже не даёт, — там цвет стекла пересобирается 1:1.
  if (uStreakVis > 0.001 && sd < -8.0) {
    float w0 = wetField(p);
    float wx = wetField(p + vec2(1.5, 0.0)) - wetField(p - vec2(1.5, 0.0));
    float wy = wetField(p + vec2(0.0, 1.5)) - wetField(p - vec2(0.0, 1.5));
    vec2 wg = vec2(wx, wy) / 3.0;
    if (w0 > 0.002 || dot(wg, wg) > 1e-6) {
      vec2 off = wg * 9.0;
      float ol = length(off);
      off *= min(1.0, 1.5 / max(ol, 1e-4)) * uRefraction;
      vec3 wetCol = sceneBlur(p + off, g.frost * m + 1.5 * w0) * mix(1.0, g.gain, m) + g.lift * m;
      float wm = clamp(w0 * 3.0 + ol * 2.0, 0.0, 1.0) * smoothstep(10.0, 14.0, -sd);
      col = mix(col, wetCol, wm);
      // Свет сверху слева: склон плёнки к свету чуть светлее, от света — темнее.
      col += clamp(dot(wg, vec2(0.45, 0.9)) * 6.0, -1.0, 1.0) * 0.03 * m;
    }
  }
  if (glass.a > 0.0) {
    vec2 q = lp / (uSize * 0.5);
    float inside = clamp(-sd / 3.0, 0.0, 1.0);
    // На светлом фоне размытие и осветление ничего не меняют (белое остаётся
    // белым), поэтому туман там — холодная серая дымка, а на тёмном — screen.
    float light = smoothstep(0.62, 0.9, luma(col));
    vec3 lifted = 1.0 - (1.0 - col) * (1.0 - 0.1 * f * (1.0 - light));
    col = mix(lifted, lifted * 0.9 + vec3(0.015, 0.025, 0.045), f * light);
    // Холодная матовость чуть сильнее на тёмном и цветном: там туман
    // иначе держится только на размытии, а гладкий градиент размытием не меняется.
    col = mix(col, vec3(0.94, 0.96, 1.0), mix(0.035, 0.02, light) * f);
    // Рассеяние: плотный туман чуть светится со стороны света (слева сверху).
    col += f * 0.025 * clamp(0.6 - 0.35 * q.x - 0.55 * q.y, 0.0, 1.0) * (1.0 - light);
    // Кромка наползающего тумана: узкая светлая полоса, видна и на гладком фоне.
    col += 0.035 * frontEdge * m * (1.0 - light) * inside;
    // Ошибка красит сам размытый фон, а не кладёт молочно-розовый слой:
    // фон остаётся виден, просто «покраснел» от вспышки. На белом тот же
    // множитель давал сплошную розовую таблетку — там оттенок вдвое слабее.
    float e = errShare * f;
    vec3 errMul = mix(vec3(1.0, 0.72, 0.74), vec3(1.0, 0.91, 0.92), light);
    col = mix(col, col * errMul + 0.04 * uErrColor * (1.0 - light), e * 0.7);
    col += uFlash * e * (1.0 - light);
    // Край высыхания облачка: мягкая линия 2–3 px на уровне 0.1 — граница пятна
    // видна на однородном фоне. Слабая: иначе читается нарисованным контуром.
    // В «Распознаю» гаснет: там главное — фронт.
    float iso = abs(fe - 0.1) / max(grad, 1e-4);
    float ring = (1.0 - smoothstep(0.0, 1.0, iso * 0.4)) * clamp(-sd / 4.0 - 0.5, 0.0, 1.0)
               * step(0.004, grad) * ringGate * (1.0 - clamp(uFront, 0.0, 1.0));
    col += ring * mix(0.012, -0.035, light);
    // Конденсат: на тёмном — светлые точки, на светлом — тёмные с бликом сверху.
    vec2 dots = condensate(lp, f) * vec2(glass.a, 1.0);
    float up = max(dots.y, 0.0), dn = max(-dots.y, 0.0);
    col += dots.x * mix(up * 0.05 - dn * 0.04, up * 0.04 - 0.07 * (1.0 - 0.6 * up), light);
    // Полоса протирки: узкий мягкий блик на линии, цвет — от самого контента;
    // на светлом фоне блика не видно, поэтому за полосой — тонкая мокрая кромка.
    if (uWipeGlow > 0.0) {
      float x = p.x + 0.32 * (p.y - uCenter.y) - uWipe;
      float band = exp(-x * x / 30.0) + 0.35 * exp(-x * x / 260.0);
      col = mix(col, 1.0 - (1.0 - col) * 0.55, band * uWipeGlow * inside * 0.55 * (1.0 - 0.7 * light));
      float wet = exp(-(x + 6.0) * (x + 6.0) / 1.6);
      col -= wet * 0.08 * uWipeGlow * inside * light;
    }
  }
  outColor = vec4(col, 1.0);
}
`;

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  // Ширина содержимого подписи: нужна точка иконки микрофона, откуда идёт дыхание.
  const measure = document.createElement('canvas').getContext('2d');
  function contentWidth(text) {
    measure.font = `600 14px ${FONT}`;
    let w = 16 + 10 + measure.measureText(text.title).width + 10;
    measure.font = `400 13px ${FONT}`;
    w += measure.measureText(text.detail || '').width;
    return w;
  }

  LG.register({
    id: 'fog',
    setup(ctx) {
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + FRAG + ctx.glsl.glass + MAIN);
      // Ширина — snappy (0.5, 0.85) по ТЗ: без заметного перелёта, но живо.
      this.w = new ctx.Spring(210, 0.5, 0.85);
      // Появление — рост линзы с лёгким перелётом по амплитуде.
      this.mat = new ctx.Spring(0, 0.42, 0.7);
      // Фронт тумана: критическое демпфирование — наползает, не отскакивая.
      this.front = new ctx.Spring(0, 1.4, 1.0);
      // Протирка чуть медленнее: это единственное движение стадии, пусть читается.
      this.wipe = new ctx.Spring(0, 1.5, 1.0);
      this.streakVis = new ctx.Spring(0, 0.12, 1.0);
      this.streakX = [0, 0];
      this.streakT = 0;
      this.breath = new ctx.Spring(0, 0.8, 1.0);
      this.shake = new ctx.Spring(0, 0.2, 0.3);
      this.puffs = Array.from({ length: PUFFS }, () => ({ x: 0, y: 0, age: 99, str: 0 }));
      this.puffBuf = new Float32Array(PUFFS * 4);
      this.puffA = new Float32Array(PUFFS);
      this.stage = 'hidden';
      this.prevRaw = 0;
      this.rising = false;
      this.lastPuff = -1;
      this.wiping = false;
      this.wipeDelay = 0;
      this.errT = 99;
      this.streakFrom = 1e5;
      this.seed = 3;
    },

    rand() {
      this.seed = (this.seed * 16807) % 2147483647;
      return (this.seed - 1) / 2147483646;
    },

    enter(stage, s, left, right) {
      if (stage === 'transcribing') {
        // Цель фронта — асимптота по времени (см. frame), пружина только сглаживает.
        this.front.response = 0.3;
      } else if (stage === 'polishing') {
        // Если пришли не из «Распознаю», стекло сначала досуществует матовым.
        this.front.response = 0.3;
        this.front.set(1);
        this.wiping = true;
        this.wipeDelay = 0.14;
        this.streakT = 0;
        this.wipe.snap(left - 40);
        this.streakX = [left, right];
      } else if (stage === 'error') {
        this.errT = 0;
        this.front.response = 0.6;
        this.front.set(0);
        this.shake.velocity = 150;   // ≈ 5 px, три затухающих качания
      } else {
        this.front.response = 0.35;
        this.front.set(0);
        // Протирка, почти ушедшая за край, считается законченной: иначе туман
        // перед полосой на миг вернулся бы на всё стекло в «Готово».
        if (this.wiping && this.wipe.value > right - 40) {
          this.wiping = false;
          this.front.snap(0);
        }
      }
      if (stage === 'error' || stage === 'hidden' || stage === 'listening') {
        this.wiping = false;
      }
    },

    frame(ctx, s) {
      const dt = s.dt;
      const cx0 = ctx.W / 2;
      const cy = ctx.H / 2;
      const mRaw = this.mat.set(s.shown ? 1 : 0).step(dt);
      const m = clamp(mRaw, 0, 1);
      const w = this.w.set(s.targetW).step(dt);
      const shakeX = this.shake.step(dt);
      const cx = cx0 + shakeX;
      // Появление: форма чуть подрастает вместе с линзой, но главное — оптика.
      const grow = 0.92 + 0.08 * m;
      const pw = w * grow;
      const ph = 56 * grow;
      const left = cx - pw / 2;
      const right = cx + pw / 2;

      if (s.stage !== this.stage) {
        this.enter(s.stage, s, left, right);
        this.stage = s.stage;
      }

      // --- дыхание: каждый пик слога выдыхает облачко у иконки
      const micRel = -contentWidth(s.text) / 2 + 8;
      if (s.stage === 'listening') {
        const r = s.raw;
        const peak = this.rising && r < this.prevRaw - 1e-4 && this.prevRaw > 0.2;
        if (peak && s.time - this.lastPuff > 0.11) {
          let slot = this.puffs[0];
          for (const p of this.puffs) if (p.age > slot.age) slot = p;
          slot.x = micRel + (this.rand() - 0.5) * 6;
          slot.y = (this.rand() - 0.5) * 8;
          // Выдох летит вдоль стекла вправо, каждый чуть в свою сторону.
          const ang = (this.rand() - 0.5) * 1.1;
          const reach = 18 + 50 * this.prevRaw;
          slot.dx = Math.cos(ang) * reach;
          slot.dy = Math.sin(ang) * reach * 0.35;
          slot.age = 0;
          slot.str = clamp(this.prevRaw, 0, 1);
          this.lastPuff = s.time;
        }
        if (r > this.prevRaw + 1e-4) this.rising = true;
        else if (r < this.prevRaw - 1e-4) this.rising = false;
        this.prevRaw = r;
      } else {
        this.prevRaw = 0;
        this.rising = false;
      }
      this.puffs.forEach((p, i) => {
        p.age += dt;
        const alive = p.age < PUFF_LIFE;
        const k = p.age / PUFF_LIFE;
        // Радиус расползается быстро и тормозит, громкий слог — большое пятно.
        const R = (12 + 78 * Math.pow(p.str, 1.4)) * (1 - Math.exp(-p.age / 0.18));
        // Облачко чуть сносит вправо — выдох идёт вдоль стекла.
        const drift = 1 - Math.exp(-p.age / 0.35);
        this.puffBuf[i * 4] = cx + p.x + (p.dx || 0) * drift;
        this.puffBuf[i * 4 + 1] = cy + p.y + (p.dy || 0) * drift;
        this.puffBuf[i * 4 + 2] = Math.max(R, 1);
        this.puffBuf[i * 4 + 3] = -0.35 + 1.4 * Math.pow(k, 1.25);
        this.puffA[i] = alive ? 0.3 + 0.45 * p.str : 0;
      });

      // --- фронт тумана и протирка
      if (s.stage === 'transcribing') {
        // Асимптота, а не пружина до упора: к 0.8 с туман покрывает ~60%,
        // к 2.5 с — ~90%, и на долгой очереди облака всё ещё видно движение.
        this.front.set(0.97 * (1 - Math.exp(-s.t / 0.8)));
      }
      const front = clamp(this.front.step(dt), 0, 1.05);
      const breath = this.breath.set(s.stage === 'transcribing' || s.stage === 'polishing' ? 1 : 0).step(dt);
      let wipeX = -1e5;
      let wipeGlow = 0;
      if (this.wiping) {
        if (this.wipeDelay > 0) {
          this.wipeDelay -= dt;
          this.wipe.snap(left - 40);
        } else {
          this.wipe.set(right + 70);
        }
        const x = this.wipe.step(dt);
        wipeX = x;
        wipeGlow = smooth(left - 40, left - 5, x) * (1 - smooth(right - 5, right + 50, x));
        this.streakFrom = x;
        if (x > right + 30) {
          // Полоса прошла: стекло за ней уже чистое, туман снимаем без анимации.
          this.wiping = false;
          this.front.snap(0);
          wipeX = -1e5;
          wipeGlow = 0;
        }
      }

      // Мокрые следы живут только в «Причёсываю»: в «Готово» стекло чистое.
      const streakVis = this.streakVis.set(s.stage === 'polishing' ? 1 : 0).step(dt);
      if (s.stage === 'polishing' && this.wipeDelay <= 0) this.streakT += dt;
      if (!this.wiping) this.streakFrom = 1e5;
      // Плёнка сохнет за ~1.5 с после протирки: к «Готово» её обычно уже нет.
      const streakDry = Math.pow(smooth(0.5, 2.0, this.streakT), 0.8);

      // --- ошибка: вспышка тумана и медленное испарение пятнами
      this.errT += dt;
      const et = this.errT;
      const err = et < 4 ? 1 - Math.exp(-et / 0.05) : 0;
      const errThr = -0.25 + 1.3 * Math.pow(smooth(0.35, 2.4, et), 0.9);
      const flash = 0.1 * Math.exp(-et / 0.22);

      const gl = ctx.gl;
      gl.useProgram(this.prog.prog);
      gl.uniform4fv(this.prog.uniforms.uPuff, this.puffBuf);
      gl.uniform1fv(this.prog.uniforms.uPuffA, this.puffA);
      ctx.draw(this.prog, {
        uCenter: [cx, cy],
        uSize: [pw, ph],
        uMat: mRaw,
        uAmp: 41 * Math.max(1, mRaw),
        uFront: front,
        uBreath: breath,
        uStreakFrom: this.streakFrom,
        uStreakDry: streakDry,
        // В «Готово» стекло чистое сразу: следы не доживают до новой ширины.
        uStreakVis: s.stage === 'polishing' ? streakVis : 0,
        uStreakX: this.streakX,
        uWipe: wipeX,
        uWipeGlow: wipeGlow,
        uErr: err,
        uErrThr: errThr,
        uFlash: flash,
        uErrColor: [1.0, 0.42, 0.45],
      });

      // --- подпись: проявляется, когда линза выросла и ширина вместила текст
      // Подпись отпирается на 80–93% ширины и на этом отрезке ужимается масштабом:
      // так она не пропадает на время морфа и гарантированно влезает в форму.
      const need = s.targetW;
      const fit = smooth(need * 0.8, need * 0.93, pw);
      const scale = Math.min(1, pw / need);
      const appear = smooth(0.55, 0.95, m);
      let opacity = appear * fit;
      let blur = 2 * (1 - fit);
      if (s.stage === 'error') {
        // Сообщение об ошибке должно совпасть со вспышкой, а не прийти после неё.
        // Ошибку читают сразу: с 0.7 до полной за 120 мс, влезание держит масштаб.
        opacity = Math.max(opacity, appear * (0.7 + 0.3 * smooth(0, 0.12, s.t)));
        blur = Math.min(blur, 0.6);
      }
      if (s.stage === 'done') {
        // Текст проявляется резким по мере того, как сходит остаток тумана.
        blur += 2.5 * clamp(front, 0, 1);
      }
      if (!s.shown) opacity = smooth(0.4, 0.9, m);
      return { cx, cy, labelOpacity: opacity, labelScale: scale, labelBlur: blur, _d: [front.toFixed(3), Math.round(wipeX), this.wiping, Math.round(right), streakDry.toFixed(2)] };
    },
  });
})();
