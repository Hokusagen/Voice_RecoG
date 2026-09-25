// «Линза» — канон Apple Liquid Glass без добавок: вся выразительность в оптике.
// Ни цвета, ни спутников: капсула, которая ломает свет, и свет, который
// один раз обходит силуэт при смене состояния. Эталон для остальных концептов.
(function () {
  'use strict';

  const BASE_H = 56;
  const BASE_W = 250;          // ширина, на которой стекло имеет «паспортную» толщину
  const SWEEP = 0.9;           // обход света, с
  const LIGHT0 = -Math.PI / 4; // покой: свет сверху справа (экранные оси, y вниз)
  // Текст влезает, когда до кромки остаётся ~8 px: поля капсулы 24 px с каждой
  // стороны, торец на высоте строки съедает ещё ~2 px.
  const FIT_SLACK = 30;
  const FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif';

  // Ease-in-out для обхода света: свет трогается и останавливается мягко,
  // поэтому воспринимается как поворот предмета, а не как бегущая точка.
  const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };

  const FRAG = `
uniform vec2 uCenter;
uniform vec2 uSize;
uniform float uMat;
uniform float uBevel;
uniform float uAmp;
uniform float uHi;
uniform float uTint;
uniform vec2 uLight;
uniform float uSpec;
uniform float uPass;
uniform float uVoice;
uniform vec3 uIcon;   // xy — центр иконки, z — её непрозрачность
float shape(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
`;

  const MAIN = `
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  // Дальше ~100 px от формы тень уже меньше 1/255: отдаём фон как есть,
  // без нормалей и размытия — основная площадь холста почти бесплатна.
  float d0 = shape(p);
  if (d0 > 100.0 || uMat <= 0.001) { outColor = vec4(bg, 1.0); return; }
  float mc = clamp(uMat, 0.0, 1.0);
  Glass g = defaultGlass();
  g.bevel = uBevel;
  g.amplitude = uAmp;
  g.highlight = uHi;
  g.light = uLight;
  g.materialize = uMat;
  // Ошибка — едва заметный красный налёт; в остальных состояниях стекло нейтрально.
  g.tint = vec3(1.0, 0.34, 0.38);
  g.tintAmount = uTint;
  // Лёгкое расхождение каналов только в кромке: в центре смещения нет,
  // и тройная выборка там была бы пустой тратой.
  g.dispersion = (-d0 < uBevel + 1.0) ? 0.035 : 0.0;
  vec4 glass = liquidGlass(p, g, bg);
  vec3 col = glass.rgb;
  // Общий блик — полоса 1 px, и её поворот почти не читается глазом. Добавляем
  // узкий «лепесток» света у самой кромки, сосредоточенный вокруг направления
  // на источник (и вдвое слабее напротив): именно он показывает, где свет, и
  // именно его видно, когда свет обходит силуэт.
  float wide = 1.8 + 0.9 * uPass + 0.8 * uVoice;
  if (glass.a > 0.0 && -d0 < wide + 0.5) {
    vec2 n;
    float inside = max(-shapeDist(p, n), 0.0);
    float c = dot(n, uLight);
    // Громкий слог расширяет освещённую дугу: кромка «вспыхивает» по большей
    // длине, и голос виден даже над пустым фоном, где преломлять нечего.
    float e = mix(6.0, 2.5, uVoice);
    float lobe = pow(max(c, 0.0), e) + 0.5 * pow(max(-c, 0.0), e);
    float k = lobe * uSpec * glass.a * mc;
    // На тёмном свет — осветление преломлённого фона. На светлом осветлять
    // нечего, и свет читается контрастом: тонкая тёмная линия по самому краю
    // со стороны источника, как ребро стекла на белой бумаге.
    float bright = smoothstep(0.5, 0.85, luma(col));
    float band = 1.0 - smoothstep(0.3, wide, inside);
    col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
    float edge = 1.0 - smoothstep(0.35, 1.25, inside);
    col *= 1.0 - 0.42 * bright * edge * k;
  }
  // Ореол под иконкой: CSS-тень букв на SVG не ложится, и цветная точка
  // терялась на пёстром фоне. Тон ореола — противоположный тону текста,
  // который основа выбирает по средней светлоте фона под плашкой.
  vec2 di = p - uIcon.xy;
  float r2 = dot(di, di);
  if (uIcon.z > 0.01 && r2 < 400.0) {
    float mean = luma(sceneAt(uCenter, 5.0) + sceneAt(uCenter + vec2(-70.0, 0.0), 5.0) + sceneAt(uCenter + vec2(70.0, 0.0), 5.0)) / 3.0;
    float halo = exp(-r2 / 72.0) * uIcon.z * glass.a;
    col = mean > 0.45 ? col + (1.0 - col) * 0.45 * halo : col * (1.0 - 0.42 * halo);
  }
  outColor = vec4(col, 1.0);
}
`;

  LG.register({
    id: 'lens',
    setup(ctx) {
      this.prog = ctx.program(ctx.glsl.header + ctx.glsl.common + FRAG + ctx.glsl.glass + MAIN);
      // Материализация: мягкий подход с лёгким перелётом, как у Apple.
      this.mat = new ctx.Spring(0, 0.45, 0.8);
      // Ширина snappy: догоняет текст с едва заметным перелётом.
      this.w = new ctx.Spring(BASE_W, 0.5, 0.85);
      // Голос: быстрая, чуть упругая — линза «вдыхает» слог, а не дрожит.
      this.voice = new ctx.Spring(0, 0.25, 0.7);
      // Встряхивание ошибки: слабое демпфирование даёт два-три затухающих качка.
      this.shake = new ctx.Spring(0, 0.3, 0.35);
      // Вход и выход «думания» и красного налёта — без скачка, апериодически.
      this.think = new ctx.Spring(0, 0.6, 1.0);
      this.tint = new ctx.Spring(0, 0.4, 1.0);
      this.stage = 'hidden';
      this.sweepAt = -10;
      this.textAt = null;
      this.reveal = 3;
      this.swap = false;
      this.shakePending = false;
      // Огибающие голоса для автоусиления: верх и низ слога.
      this.peak = 0;
      this.valley = 0;
      this.measure = document.createElement('canvas').getContext('2d');
      this.textKey = '';
      this.contentW = 0;
    },

    // Ширина строки «иконка + заголовок + деталь», как её раскладывает основа:
    // нужна, чтобы поставить ореол ровно под иконку.
    labelWidth(text) {
      const key = text.title + '|' + text.detail;
      if (key !== this.textKey) {
        const m = this.measure;
        m.font = `600 14px ${FONT_UI}`;
        let w = 16 + 10 + m.measureText(text.title).width;
        if (text.detail) { m.font = `400 13px ${FONT_UI}`; w += 10 + m.measureText(text.detail).width; }
        this.textKey = key;
        this.contentW = w;
      }
      return this.contentW;
    },

    // Сырой уровень гуляет между слогами всего на ±0.08 — линза на глаз стоит.
    // Нормируем слог по его же огибающим (быстро вверх/вниз, медленно назад):
    // каждый слог доходит почти до 1, пауза — до 0, тихий микрофон не шумит.
    syllable(level, dt) {
      const back = 1 - Math.exp(-dt / 0.6);
      this.peak = level > this.peak ? level : this.peak + (level - this.peak) * back;
      this.valley = level < this.valley ? level : this.valley + (level - this.valley) * back;
      const range = Math.max(this.peak - this.valley, 0.12);
      const pulse = clamp01((level - this.valley) / range);
      // Небольшая доля абсолютного уровня: громкая фраза в целом чуть «толще» тихой.
      return clamp01(0.2 * Math.min(1, level * 2) + 0.8 * pulse);
    },

    frame(ctx, s) {
      const dt = s.dt;
      const wNow = this.w.value;

      // ---- смена состояния: свет обходит силуэт
      if (s.stage !== this.stage) {
        const from = this.stage;
        this.stage = s.stage;
        if (s.shown) {
          this.sweepAt = s.time;
          // Из невидимого состояния ширина сразу встаёт под текст:
          // появление — рост линзы, а не растяжение.
          const fromHidden = from === 'hidden' && this.mat.value < 0.05;
          if (fromHidden) this.w.snap(s.targetW);
          // Текст гасим, только если новый не влезает в нынешнюю ширину;
          // иначе новая подпись просто проступает поверх, без пустой капсулы.
          const fitsNow = wNow >= s.targetW - FIT_SLACK;
          if (fromHidden || !fitsNow || this.textAt == null) {
            this.textAt = null;
            this.swap = false;
          } else {
            this.textAt = s.time;
            this.swap = true;
          }
          this.reveal = s.stage === 'done' ? 6 : 3;
          // Толчок ошибки ждёт, пока ширина почти придёт: на фоне сжатия
          // на 200 px 12-пиксельный качок терялся.
          this.shakePending = s.stage === 'error';
        }
      }

      // ---- материализация: на уходе быстрее и без перелёта. Критическая пружина
      // 0.32 с доходит до 7% за ~220 мс; A на уходе идёт как m³, так что на глаз
      // линза тает к ~150 мс, а не обрывается.
      if (s.shown) { this.mat.response = 0.45; this.mat.damping = 0.8; }
      else { this.mat.response = 0.32; this.mat.damping = 1.0; }
      const m = this.mat.set(s.shown ? 1 : 0).step(dt);
      const mc = clamp01(m);

      if (s.shown) this.w.set(s.targetW);
      const w = this.w.step(dt);
      if (this.shakePending && s.stage === 'error' && (Math.abs(w - s.targetW) < 24 || s.t > 0.35)) {
        this.shake.velocity += 420;
        this.shakePending = false;
      }
      const drive = s.stage === 'listening' ? this.syllable(s.level, dt) : 0;
      const voice = this.voice.set(drive).step(dt);
      const thinking = s.stage === 'transcribing' || s.stage === 'polishing';
      const think = this.think.set(thinking ? 1 : 0).step(dt);
      const tint = this.tint.set(s.stage === 'error' ? 0.045 : 0).step(dt);
      const dx = this.shake.set(0).step(dt);

      // ---- геометрия: лёгкий масштаб 0.96→1 вместе с материализацией
      const scale = 0.96 + 0.04 * m;
      const h = (BASE_H + 4 * voice) * scale;
      const ww = Math.max(w, BASE_H) * scale;
      const cx = ctx.W / 2 + dx;
      const cy = ctx.H / 2;

      // ---- оптика: шире — толще (размер^0.3), голос и «думание» меняют только A.
      // Кромка сужается вместе с материализацией, а A идёт как m² (на уходе m³):
      // иначе зеркальная полоса ещё ломала фон, когда тело линзы уже растаяло,
      // и у торцов висели оторванные перевёрнутые глифы. При m³ полоса берёт
      // фон не глубже ~6 px — это уже рябь, а не буквы.
      const thick = Math.pow(Math.max(w / BASE_W, 1), 0.3);
      const breath = 1 + 0.15 * Math.sin(2 * Math.PI * 0.6 * s.time) * think;
      const fade = s.shown ? mc : mc * mc;
      const amp = 41 * thick * (1 + 0.35 * voice) * breath * fade;
      const bevel = 13 * thick * (0.35 + 0.65 * mc);

      // Свет: в покое стоит, по событию один раз проворачивается на 360°.
      const sw = clamp01((s.time - this.sweepAt) / SWEEP);
      const ang = LIGHT0 + 2 * Math.PI * easeInOut(sw);
      // Пока свет идёт, лепесток ярче и шире — проход читается, но без вспышки;
      // громкий слог тоже подсвечивает кромку.
      const passing = sw < 1 ? Math.sin(Math.PI * sw) : 0;
      const hi = 1 + 0.4 * voice;
      const spec = 0.2 + 0.3 * passing + 0.5 * voice;

      // ---- текст: последним, только когда форма уже вмещает его целиком
      const fits = w >= s.targetW - FIT_SLACK && mc > 0.8;
      if (s.shown && fits && this.textAt == null) this.textAt = s.time;
      let opacity = 0;
      let blur = 0;
      if (s.shown && this.textAt != null) {
        const k = s.time - this.textAt;
        const gate = smooth(0.8, 0.97, mc);
        if (this.swap) {
          // Подпись сменилась в той же ширине: проступает с полупрозрачности,
          // без провала в пустоту.
          opacity = (0.4 + 0.6 * smooth(0, 0.18, k)) * gate;
          blur = 1.5 * (1 - smooth(0, 0.2, k));
        } else {
          opacity = smooth(0, 0.22, k) * gate;
          // В «Готово» результат проступает из короткого размытия: так читается «проявился».
          blur = this.reveal * (1 - smooth(0, 0.28, k));
        }
      }

      const iconX = cx - this.labelWidth(s.text) / 2 + 8;
      ctx.draw(this.prog, {
        uCenter: [cx, cy], uSize: [ww, h], uMat: m,
        uBevel: bevel, uAmp: amp, uHi: hi, uTint: tint, uSpec: spec, uPass: passing, uVoice: voice,
        uLight: [Math.cos(ang), Math.sin(ang)],
        uIcon: [iconX, cy, opacity],
      });
      return { cx, cy, labelOpacity: opacity, labelBlur: blur };
    },
  });
})();
