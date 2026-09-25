// «Мембрана»: кромка стекла сама и есть осциллограмма голоса.
//
// Верхний край капсулы ведёт себя как поверхность жидкости с поверхностным
// натяжением: каждый слог рождает у иконки микрофона волновой пакет, который
// бежит вправо, расплывается и гаснет. Нижний край идёт слабее и в противофазе:
// толщина почти постоянна, и по капсуле бежит изгиб, как по шлангу, а не
// «бусы» из вздутий (синфазный низ превращал речь в зубчатое печенье).
// Поле смещения считается на CPU (128 отсчётов вдоль прямого участка) и
// уходит в шейдер массивом; шейдер только интерполирует его и строит SDF,
// а преломление, блик и тёмная кромка общего стекла сами «ломаются» на гребнях.
(function () {
  const N = 128;            // отсчётов поля вдоль прямого участка
  const H = 56;             // высота капсулы
  const R = H / 2;
  const VG = 180;           // групповая скорость пакета, px/с (по ТЗ)
  // Фазовая: гребни отстают от огибающей, но медленно — у короткого пакета
  // главный гребень должен жить внутри огибающей весь пробег, иначе к середине
  // капсулы от слога остаётся лишь ~0.5 px ряби.
  const VP = VG / 1.15;
  const BOT_DELAY = 0.03;   // лёгкое запаздывание низа: изгиб не жёсткий, а «течёт»
  const BOT_GAIN = 0.4;

  // Моды «желе»: частоты по Рэлею (ω₃/ω₂ ≈ 1.94), затухание мягче физики,
  // чтобы мода 3 успела показаться, а не умерла за один кадр.
  const F2 = 4.2, F3 = 4.2 * 1.94;
  const TAU2 = 0.16, TAU3 = 0.085;
  const MAX_PK = 6;         // больше — пакеты сливаются в сплошную гребёнку
  const REFRACT = 0.3;      // минимальный зазор между пакетами, с
  const DECAY = 1.1;        // затухание пакета: доходит до правого торца едва живым

  const SHADER = `
uniform vec2 uCenter;      // центр капсулы, CSS px
uniform vec2 uSize;        // полная ширина и высота
uniform vec2 uSpan;        // начало прямого участка и его длина
uniform float uMat;        // материализация 0..1
uniform float uSwell;      // жива ли волна появления 0..1
uniform vec4 uTop[32];     // смещение верхнего края наружу, px (128 отсчётов)
uniform vec4 uBot[32];     // то же для нижнего

float tapT(int i) { i = clamp(i, 0, ${N - 1}); return uTop[i >> 2][i & 3]; }
float tapB(int i) { i = clamp(i, 0, ${N - 1}); return uBot[i >> 2][i & 3]; }
// Катмулл–Ром, а не линейная интерполяция: у ломаной нормаль прыгала бы
// между отсчётами, и блик на кромке шёл бы гранями.
float cr(float a, float b, float c, float d, float t) {
  return b + 0.5 * t * (c - a + t * (2.0 * a - 5.0 * b + 4.0 * c - d + t * (3.0 * (b - c) + d - a)));
}
vec2 wave(float x) {
  float s = (x - uSpan.x) / uSpan.y * ${(N - 1).toFixed(1)};
  if (s <= 0.0 || s >= ${(N - 1).toFixed(1)}) return vec2(0.0);
  int i = int(floor(s));
  float f = s - float(i);
  return vec2(cr(tapT(i - 1), tapT(i), tapT(i + 1), tapT(i + 2), f),
              cr(tapB(i - 1), tapB(i), tapB(i + 1), tapB(i + 2), f));
}
float shape(vec2 p) {
  float d = sdPill(p, uCenter, uSize.x, uSize.y);
  vec2 w = wave(p.x);
  // Верх и низ смещаются независимо; переход по высоте плавный, иначе
  // на средней линии SDF получил бы ступеньку.
  float up = smoothstep(-0.6, 0.6, (uCenter.y - p.y) / (uSize.y * 0.5));
  return d - mix(w.y, w.x, up);
}
`;

  const MAIN = `
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Дальние пиксели — сразу фон: грубая капсула с запасом на волну и тень.
  float far = sdPill(p, uCenter, uSize.x, uSize.y);
  if (uMat < 0.002 || far > 64.0) { outColor = vec4(bg, 1.0); return; }
  Glass g = defaultGlass();
  g.materialize = uMat;
  g.dispersion = 0.06;
  // Гребень — это место, где стекло толще: линза там чуть сильнее.
  vec2 w = wave(p.x);
  float swell = max(p.y < uCenter.y ? w.x : w.y, 0.0);
  g.amplitude *= 1.0 + 0.06 * swell;
  // Тёмная кромка и тень общего стекла тянутся за горбом и мажут его в
  // грязный ореол на тёмном фоне — на гребне их ослабляем.
  g.darkRim *= clamp(1.0 - 0.12 * swell, 0.4, 1.0);
  g.shadow *= 1.0 - 0.4 * uSwell;
  outColor = vec4(liquidGlass(p, g, bg).rgb, 1.0);
}
`;

  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const smoother = (v) => { v = clamp01(v); return v * v * v * (v * (v * 6 - 15) + 10); };

  LG.register({
    id: 'membrane',

    setup(ctx) {
      const src = ctx.glsl.header + ctx.glsl.common + SHADER + ctx.glsl.glass + MAIN;
      this.prog = ctx.program(src);
      const gl = ctx.gl;
      this.locTop = gl.getUniformLocation(this.prog.prog, 'uTop');
      this.locBot = gl.getUniformLocation(this.prog.prog, 'uBot');

      // Ширина — одна пружина на все переходы; «желейный» перелёт по ТЗ.
      this.width = new ctx.Spring(260, 0.5, 0.65);
      this.mat = new ctx.Spring(0, 0.45, 0.82);
      this.tide = new ctx.Spring(0, 0.7, 1.0);
      this.alive = new ctx.Spring(0, 0.6, 1.0);
      this.prevWV = 0;
      this.modes = { a2: 0, v2: 0, a3: 0, v3: 0 };
      this.tidePhase = 0;
      this.packets = [];
      this.top = new Float32Array(N);
      this.bot = new Float32Array(N);
      this.stage = 'hidden';
      this.onset = { armed: true, trough: 0, peak: 0, pk: null };
      this.fade = 0;
      this.kick = null;

      // Прозрачность текста ведём сами по кадрам: CSS-переход в 180 мс успел бы
      // показать новый длинный текст поверх ещё узкой капсулы.
      const label = ctx.root.querySelector('.lg-label');
      if (label) label.style.transition = 'color 0.3s ease';
    },

    enterStage(s, W) {
      const from = this.stage;
      this.stage = s.stage;
      if (from === 'hidden' && s.stage !== 'hidden') {
        // Появление: линза материализуется, форма чуть «доливается» по ширине,
        // и по всей длине проходит одна мягкая волна.
        this.width.snap(W * 0.86);
        this.packets.length = 0;
        this.packets.push({ kind: 'swell', t0: s.time + 0.05, x0: -40, v: 420, sigma: 46, A: 2.4, decay: 1.2 });
      }
      if (s.stage === 'listening') this.onset = { armed: true, trough: 0, peak: 0, pk: null };
      // В «Готово» ширина разгоняется быстрее: иначе подтверждение ждёт ~0.3 с,
      // пока капсула дорастёт до строки. Перелёт тот же (damping 0.65).
      this.width.response = s.stage === 'done' ? 0.38 : 0.5;
      if (s.stage === 'done') {
        // Явный толчок в моду 2: при растяжении середина проседает и отыгрывает,
        // при сжатии — вспухает. Одного ускорения ширины на это не хватало.
        const grow = Math.sign(W - this.width.value) || 1;
        this.modes.v2 -= grow * 2 * Math.PI * F2 * 1.2;
      }
      if (s.stage === 'error') {
        // Желе: толчок в собственные моды, дальше капсула звенит сама. Толчок
        // чуть позже смены стадии — когда текст уже проявился и звон читается
        // как «не вышло», а не теряется в раздаче ширины.
        this.kick = { at: s.time + 0.14, v2: 2 * Math.PI * F2 * 4.0, v3: 2 * Math.PI * F3 * 2.4 };
      }
    },

    // Слог = фронт роста громкости с гистерезисом; пакет рождается сразу,
    // а амплитуду добирает по пику слога за первые ~80 мс (пока он ещё мал).
    listen(s, x0) {
      const o = this.onset;
      const lv = s.level;
      if (o.armed) {
        o.trough = Math.min(o.trough, lv);
        if (lv - o.trough > 0.07 && lv > 0.12) {
          o.armed = false;
          o.peak = lv;
          // Не чаще ~3 пакетов в секунду: при речи 5 слогов/с и пробеге ~1 с
          // по капсуле иначе стоит сплошная гребёнка из одинаковых горбов.
          const last = this.packets.length ? this.packets[this.packets.length - 1] : null;
          if (last && last.kind === 'wave' && s.time - last.t0 < REFRACT) {
            o.pk = null;
          } else {
            const pk = { kind: 'wave', t0: s.time, x0, sigma: 15, A: 0, lam: 46 };
            this.packets.push(pk);
            o.pk = pk;
          }
        }
      } else {
        o.peak = Math.max(o.peak, lv);
        if (o.pk && s.time - o.pk.t0 < 0.09) {
          const loud = clamp01((o.peak - 0.15) / 0.55);
          // Квадрат: тихие слоги дают почти гладкую кромку, ударные — ясный горб.
          o.pk.A = 1.5 + 2.5 * loud * loud;
          o.pk.lam = 40 + 20 * loud;     // громче — длиннее волна
        }
        if (o.peak - lv > 0.05) { o.armed = true; o.trough = lv; }
      }
      if (this.packets.length > MAX_PK) this.packets.shift();
    },

    packetAt(pk, x, tau) {
      if (tau <= 0) return 0;
      if (pk.kind === 'swell') {
        const dx = (x - (pk.x0 + pk.v * tau)) / pk.sigma;
        return pk.A * Math.exp(-0.5 * dx * dx) * Math.exp(-tau / pk.decay) * (1 - Math.exp(-tau / 0.08));
      }
      // Капиллярный пакет: огибающая бежит с VG и расплывается, гребни бегут
      // медленнее (VP) и проходят сквозь неё назад; впереди волны короче (чирп).
      const k0 = (2 * Math.PI) / pk.lam;
      const sg = pk.sigma * Math.sqrt(1 + (tau / 1.2) ** 2);
      const dx = x - (pk.x0 + VG * tau);
      const env = Math.exp(-0.5 * (dx / sg) ** 2) * Math.sqrt(pk.sigma / sg);
      const beta = (0.22 * tau) / (tau + 0.35);
      // Фаза от рождения пакета: слог всегда выталкивает кромку гребнем вверх,
      // а не случайно впадиной, как было при фазе от общих часов.
      const phase = k0 * (x - pk.x0) - k0 * VP * tau + (0.5 * k0 * beta * dx * dx) / sg;
      return pk.A * env * Math.exp(-tau / DECAY) * (1 - Math.exp(-tau / 0.05)) * Math.cos(phase);
    },

    stepModes(dt, drive) {
      const m = this.modes;
      const w2 = 2 * Math.PI * F2, w3 = 2 * Math.PI * F3;
      const n = Math.max(1, Math.ceil(dt * 480));
      const h = dt / n;
      for (let i = 0; i < n; i++) {
        m.v2 += (-w2 * w2 * m.a2 - (2 / TAU2) * m.v2 + drive) * h;
        m.a2 += m.v2 * h;
        m.v3 += (-w3 * w3 * m.a3 - (2 / TAU3) * m.v3) * h;
        m.a3 += m.v3 * h;
      }
      m.a2 = Math.max(-4.5, Math.min(4.5, m.a2));
      m.a3 = Math.max(-3, Math.min(3, m.a3));
    },

    frame(ctx, s) {
      const dt = Math.max(1e-4, s.dt);
      const listening = s.stage === 'listening';
      const thinking = s.stage === 'transcribing' || s.stage === 'polishing';
      // В «Слушаю» капсула шире текста: волнам нужна взлётная полоса.
      const targetW = listening ? Math.max(s.targetW, 260) : s.targetW;
      if (s.stage !== this.stage) this.enterStage(s, targetW);

      if (s.shown) this.width.set(targetW);
      const W = this.width.step(dt);
      const m = Math.max(0, this.mat.set(s.shown ? 1 : 0).step(dt));
      const tide = Math.max(0, this.tide.set(thinking ? 1 : 0).step(dt));
      const alive = this.alive.set(listening ? 1 : thinking ? 0.5 : 0).step(dt);

      // Мода 2 раскачивается ускорением ширины: когда капсулу резко тянут,
      // середина проседает, потом отдаёт — как желе, а не как резинка.
      if (this.kick && s.time >= this.kick.at) {
        this.modes.v2 += this.kick.v2;
        this.modes.v3 += this.kick.v3;
        this.kick = null;
      }
      const acc = (this.width.velocity - this.prevWV) / dt;
      this.prevWV = this.width.velocity;
      this.stepModes(dt, -0.04 * Math.max(-60000, Math.min(60000, acc)));

      // Мода 2 сохраняет «объём»: середина вздулась — торцы подтянулись.
      const Weff = Math.max(H, W - 1.2 * this.modes.a2);
      const cx = ctx.W / 2, cy = ctx.H / 2;
      const L = Math.max(1, Weff - H);
      const left = cx - Weff / 2;

      // Источник волн — иконка микрофона: она стоит у левого края текста.
      const labelW = s.targetW - 48;
      const x0 = Weff / 2 - labelW / 2 + 8 - R;   // от начала прямого участка

      if (listening) this.listen(s, x0);
      if (thinking) this.tidePhase = (this.tidePhase + dt / 1.8) % 1;
      this.packets = this.packets.filter((pk) => s.time - pk.t0 < 3.0);

      // Прилив: одна пологая выпуклость (+4 px, ширина на полувысоте ~80 px);
      // в середине капсулы идёт чуть быстрее, у торцов (где её гасит окно) медленнее.
      const tSig = 34;
      // Заход за торцы короткий: выпуклость переваливает через край, а не
      // прячется под окном на треть периода («волна — пауза — волна»).
      const span = L + 2.4 * tSig;
      const tideX = (phi) => -1.2 * tSig + span * (phi - (0.06 * Math.sin(2 * Math.PI * phi)));
      const tcTop = tideX(this.tidePhase);
      const tcBot = tideX((this.tidePhase - BOT_DELAY / 1.8 + 1) % 1);

      const ramp = Math.min(26, L / 3);
      const t = s.time;
      for (let j = 0; j < N; j++) {
        const x = (j / (N - 1)) * L;
        const u = x / L;
        const win = smoother(x / ramp) * smoother((L - x) / ramp);
        if (win <= 0) { this.top[j] = 0; this.bot[j] = 0; continue; }
        // Едва заметная рябь покоя: две медленные встречные компоненты, 0.3 px.
        const idleT = 0.3 * alive * (0.6 * Math.sin(x * 0.0898 - t * 2.1) + 0.4 * Math.sin(x * 0.146 + t * 1.3 + 1.7));
        const idleB = 0.3 * alive * (0.6 * Math.sin(x * 0.0898 - (t - BOT_DELAY) * 2.1) + 0.4 * Math.sin(x * 0.146 + (t - BOT_DELAY) * 1.3 + 1.7));
        // Низ в противофазе (минус): кромки смещаются в одну сторону, капсула
        // изгибается целиком, толщина под текстом почти не меняется.
        let wt = idleT, wb = -idleB * BOT_GAIN;
        for (const pk of this.packets) {
          wt += this.packetAt(pk, x, t - pk.t0);
          wb -= BOT_GAIN * this.packetAt(pk, x, t - pk.t0 - BOT_DELAY);
        }
        if (tide > 0.001) {
          const a = (x - tcTop) / tSig, b = (x - tcBot) / tSig;
          wt += 4 * tide * Math.exp(-0.5 * a * a);
          wb += 4 * BOT_GAIN * tide * Math.exp(-0.5 * b * b);
        }
        // Моды: 2 — середина дышит толщиной, 3 — капсулу «перекашивает» S-ом.
        const m2 = this.modes.a2 * Math.sin(Math.PI * u);
        const m3 = this.modes.a3 * Math.sin(2 * Math.PI * u);
        wt += m2 + m3;
        wb += m2 - m3;
        this.top[j] = wt * win;
        this.bot[j] = wb * win;
      }

      let swellAlive = 0;
      for (const pk of this.packets) {
        if (pk.kind === 'swell') swellAlive = Math.max(swellAlive, Math.exp(-(t - pk.t0) / pk.decay));
      }
      const gl = ctx.gl;
      gl.useProgram(this.prog.prog);
      gl.uniform4fv(this.locTop, this.top);
      gl.uniform4fv(this.locBot, this.bot);
      const h = H * (0.9 + 0.1 * m);
      ctx.draw(this.prog, {
        uCenter: [cx, cy],
        uSize: [Weff * (0.94 + 0.06 * m), h],
        uSpan: [left + R, L],
        uMat: m,
        uSwell: swellAlive,
      });

      // Текст виден только тогда, когда форма его уже вмещает: иначе при
      // смене состояния длинная строка на миг вылезла бы за узкую капсулу.
      const room = Weff * (0.94 + 0.06 * m) - labelW - 12;
      const fit = clamp01(room / 14);
      const want = s.shown ? fit * clamp01((m - 0.4) / 0.45) : 0;
      this.fade += (want - this.fade) * (1 - Math.exp(-dt / 0.08));
      if (this.fade > fit) this.fade = fit;
      return {
        cx, cy,
        labelOpacity: this.fade,
        labelBlur: this.fade < 0.999 ? (1 - this.fade) * 3 : 0,
      };
    },
  });
})();
