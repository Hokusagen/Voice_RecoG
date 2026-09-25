/* «Ртуть»: состояние плашки выражается топологией жидкого стекла.
 *
 * Форма — капсула 56 px плюс до трёх капель, слитых нормированным smin, как
 * GlassEffectContainer у Apple. Капли живут справа от текста: отпочковываются
 * от правого торца, висят рядом, возвращаются и сливаются. Всё движение —
 * пружины; перемычки и разрывы не анимируются отдельно, их даёт сам smin,
 * когда зазор проходит порог 2k.
 */
(function () {
  'use strict';

  const H0 = 56;          // высота капсулы
  const R0 = H0 / 2;      // радиус торца
  const K_REST = 5.25;    // вздутие smin в покое: 3/16 от spacing Apple, пересчитанного на r = 28
  const K_MAX = 10;       // выше — «вата»: перемычка шире капсулы

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const deg = (a) => (a * Math.PI) / 180;

  // SDF капсулы на стороне JS — чтобы знать, насколько капля утонула в форме.
  function sdPill(px, py, cx, cy, w, h) {
    const r = h / 2;
    const qx = Math.abs(px - cx) - w / 2 + r;
    const qy = Math.abs(py - cy) - h / 2 + r;
    return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
  }

  class Drop {
    constructor(S) {
      this.x = new S(0, 0.45, 0.7);
      this.y = new S(0, 0.45, 0.7);
      this.r = new S(10, 0.3, 0.75);
      this.vis = new S(0, 0.22, 0.9);   // видимость: множитель радиуса и k (появление, лопание)
      this.stretch = 0;                 // вытяжка вдоль направления, площадь сохраняется
      this.dx = 1; this.dy = 0;
      this.pres = 0;                    // насколько капля снаружи капсулы, 0..1
      this.merge = false;               // цель — слиться: утонула, значит исчезла
    }
    tune(resp, damp) {
      this.x.response = this.y.response = resp;
      this.x.damping = this.y.damping = damp;
    }
    place(x, y) { this.x.snap(x); this.y.snap(y); }
    go(x, y) { this.x.set(x); this.y.set(y); }
    get alive() { return this.vis.value > 0.02 || this.vis.target > 0; }
  }

  const SHADER = `
uniform vec2 uCenter; uniform vec2 uSize; uniform float uK; uniform float uMat;
uniform vec4 uBox;                       // рамка формы: за ней только фон
uniform vec4 uD0; uniform vec4 uD1; uniform vec4 uD2;   // xy центр, z радиус, w присутствие
uniform vec4 uS0; uniform vec4 uS1; uniform vec4 uS2;   // xy направление вытяжки, z вытяжка

// Эллипс с сохранением площади (вдоль r·s, поперёк r/s); приближение Килеса
// k0·(k0−1)/k1 точно у кромки, а глубже нам точность не нужна.
float sdDrop(vec2 p, vec4 D, vec4 S) {
  vec2 q = p - D.xy;
  float s = 1.0 + S.z;
  vec2 l = vec2(dot(q, S.xy), dot(q, vec2(-S.y, S.x)));
  vec2 ab = max(D.z, 0.01) * vec2(s, 1.0 / s);
  float k0 = length(l / ab);
  float k1 = length(l / (ab * ab));
  if (k0 < 1e-3) return -min(ab.x, ab.y);
  return k0 * (k0 - 1.0) / k1;
}
float pillD(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
// Порядок цепочки фиксированный: капсула, потом капли (ядро неассоциативно).
// Неактивная капля выпадает из smin через k·присутствие, иначе раздувает капсулу.
float shape(vec2 p) {
  float d = pillD(p);
  if (uD0.w > 1e-3 && uD0.z > 0.05) d = smin(d, sdDrop(p, uD0, uS0), uK * uD0.w);
  if (uD1.w > 1e-3 && uD1.z > 0.05) d = smin(d, sdDrop(p, uD1, uS1), uK * uD1.w);
  if (uD2.w > 1e-3 && uD2.z > 0.05) d = smin(d, sdDrop(p, uD2, uS2), uK * uD2.w);
  return d;
}
`;

  const MAIN = `
uniform vec4 uText;   // xy — полуразмеры надписи, z — сила матирования под ней (0..1)
// Доля «капли» в пикселе: где капля ближе капсулы, стекло толще и линза сильнее.
float own(vec2 p, float dc, vec4 D, vec4 S, inout float rOwn) {
  if (D.w <= 1e-3 || D.z <= 0.05) return 0.0;
  float o = clamp(0.5 + (dc - sdDrop(p, D, S)) / 12.0, 0.0, 1.0) * D.w;
  if (o > 0.0) rOwn = max(rOwn, D.z);
  return o;
}
// Мягкое пятно блика у светлой стороны бусины: сдвинуто к свету, меньше трети радиуса.
float glint(vec2 p, vec4 D) {
  if (D.w <= 1e-3 || D.z <= 0.5) return 0.0;
  vec2 c = D.xy + normalize(vec2(0.7071, -0.7071)) * D.z * 0.45;
  // Утонувшая в капсуле капля бликом себя не выдаёт: иначе в торце висит точка.
  float bare = smoothstep(-2.0, 4.0, pillD(c));
  return D.w * bare * (1.0 - smoothstep(D.z * 0.08, D.z * 0.28, length(p - c)));
}
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Дальние пиксели — только фон: тень там уже меньше полуступени яркости.
  if (uMat < 0.002 || p.x < uBox.x - 90.0 || p.x > uBox.z + 90.0 || p.y < uBox.y - 90.0 || p.y > uBox.w + 90.0) {
    outColor = vec4(bg, 1.0);
    return;
  }
  Glass g = defaultGlass();
  g.materialize = uMat;
  // Без смещения фона у стекла нет силуэта: на светлом держат форму кромка, блик и тень.
  bool isFlat = uRefraction < 0.5;
  if (isFlat) {
    g.darkRim = 1.4;
    g.highlight = 1.4;
    g.shadow = mix(0.035, 0.05, smoothstep(0.55, 0.8, luma(bg)));
  }
  float d0 = shape(p);
  if (d0 > 1.5) {
    // Снаружи — только едва заметная тень, как в общем стекле, без выборок фона.
    float sd = shape(p - vec2(0.0, g.shadowY));
    float sh = uMat * g.shadow * exp(-max(sd, 0.0) / g.shadowBlur) * smoothstep(-g.shadowBlur, 0.0, sd);
    outColor = vec4(bg * (1.0 - sh), 1.0);
    return;
  }
  float dc = pillD(p);
  float rOwn = 0.0;
  float w = max(own(p, dc, uD0, uS0, rOwn), max(own(p, dc, uD1, uS1, rOwn), own(p, dc, uD2, uS2, rOwn)));
  // Капля — толстая линза: бортик глубже её радиуса, поэтому преломляется вся,
  // а амплитуда перебрасывает выборку через центр — фон в капле перевёрнут и сжат.
  g.bevel = mix(g.bevel, rOwn + 5.0, w);
  g.amplitude = mix(g.amplitude, 3.4 * rOwn + 8.0, w);
  // Под надписью фон матовее: строки фона не читаются вместе с текстом. Кромка
  // и капли остаются прозрачными — это стекло, а не тонировка.
  // Зона — капсула вокруг строки с мягким спадом: прямоугольная читалась бы заплаткой.
  vec2 tq = abs(p - uCenter) - vec2(uText.x, 0.0);
  float tb = length(max(tq, 0.0)) - uText.y;
  float under = (1.0 - smoothstep(0.0, 18.0, tb)) * uText.z * (1.0 - w);
  g.frost = mix(mix(g.frost, 7.5, under), 1.4, w);
  // Капля — бусина: блик ярче, чуть светлее тело, заметнее цветная кайма.
  g.highlight *= mix(1.0, 1.8, w);
  g.lift += 0.02 * w;
  // Три выборки вместо одной — только в зоне кромки, где сдвиг вообще есть.
  // В вогнутой шейке нормали сходятся, и радужные копии текста там выглядят
  // искрами-крестиками: каймы оставляем только на выпуклой кромке (лапласиан SDF ≥ 0).
  if (d0 > -g.bevel - 1.0) {
    const float e = 2.0;
    float lap = (shape(p + vec2(e, 0.0)) + shape(p - vec2(e, 0.0)) + shape(p + vec2(0.0, e)) + shape(p - vec2(0.0, e)) - 4.0 * d0) / (e * e);
    g.dispersion = mix(0.04, 0.09, w) * smoothstep(-0.03, 0.0, lap);
  } else {
    g.dispersion = 0.0;
  }
  vec3 col = liquidGlass(p, g, bg).rgb;
  if (w > 0.01 && d0 < 0.5) {
    // Каустика: свет, прошедший сквозь бусину, собирается у противоположного края,
    // и мягкий блик со стороны света — капля стеклянная даже на ровном фоне.
    vec2 n;
    float sdn = shapeDist(p, n);
    float band = smoothstep(0.0, 1.5, -sdn) * (1.0 - smoothstep(1.5, 0.5 * rOwn + 1.5, -sdn));
    col += 0.06 * w * band * smoothstep(0.6, 1.0, dot(-n, g.light)) * uMat;
    float spot = glint(p, uD0) + glint(p, uD1) + glint(p, uD2);
    col = mix(col, vec3(1.0), 0.32 * min(spot, 1.0) * uMat);
  }
  outColor = vec4(col, 1.0);
}
`;

  LG.register({
    id: 'mercury',

    setup(ctx) {
      const S = ctx.Spring;
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + SHADER + ctx.glsl.glass + MAIN);
      this.w = new S(210, 0.5, 0.8);
      this.mat = new S(0, 0.6, 0.9);       // материализация линзы
      this.sc = new S(0.9, 0.55, 0.7);     // конденсация: капсула чуть собирается
      this.shx = new S(0, 0.28, 0.32);     // отдача и вздрагивание капсулы
      this.kB = new S(K_REST, 0.35, 1.0);  // подпорка k на время слияния в «Готово»
      this.fade = new S(0, 0.26, 1.0);     // появление текста после смены состояния
      this.pop = new S(1, 0.22, 0.42);     // лопание капли в «Ошибке»
      this.drops = [new Drop(S), new Drop(S), new Drop(S)];
      this.m = 0;
      this.env = 0;
      this.stage = 'hidden';
      this.cycle = -1;
      // Прозрачность текста ведём сами: CSS-переход показал бы новый, ещё не влезший
      // текст поверх узкой формы, пока гаснет.
      const label = ctx.root.querySelector('.lg-label');
      this.label = label;
      if (label) {
        label.style.transition = 'color 0.3s ease';
        // «Призрак» прошлой надписи: основа меняет текст сразу, а форма дорастает
        // под новый ещё ~0.2 с. Держим старую надпись, пока новая не влезла, —
        // иначе плашка мигает пустой.
        this.ghost = label.cloneNode(true);
        this.ghost.classList.add('mercury-ghost');
        this.ghost.style.opacity = '0';
        this.ghost.style.pointerEvents = 'none';
        label.after(this.ghost);
      }
      this.ghostO = 0;
      this.ghostW = 0;
      this.lastTW = 210;
    },

    enter(s, G) {
      const [d0, d1, d2] = this.drops;
      if (this.ghost && this.label) {
        // Основа ещё не перерисовала надпись: в ней прошлый текст, тон и цвет иконки.
        this.ghost.innerHTML = this.label.innerHTML;
        this.ghost.dataset.tone = this.label.dataset.tone || '';
        this.ghost.style.color = this.label.style.color;
        this.ghostO = Number(this.label.style.opacity) || 0;
        this.ghostW = this.lastTW;
      }
      this.fade.snap(0).set(1);
      this.w.response = 0.5; this.w.damping = 0.8;
      for (const d of this.drops) { d.stretch = 0; d.merge = false; }
      if (s.stage === 'listening' && s.prev === 'hidden') {
        // Капсула конденсируется, а одна капля втягивается в правый торец.
        this.w.snap(s.targetW);
        this.sc.snap(0.9);
        d0.place(G.xR + 50, G.cy - 4);
        d0.r.snap(10);
        d0.vis.snap(0).set(1);
        d0.tune(0.6, 0.62);
      }
      if (s.stage === 'done') {
        this.w.response = 0.5; this.w.damping = 0.72;
        this.kB.set(8);
        // Жидкость течёт вперёд: пара капель выстреливает туда, куда растёт капсула,
        // и расширяющийся торец их собирает.
        const xRf = G.cx + s.targetW / 2;
        if (xRf - G.xR > 60) {
          const spots = [[0.55, -5], [0.92, 6]];
          const free = this.drops.filter((d) => !d.alive || d.pres < 0.05);
          free.slice(0, 2).forEach((d, i) => {
            d.place(G.capRx + 4, G.cy + spots[i][1]);
            d.r.snap(9 + i);
            d.vis.snap(1);
            d.tune(0.24 + i * 0.05, 0.7);
            d.go(G.xR + (xRf - G.xR) * spots[i][0], G.cy + spots[i][1]);
            d.flowUntil = 0.22 + i * 0.05;
          });
        }
      }
      if (s.stage === 'error') {
        this.shx.velocity -= 170;      // отдача: капсулу толкает влево
        this.pop.snap(1);
        // Бросаем свежую каплю из правого торца; летящая поверху капля слилась бы
        // сквозь капсулу невидимо и вынырнула справа — это читалось бы как телепорт.
        let idx = this.drops.findIndex((d) => !d.alive || d.pres < 0.05);
        if (idx < 0) idx = this.drops.reduce((b, d, i) => (d.x.value > this.drops[b].x.value ? i : b), 0);
        const e = this.drops[idx];
        this.errIdx = idx;
        e.merge = false;
        if (!e.alive || e.pres < 0.05) {
          e.r.snap(12);
          e.place(G.capRx + 4, G.cy);
          e.vis.snap(1);
        }
        e.r.set(12);
        e.tune(0.42, 0.5);
        this.popped = false;
      }
      if (s.stage === 'polishing') this.cycle = -1;
    },

    // Капля уходит в капсулу: цель внутри, а когда утонула — гаснет насовсем.
    absorb(d, tx, ty) {
      d.merge = true;
      d.go(tx, ty);
    },

    frame(ctx, s) {
      const dt = s.dt;
      const [d0, d1, d2] = this.drops;

      // Геометрия на начало кадра: цели считаются от текущей формы.
      this.w.set(s.targetW);
      const cx = ctx.W / 2 + this.shx.value;
      const cy = ctx.H / 2;
      const sc = this.sc.value;
      const w = this.w.value * sc;
      const h = H0 * sc;
      const G = { cx, cy, w, h, xL: cx - w / 2, xR: cx + w / 2, capLx: cx - w / 2 + h / 2, capRx: cx + w / 2 - h / 2 };

      const first = s.stage !== this.stage;
      if (first) {
        this.enter(s, G);
        this.stage = s.stage;
      }
      const t = s.t;

      // Огибающая громкости: быстрая атака и долгий спад — капля держится снаружи
      // всю фразу и возвращается только в паузе.
      const a = s.level > this.env ? 1 - Math.exp(-dt / 0.07) : 1 - Math.exp(-dt / 0.26);
      this.env += (s.level - this.env) * a;

      const inside = (d, ang, depth = 8) => {
        const r = d.r.target;
        const dist = R0 - r - depth;
        return [G.capRx + Math.cos(deg(ang)) * dist, cy + Math.sin(deg(ang)) * dist];
      };
      // Приготовить каплю внутри правого торца: утонувшая капля невидима, её можно переставить.
      const ready = (d, ang, r) => {
        if (d.pres < 0.02) {
          d.r.snap(r);
          const [x, y] = inside(d, ang);
          d.place(x, y);
          d.vis.snap(1);
          d.merge = false;
        }
      };

      const shown = s.stage !== 'hidden';
      this.mat.set(shown ? 1 : 0);
      this.sc.set(shown ? 1 : 0.94);
      this.kB.set(s.stage === 'done' && t < 0.6 ? 8 : K_REST);

      if (s.stage === 'listening') {
        // Спутник у правого торца: громкие слоги выталкивают его вправо, пауза втягивает.
        // Вылет пропорционален громкости: тихая речь — капля дышит у торца на шейке,
        // громкий слог выталкивает её дальше 2k, и шейка рвётся сама.
        const push = Math.pow(clamp((this.env - 0.3) / 0.5, 0, 1), 1.3) * 44;
        const breath = 6 * clamp(this.env / 0.3, 0, 1);
        const sway = clamp((s.bands[1] - s.bands[3]) * 7, -5, 5);
        if (t > 0.2 || s.prev !== 'hidden') {
          d0.tune(0.42, 0.56);
          d0.go(G.xR - 3 + breath + push, cy + sway);
        }
        d0.merge = false;
        d0.vis.set(1);
        d0.r.set(10 + 2 * s.level);
        for (const d of [d1, d2]) { d.r.set(9); const [x, y] = inside(d, 0, 10); this.absorb(d, x, y); }
      } else if (s.stage === 'transcribing') {
        // Бусины по очереди выкатываются на шейках, отрываются и сливаются обратно.
        const P = 1.6;
        const angs = [0, -32, 32];
        this.drops.forEach((d, i) => {
          if (first || !d.alive) ready(d, angs[i], 9);
          d.r.set(9);
          d.vis.set(1);
          d.merge = false;
          d.tune(0.55, 0.66);
          const off = (i * P) / 3;
          const ph = (((t - off) % P) + P) % P / P;
          const out = t >= off && ph < 0.42;
          const dist = out ? R0 + 9 + 15 : R0 - 9 - 8;
          d.go(G.capRx + Math.cos(deg(angs[i])) * dist, cy + Math.sin(deg(angs[i])) * dist);
        });
      } else if (s.stage === 'polishing') {
        // Капля отрывается от правого торца, перетекает поверху и сливается слева.
        const P = 1.8;
        const c = Math.floor(t / P);
        const act = this.drops[c % 2];
        const other = this.drops[(c + 1) % 2];
        if (c !== this.cycle) {
          this.cycle = c;
          ready(act, -25, 10);
        }
        const u = smooth(0.0, 1.3, t - c * P);
        const [px, py] = this.path(u, G, 10);
        act.merge = false;
        act.r.set(10);
        act.vis.set(1);
        act.tune(0.3, 0.8);
        act.go(px, py);
        // Прошлая капля тонет в левом торце, лишняя — в правом.
        if (other.alive && other.pres > 0.02) other.go(G.capLx - 6, cy - 4);
        const [x2, y2] = inside(d2, 0, 10);
        this.absorb(d2, x2, y2);
      } else if (s.stage === 'done') {
        for (const d of this.drops) {
          if (d.flowUntil != null && t < d.flowUntil) continue;
          d.flowUntil = null;
          // Слиться: цель — ближайшая точка осевой линии капсулы.
          if (!d.merge) d.tune(0.35, 0.8);
          const tx = clamp(d.x.target, G.capLx, G.capRx);
          this.absorb(d, tx, cy + (d.y.target - cy) * 0.3);
        }
      } else if (s.stage === 'error') {
        // Капля отлетает вправо, вздрагивает и лопается; остальные сливаются.
        const e = this.drops[this.errIdx];
        e.go(G.capRx + R0 + 12 + 24, cy);
        const q = t - 0.42;
        if (q > 0) {
          e.dx = 1; e.dy = 0;
          // Дрожь второй моды капли: сплющивается и вытягивается поперёк, затухая.
          e.stretch = -0.24 * Math.exp(-q / 0.16) * Math.sin(2 * Math.PI * 8 * q);
        }
        if (t > 0.78) {
          if (!this.popped) { this.popped = true; this.shx.velocity -= 45; }
          this.pop.set(0);
        }
        for (const d of this.drops) {
          if (d === e) continue;
          const [x, y] = inside(d, 0, 10);
          this.absorb(d, x, y);
        }
      } else {
        for (const d of this.drops) this.absorb(d, clamp(d.x.value, G.capLx, G.capRx), cy);
      }

      // Разрыв между кадрами больше четверти секунды (фоновая вкладка, безголовый
      // снимок): основа режет dt до 0.05, пружины не доходят, и надпись осталась бы
      // невидимой. Тогда капсулу и надпись ставим сразу, капли живут как есть.
      // Меряем настоящим временем: медленная машина на 20 к/с сюда не попадает.
      const now = performance.now();
      const gap = this.lastNow == null ? 0 : (now - this.lastNow) / 1000;
      this.lastNow = now;
      if (gap > 0.25) {
        this.fade.snap(1); this.mat.snap(this.mat.target);
        this.sc.snap(this.sc.target); this.w.snap(this.w.target);
      }

      // Шаг пружин.
      this.w.step(dt); this.mat.step(dt); this.sc.step(dt); this.shx.step(dt);
      this.kB.step(dt); this.fade.step(dt); this.pop.step(dt);
      let speed = 0;
      for (const d of this.drops) {
        d.x.step(dt); d.y.step(dt); d.r.step(dt); d.vis.step(dt);
        const vx = d.x.velocity, vy = d.y.velocity;
        const v = Math.hypot(vx, vy);
        // В полёте капля вытягивается по скорости — жидкость, а не шарик.
        if (s.stage !== 'error' || d !== this.drops[this.errIdx]) {
          d.stretch += (clamp(v / 1500, 0, 0.16) - d.stretch) * Math.min(1, dt * 12);
          if (v > 1) { d.dx = vx / v; d.dy = vy / v; }
        }
        const r = d.r.value * d.vis.value;
        const sd = sdPill(d.x.value, d.y.value, G.cx, G.cy, G.w, G.h);
        d.pres = r > 0.05 ? smooth(-(r + 6), -0.3 * r, sd) : 0;
        if (d.merge && d.pres < 0.06) d.vis.set(0);
        speed = Math.max(speed, v * d.pres);
      }

      // Лопание: радиус к нулю пружиной с перелётом, поверх — затухающая дрожь.
      let popMul = 1;
      if (s.stage === 'error' && t > 0.78) {
        const q = t - 0.78;
        popMul = Math.max(0, this.pop.value) * (1 + 0.22 * Math.exp(-q / 0.12) * Math.sin(2 * Math.PI * 11 * q));
        if (this.pop.value < 0.01 && q > 0.2) this.drops[this.errIdx].vis.snap(0);
      }

      // k(t) = 5.25·(1 + 0.4·m): пока идёт движение, мостик живёт дольше, как у Apple.
      const mT = clamp(Math.max(speed / 90, Math.abs(this.w.velocity) / 250), 0, 1);
      this.m += (mT - this.m) * (mT > this.m ? 1 - Math.exp(-dt / 0.05) : 1 - Math.exp(-dt / 0.18));
      const k = Math.min(K_MAX, Math.max(K_REST * (1 + 0.4 * this.m), this.kB.value));

      // Форма после шага пружин.
      const cx2 = ctx.W / 2 + this.shx.value;
      const w2 = this.w.value * this.sc.value;
      const h2 = H0 * this.sc.value;
      const box = [cx2 - w2 / 2, cy - h2 / 2, cx2 + w2 / 2, cy + h2 / 2];
      const U = {};
      this.drops.forEach((d, i) => {
        let r = d.r.value * d.vis.value;
        if (i === this.errIdx && s.stage === 'error') r *= popMul;
        const pres = d.pres * clamp(d.vis.value, 0, 1);
        U['uD' + i] = [d.x.value, d.y.value, Math.max(0, r), pres];
        U['uS' + i] = [d.dx, d.dy, clamp(d.stretch, -0.5, 0.4), 0];
        if (pres > 0.001 && r > 0.05) {
          const e = r * 1.5 + k;
          box[0] = Math.min(box[0], d.x.value - e); box[1] = Math.min(box[1], d.y.value - e);
          box[2] = Math.max(box[2], d.x.value + e); box[3] = Math.max(box[3], d.y.value + e);
        }
      });
      const mat = Math.max(0, Math.min(1, this.mat.value));

      // Текст — только когда влезает в капсулу. Содержимое надписи уже плашки на 48 px
      // (поля по 24), значит при w = targetW − 36 до торца ещё ~4 px: проявляться можно
      // заранее, пока форма дорастает, а не мигать пустой плашкой.
      const fit = smooth(s.targetW - 36, s.targetW - 20, w2);
      // Пока новая надпись не влезла, её проявление не начинается: иначе на быстром
      // росте формы окно fit проскакивается за кадр и текст выпрыгивает.
      if (fit < 0.5) this.fade.snap(0).set(1);
      const fade = clamp(this.fade.value, 0, 1);
      const matO = smooth(0.45, 0.95, mat);
      const o = fit * fade * matO;
      const lo = shown ? o : 0;
      // Старая надпись гаснет, когда проявляется новая или когда форма стала ей тесна.
      let go = 0;
      if (this.ghost) {
        const fitOld = smooth(this.ghostW - 36, this.ghostW - 20, w2);
        go = this.ghostO * fitOld * (1 - fade) * matO;
        if (go < 0.01) { go = 0; this.ghostO = 0; }
        this.ghost.style.opacity = String(go);
        if (go > 0) {
          this.ghost.style.transform = `translate(${cx2}px, ${cy}px) translate(-50%, -50%)`;
          this.ghost.style.filter = `blur(${(2.5 * fade).toFixed(2)}px)`;
        }
      }
      this.lastTW = s.targetW;
      // Матовость под надписью живёт вместе с ней, в полуширине не больше самой капсулы.
      const tW = go > lo ? this.ghostW : s.targetW;
      const tw = Math.max(0, Math.min(tW / 2 - 28, w2 / 2 - 30));
      ctx.draw(this.prog, Object.assign(U, {
        uCenter: [cx2, cy], uSize: [w2, h2], uK: k, uMat: mat, uBox: box,
        uText: [tw, 11, Math.max(lo, go), 0],
      }));
      return {
        cx: cx2,
        cy,
        labelOpacity: lo,
        labelBlur: shown ? 2.5 * (1 - Math.min(fade, fit)) : 0,
      };
    },

    // Путь поверху: из правого торца по дуге вверх, над капсулой, вниз в левый торец.
    // Зазор сначала растёт (отпочкование, шейка рвётся), держится > 2k, потом падает (слияние).
    path(u, G, r) {
      const gapPk = 16;
      const gIn = -(2 * r + 8);   // центр глубже r + 8 от кромки: капля утонула целиком
      const bump = smooth(0, 0.24, u) * (1 - smooth(0.76, 1, u));
      const R = R0 + r + gIn + (gapPk - gIn) * bump;
      const Rn = R0 + r + gapPk;
      const sweep = deg(65);
      const A1 = Rn * sweep;
      const Ls = Math.max(0, G.capRx - G.capLx);
      const T = 2 * A1 + Ls;
      const dist = u * T;
      if (dist < A1) {
        const th = deg(-25) - sweep * (dist / A1);
        return [G.capRx + Math.cos(th) * R, G.cy + Math.sin(th) * R];
      }
      if (dist < A1 + Ls) return [G.capRx - (dist - A1), G.cy - R];
      const th = deg(-90) - sweep * ((dist - A1 - Ls) / A1);
      return [G.capLx + Math.cos(th) * R, G.cy + Math.sin(th) * R];
    },
  });
})();
