/* Лаборатория жидкого стекла: общая основа для концептов плашки VoiceTyper.
 *
 * Даёт каждому концепту одно и то же: сцену «за стеклом» (редактор кода,
 * документ или обои — длинное полотно, которое прокручивается), общий цикл
 * состояний плашки, имитацию речи, текст плашки поверх холста, пружины и
 * GLSL-заготовки — SDF, размытие фона по мип-уровням и общее «жидкое
 * стекло» с преломлением в кромке.
 *
 * Концепт регистрируется так:
 *   LG.register({ id: 'lens', setup(ctx) {...}, frame(ctx, s) { return {cx, cy, ...} } })
 * и попадает в элемент [data-concept="lens"] на странице.
 */
(function () {
  'use strict';

  const LG = (window.LG = {});

  // ---------------------------------------------------------------- сцена

  const SCENE_W = 1400;          // CSS px: ширина полотна
  const SCENE_H = 1600;          // CSS px: высота полотна, по вертикали повторяется
  const SCENE_SCALE = 1.5;       // текстурных px на CSS px: текст остаётся чётким

  const FONT_UI = '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif';
  const FONT_CODE = '"Cascadia Code", "Cascadia Mono", Consolas, "SF Mono", monospace';

  const DOC_TEXT = [
    ['h1', 'Почему стекло выглядит стеклом'],
    ['p', 'Прозрачный прямоугольник с размытием ещё не стекло. Глаз узнаёт материал по тому, как он ломает свет: у края толстое стекло сдвигает картинку, вытягивает её вдоль кромки и чуть раскладывает на цвета. В середине, где поверхность плоская, фон виден почти без искажений.'],
    ['p', 'Второй признак — блик. Кромка, повёрнутая к свету, вспыхивает тонкой линией, а противоположная светится слабее. Стоит блику сдвинуться вслед за движением, и мозг перестаёт сомневаться: это предмет, у которого есть толщина.'],
    ['h2', 'Что делает форму жидкой'],
    ['p', 'Жидкость не растягивается, а перетекает. Капля, которая отделяется от большой капли, сначала вытягивает перемычку, потом рвёт её и вздрагивает. Когда две капли встречаются, между ними появляется мостик раньше, чем они коснутся.'],
    ['list', ['Перемычка между формами — гладкий минимум двух расстояний.', 'Упругость — пружина с недодемпфированием около 0,7.', 'Инерция — форма догоняет цель с запаздыванием и лёгким перелётом.']],
    ['img', 'fig'],
    ['p', 'Голос удобно показывать дыханием формы: громкость меняет толщину и яркость, а не заставляет что-то бегать по кругу. Движение должно жить на периферии зрения и не тянуть взгляд на себя, пока человек диктует.'],
    ['h2', 'Замеры'],
    ['table', [['Состояние', 'Длительность', 'Цвет'], ['Слушаю', 'пока держат F8', 'красный'], ['Распознаю', '0,5–1,5 с', 'синий'], ['Причёсываю', '0,3–0,8 с', 'фиолетовый'], ['Готово', '2,4 с + 30 мс на знак', 'зелёный']]],
    ['p', 'Плашка висит над чужими окнами: над белым документом, тёмным редактором, видео. Поэтому материал обязан читаться на любом фоне, а текст на нём — оставаться чётким без плотной подложки.'],
  ];

  const CODE_TEXT = `from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests


@dataclass
class Quota:
    """Остатки лимитов, как их сообщил сервер в заголовках."""

    requests_left: int | None = None
    tokens_left: int | None = None
    tokens_reset_s: float = 0.0
    at: float = field(default_factory=time.monotonic)

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.at

    def tokens_now(self) -> int | None:
        if self.tokens_left is None:
            return None
        if self.tokens_reset_s and self.age_s >= self.tokens_reset_s:
            return self.tokens_left
        return self.tokens_left


class CloudClient:
    def __init__(self, cfg, llm_cfg) -> None:
        self.cfg = cfg
        self.llm_cfg = llm_cfg
        self._session = requests.Session()
        self.last_error: str | None = None

    def polish(self, raw_text: str, style: str = "careful"):
        system = self.llm_cfg.system_prompt
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": raw_text},
            ],
            "temperature": 0.0,
            "max_tokens": self.output_cap(raw_text),
        }
        started = time.monotonic()
        response = self._request("chat/completions", payload)
        if response.status_code == 429:
            raise CloudLimited("исчерпан лимит", "minute", 60.0)
        took = time.monotonic() - started
        print(f"[cloud] за {took:.1f} с")
        return response.json()["choices"][0]["message"]["content"]

    def output_cap(self, raw_text: str) -> int:
        # Потолок по длине фразы: в лимит идёт не ответ, а max_tokens.
        cap = len(raw_text) // 3 + 128 + len(raw_text) // 9
        return min(cap, self.cfg.output_tokens_per_minute)
`;

  function wrapText(g, text, x, y, maxW, lineH) {
    const words = text.split(' ');
    let line = '';
    for (const word of words) {
      const test = line ? line + ' ' + word : word;
      if (g.measureText(test).width > maxW && line) {
        g.fillText(line, x, y);
        line = word;
        y += lineH;
      } else {
        line = test;
      }
    }
    if (line) g.fillText(line, x, y);
    return y + lineH;
  }

  function drawDoc(g) {
    g.fillStyle = '#f7f6f3';
    g.fillRect(0, 0, SCENE_W, SCENE_H);
    // Колонка документа и серые поля, как у текстового редактора.
    const colW = 720;
    const x0 = (SCENE_W - colW) / 2;
    g.fillStyle = '#ffffff';
    g.fillRect(x0 - 56, 0, colW + 112, SCENE_H);
    let y = 70;
    for (const [kind, value] of DOC_TEXT) {
      if (kind === 'h1') {
        g.fillStyle = '#141414';
        g.font = `700 34px ${FONT_UI}`;
        y = wrapText(g, value, x0, y + 10, colW, 42) + 8;
      } else if (kind === 'h2') {
        g.fillStyle = '#1b1b1b';
        g.font = `650 23px ${FONT_UI}`;
        y = wrapText(g, value, x0, y + 18, colW, 30) + 2;
      } else if (kind === 'p') {
        g.fillStyle = '#2b2b2b';
        g.font = `400 17px ${FONT_UI}`;
        y = wrapText(g, value, x0, y, colW, 27) + 12;
      } else if (kind === 'list') {
        g.font = `400 17px ${FONT_UI}`;
        for (const item of value) {
          g.fillStyle = '#d0452f';
          g.beginPath();
          g.arc(x0 + 6, y - 6, 3.5, 0, Math.PI * 2);
          g.fill();
          g.fillStyle = '#2b2b2b';
          y = wrapText(g, item, x0 + 22, y, colW - 22, 27) + 4;
        }
        y += 10;
      } else if (kind === 'img') {
        const h = 230;
        const grad = g.createLinearGradient(x0, y, x0 + colW, y + h);
        grad.addColorStop(0, '#1d3b6b');
        grad.addColorStop(0.5, '#3e7cc7');
        grad.addColorStop(1, '#f2b04f');
        g.fillStyle = grad;
        roundRect(g, x0, y, colW, h, 14);
        g.fill();
        // Пара чётких фигур внутри: на них видно преломление.
        g.fillStyle = 'rgba(255,255,255,0.92)';
        g.beginPath();
        g.arc(x0 + 150, y + 115, 58, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = '#0f1e33';
        for (let i = 0; i < 9; i++) g.fillRect(x0 + 300 + i * 42, y + 60, 16, 110);
        g.fillStyle = 'rgba(255,255,255,0.85)';
        g.font = `600 15px ${FONT_UI}`;
        g.fillText('Рис. 1. Кромка стекла сдвигает полосы, середина — нет', x0 + 18, y + h - 18);
        y += h + 30;
      } else if (kind === 'table') {
        const cols = [260, 230, 230];
        g.font = `400 16px ${FONT_UI}`;
        value.forEach((row, r) => {
          let x = x0;
          g.fillStyle = r === 0 ? '#eeece6' : r % 2 ? '#ffffff' : '#fafaf7';
          g.fillRect(x0, y - 22, colW, 38);
          row.forEach((cell, c) => {
            g.fillStyle = r === 0 ? '#555' : '#222';
            g.font = r === 0 ? `600 14px ${FONT_UI}` : `400 16px ${FONT_UI}`;
            g.fillText(cell, x + 12, y);
            x += cols[c];
          });
          g.fillStyle = '#e4e2dc';
          g.fillRect(x0, y + 16, colW, 1);
          y += 38;
        });
        y += 26;
      }
    }
    // Повтор по вертикали: низ полотна продолжает верх.
  }

  const KEYWORDS = new Set(['from', 'import', 'class', 'def', 'return', 'if', 'else', 'elif', 'for', 'in', 'is',
    'not', 'and', 'or', 'None', 'True', 'False', 'self', 'raise', 'try', 'except', 'with', 'as', 'while', 'print']);

  function drawCode(g) {
    g.fillStyle = '#1e1f22';
    g.fillRect(0, 0, SCENE_W, SCENE_H);
    // Боковая панель и мини-карта: у редактора есть края, как в жизни.
    g.fillStyle = '#18191b';
    g.fillRect(0, 0, 250, SCENE_H);
    g.font = `400 14px ${FONT_UI}`;
    const tree = ['VOICERECOGNIZE', '  src', '    core', '      audio.py', '      cloud.py', '      hotkeys.py',
      '      journal.py', '      llm.py', '      paster.py', '      pipeline.py', '    ui', '      hud.py',
      '      liquid.py', '      live.py', '    config.py', '    main.py', '  CHANGELOG.md', '  README.md'];
    tree.forEach((item, i) => {
      g.fillStyle = item.includes('cloud.py') ? '#e6e6e6' : '#9a9da3';
      if (item.includes('cloud.py')) {
        g.fillStyle = '#2b2d31';
        g.fillRect(0, 40 + i * 24 - 17, 250, 24);
        g.fillStyle = '#e6e6e6';
      }
      g.fillText(item, 18, 40 + i * 24);
    });
    const lines = CODE_TEXT.split('\n');
    const lineH = 22;
    const x0 = 300;
    g.font = `400 15px ${FONT_CODE}`;
    const total = Math.floor(SCENE_H / lineH);
    for (let i = 0; i < total; i++) {
      const line = lines[i % lines.length];
      const y = 30 + i * lineH;
      g.fillStyle = '#5c6068';
      g.textAlign = 'right';
      g.fillText(String(i + 1), x0 - 24, y);
      g.textAlign = 'left';
      drawCodeLine(g, line, x0, y);
    }
    // Мини-карта справа.
    for (let i = 0; i < 160; i++) {
      const line = lines[i % lines.length];
      g.fillStyle = 'rgba(160,170,190,0.18)';
      g.fillRect(SCENE_W - 110, 20 + i * 9, Math.min(90, line.length * 1.4), 3);
    }
  }

  function drawCodeLine(g, line, x, y) {
    const comment = line.indexOf('#');
    const parts = line.match(/("[^"]*"|'[^']*'|#.*$|\w+|\s+|[^\w\s])/g) || [];
    let px = x;
    let afterDef = false;
    for (const part of parts) {
      let color = '#cfd3da';
      if (part.startsWith('#')) color = '#6f9c5a';
      else if (part.startsWith('"') || part.startsWith("'")) color = '#d69a73';
      else if (/^\d/.test(part)) color = '#b3cea0';
      else if (KEYWORDS.has(part)) color = part === 'self' ? '#9cdcfe' : '#c38fd1';
      else if (afterDef && /^\w/.test(part)) color = '#e2d58f';
      else if (/^[A-Z]\w*/.test(part)) color = '#6fc2b0';
      if (/^\w/.test(part)) afterDef = part === 'def' || part === 'class';
      g.fillStyle = color;
      g.fillText(part, px, y);
      px += g.measureText(part).width;
    }
    void comment;
  }

  function drawPhoto(g) {
    // Обои: мягкая сетка градиентов, периодическая по вертикали, и чёткие элементы.
    const base = g.createLinearGradient(0, 0, 0, SCENE_H);
    base.addColorStop(0, '#0d1b3a');
    base.addColorStop(0.5, '#3a1850');
    base.addColorStop(1, '#0d1b3a');
    g.fillStyle = base;
    g.fillRect(0, 0, SCENE_W, SCENE_H);
    const blobs = [
      [0.22, 0.18, 520, '#ff7a45'], [0.78, 0.30, 560, '#3f8cff'], [0.45, 0.55, 600, '#ff4fa3'],
      [0.15, 0.82, 520, '#22c7b8'], [0.85, 0.80, 520, '#ffc24b'], [0.55, 1.05, 520, '#ff7a45'],
      [0.55, -0.05, 520, '#22c7b8'],
    ];
    g.globalCompositeOperation = 'lighter';
    for (const [bx, by, r, color] of blobs) {
      const grd = g.createRadialGradient(bx * SCENE_W, by * SCENE_H, 0, bx * SCENE_W, by * SCENE_H, r);
      grd.addColorStop(0, color + 'cc');
      grd.addColorStop(1, color + '00');
      g.fillStyle = grd;
      g.fillRect(0, 0, SCENE_W, SCENE_H);
    }
    g.globalCompositeOperation = 'source-over';
    // Крупные часы и виджеты: чёткие края, на которых видно линзу.
    g.fillStyle = 'rgba(255,255,255,0.95)';
    g.font = `200 150px ${FONT_UI}`;
    g.textAlign = 'center';
    g.fillText('21:47', SCENE_W / 2, 330);
    g.font = `500 24px ${FONT_UI}`;
    g.fillText('четверг, 25 сентября', SCENE_W / 2, 380);
    g.textAlign = 'left';
    const widgets = [[330, 520, 340, 170, 'Погода', 'Москва · +14°, ясно'], [730, 520, 340, 170, 'Календарь', '19:00 · Созвон по плашке'],
      [330, 1040, 740, 150, 'Сейчас играет', 'Nils Frahm — Says']];
    for (const [x, y, w, h, title, text] of widgets) {
      g.fillStyle = 'rgba(255,255,255,0.16)';
      roundRect(g, x, y, w, h, 26);
      g.fill();
      g.strokeStyle = 'rgba(255,255,255,0.35)';
      g.lineWidth = 1;
      g.stroke();
      g.fillStyle = 'rgba(255,255,255,0.72)';
      g.font = `600 15px ${FONT_UI}`;
      g.fillText(title.toUpperCase(), x + 26, y + 44);
      g.fillStyle = '#ffffff';
      g.font = `500 24px ${FONT_UI}`;
      g.fillText(text, x + 26, y + 90);
    }
    // Тонкие полосы у края: преломление видно лучше всего на линиях.
    g.fillStyle = 'rgba(255,255,255,0.55)';
    for (let i = 0; i < 22; i++) g.fillRect(250 + i * 42, 780, 3, 160);
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

  const SCENES = { code: drawCode, doc: drawDoc, photo: drawPhoto };
  const sceneCanvases = {};

  function sceneCanvas(mode) {
    if (!sceneCanvases[mode]) {
      const c = document.createElement('canvas');
      c.width = SCENE_W * SCENE_SCALE;
      c.height = SCENE_H * SCENE_SCALE;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.scale(SCENE_SCALE, SCENE_SCALE);
      g.textBaseline = 'alphabetic';
      SCENES[mode](g);
      sceneCanvases[mode] = c;
    }
    return sceneCanvases[mode];
  }

  /** Средняя светимость полотна в прямоугольнике (CSS px полотна): для цвета текста. */
  function sceneLuma(mode, x, y, w, h) {
    const c = sceneCanvas(mode);
    const g = c.getContext('2d', { willReadFrequently: true });
    const sx = Math.max(0, Math.floor(x * SCENE_SCALE));
    const sw = Math.max(1, Math.floor(w * SCENE_SCALE));
    const sh = Math.max(1, Math.floor(h * SCENE_SCALE));
    let sy = Math.floor((((y % SCENE_H) + SCENE_H) % SCENE_H) * SCENE_SCALE);
    if (sy + sh > c.height) sy = c.height - sh;
    const data = g.getImageData(sx, sy, Math.min(sw, c.width - sx), sh).data;
    let sum = 0;
    let n = 0;
    for (let i = 0; i < data.length; i += 4 * 7) {
      sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      n++;
    }
    return n ? sum / n / 255 : 0.5;
  }

  // ---------------------------------------------------------------- состояния

  const STAGES = {
    listening: { title: 'Слушаю', accent: '#ff5f6d', icon: 'dot' },
    transcribing: { title: 'Распознаю', accent: '#79b0ff', icon: 'dot' },
    polishing: { title: 'Причёсываю', accent: '#b79cff', icon: 'dot' },
    done: { title: 'Готово', accent: '#4fdca6', icon: 'check' },
    error: { title: 'Не расслышал', accent: '#ff6b74', icon: 'cross' },
    hidden: { title: '', accent: '#ffffff', icon: null },
  };
  const DONE_TEXT = 'Давай разберём на примере, как энкодер связан с декодером.';
  const PLAN = [['listening', 6.0], ['transcribing', 1.8], ['polishing', 1.8], ['result', 3.6], ['hidden', 1.3]];

  const clock = {
    time: 0,
    stage: 'hidden',
    prev: 'hidden',
    since: 0,
    auto: true,
    planIndex: -1,
    planLeft: 0.6,
    cycle: 0,
    recorded: 0,
  };

  function hexRgb(hex) {
    const v = parseInt(hex.slice(1), 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }

  function setStage(name) {
    clock.prev = clock.stage;
    clock.stage = name;
    clock.since = clock.time;
    if (name === 'listening') clock.recorded = 0;
    for (const fn of stageListeners) fn(name);
  }
  const stageListeners = [];

  function advanceAuto(dt) {
    if (!clock.auto) return;
    clock.planLeft -= dt;
    if (clock.planLeft > 0) return;
    clock.planIndex = (clock.planIndex + 1) % PLAN.length;
    let [name, seconds] = PLAN[clock.planIndex];
    if (name === 'result') {
      name = clock.cycle % 3 === 2 ? 'error' : 'done';
      if (name === 'error') seconds = 2.6;
      clock.cycle++;
    }
    clock.planLeft = seconds;
    setStage(name);
  }

  // ---------------------------------------------------------------- голос

  // Детерминированная «речь»: фразы из слогов 4–6 Гц с паузами, атака быстрая,
  // спад медленный — как у реального уровня RMS с микрофона.
  let seed = 7;
  function rand() {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  }
  const voice = { level: 0, raw: 0, history: new Float32Array(96), bands: new Float32Array(5), phrase: 0, syll: 0, gap: 0, amp: 0.7, rate: 5 };

  function stepVoice(dt, speaking) {
    let target = 0;
    if (speaking) {
      if (voice.gap > 0) {
        voice.gap -= dt;
      } else {
        voice.phrase -= dt;
        voice.syll += dt * voice.rate;
        const s = voice.syll % 1;
        const envelope = Math.pow(Math.sin(Math.PI * s), 1.6);
        target = voice.amp * (0.35 + 0.65 * envelope) * (0.8 + 0.2 * Math.sin(clock.time * 1.7));
        if (voice.phrase <= 0) {
          voice.gap = 0.25 + rand() * 0.55;
          voice.phrase = 1.2 + rand() * 2.4;
          voice.amp = 0.55 + rand() * 0.4;
          voice.rate = 4 + rand() * 2.2;
        }
      }
    }
    voice.raw = target;
    const k = target > voice.level ? 1 - Math.exp(-dt / 0.025) : 1 - Math.exp(-dt / 0.14);
    voice.level += (target - voice.level) * k;
    voice.history.copyWithin(0, 1);
    voice.history[voice.history.length - 1] = voice.level;
    for (let i = 0; i < voice.bands.length; i++) {
      const wobble = 0.55 + 0.45 * Math.sin(clock.time * (3.1 + i * 1.7) + i * 1.3);
      voice.bands[i] += (voice.level * wobble - voice.bands[i]) * Math.min(1, dt * 18);
    }
  }

  // ---------------------------------------------------------------- пружина

  /** Пружина в терминах SwiftUI: response (с) и dampingFraction. */
  class Spring {
    constructor(value = 0, response = 0.45, damping = 0.72) {
      this.value = value;
      this.target = value;
      this.velocity = 0;
      this.response = response;
      this.damping = damping;
    }
    set(target) { this.target = target; return this; }
    snap(value) { this.value = this.target = value; this.velocity = 0; return this; }
    step(dt) {
      const omega = (2 * Math.PI) / this.response;
      const k = omega * omega;
      const c = 2 * this.damping * omega;
      const n = Math.max(1, Math.ceil(dt / (1 / 240)));
      const h = dt / n;
      for (let i = 0; i < n; i++) {
        const a = -k * (this.value - this.target) - c * this.velocity;
        this.velocity += a * h;
        this.value += this.velocity * h;
      }
      return this.value;
    }
  }
  LG.Spring = Spring;

  // ---------------------------------------------------------------- GLSL

  LG.glsl = {};
  LG.glsl.header = `#version 300 es
precision highp float;
uniform sampler2D uScene;
uniform vec2 uRes;          // холст, device px
uniform float uDpr;
uniform vec2 uSceneSize;    // полотно, CSS px
uniform vec2 uSceneOff;     // сдвиг полотна: x — центровка, y — прокрутка (CSS px)
uniform float uSceneScale;  // текстурных px на CSS px
uniform float uTime;
out vec4 outColor;
`;

  LG.glsl.common = `
// Координаты холста в CSS px с началом в левом верхнем углу.
vec2 cssCoord(vec2 frag) { return vec2(frag.x, uRes.y - frag.y) / uDpr; }
vec2 sceneUV(vec2 css) { return (css + uSceneOff) / uSceneSize; }
vec3 sceneAt(vec2 css, float lod) { return textureLod(uScene, sceneUV(css), lod).rgb; }
// Размытие фона: мип-уровень по радиусу и 12 выборок по золотой спирали.
vec3 sceneBlur(vec2 css, float r) {
  if (r < 0.6) return sceneAt(css, 0.0);
  float lod = log2(max(r * uSceneScale * 0.45, 1.0));
  vec3 acc = vec3(0.0); float w = 0.0;
  for (int i = 0; i < 12; i++) {
    float fi = float(i);
    float a = fi * 2.39996323;
    float rr = r * sqrt((fi + 0.5) / 12.0);
    float k = 1.0 - 0.5 * fi / 12.0;
    acc += sceneAt(css + vec2(cos(a), sin(a)) * rr, lod) * k;
    w += k;
  }
  return acc / w;
}
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float sdRoundBox(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
// Капсула: центр c, полная ширина w, высота h.
float sdPill(vec2 p, vec2 c, float w, float h) { return sdRoundBox(p - c, vec2(w, h) * 0.5, h * 0.5); }
float sdCircle(vec2 p, vec2 c, float r) { return length(p - c) - r; }
// Гладкий минимум, нормированное квартичное ядро (Иниго Килес): k — наибольшее
// вздутие формы в px. Мостик между фигурами живёт при зазоре g <= 2k, влияние
// начинается с 5.33k. Для капсулы 56 px: покой 5.25, движение 7–8, не больше 10.
float smin(float a, float b, float k) {
  k = max(k, 1e-4) * (16.0 / 3.0);
  float h = max(k - abs(a - b), 0.0) / k;
  return min(a, b) - h * h * h * (4.0 - h) * k * (1.0 / 16.0);
}
float smax(float a, float b, float k) { return -smin(-a, -b, k); }
float hash21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1, 0)), u.x), mix(hash21(i + vec2(0, 1)), hash21(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + 17.1; a *= 0.5; } return s; }
`;

  // Жидкое стекло по замерам нативного Apple Liquid Glass (iOS 26 / macOS 26,
  // см. research.json → «Эталон оптики Apple в числах»). Концепт определяет
  // float shape(vec2 p) — SDF в CSS px (минус внутри) — до этого фрагмента.
  //
  // Главное: у кромки фон берётся ВНУТРЬ по нормали, амплитуда A больше зоны
  // искажения h, поэтому кромка «зеркальная» — показывает контент из глубины,
  // перевёрнутый и сжатый. Центр 1:1, без лупы. Блик — жёсткая полоса 1 px цвета
  // самого контента, усиленного vibrant-матрицей, а не белая обводка. Тени почти
  // нет; в iOS 27 вместо неё тёмная кромка, толще на торцах.
  LG.glsl.glass = `
uniform float uRefraction;   // 1 — как у Apple, 0 — как в композиторе Windows (без смещения)
struct Glass {
  float bevel;       // h: глубина зоны искажения, px (~13 для капсулы 56 px; растёт как размер^0.3)
  float amplitude;   // A: сдвиг выборки внутрь у самого края, px (~41 для 56 px)
  float dispersion;  // расхождение каналов 0..0.15 (у Apple почти ноль)
  float frost;       // σ размытия интерьера, px (iOS 26 b1 ≈ 1.8; релизы матовее)
  float gain; float lift;          // тон: out = in·gain + lift (Apple ≈ 1.015 и +0.086)
  vec3 tint; float tintAmount;
  float highlight;   // сила бликовой полосы 0..1
  vec2 light;        // направление на основной свет (экранные оси, y вниз); второй — напротив
  float darkRim;     // 0..1 тёмная кромка iOS 27 (торцы ×0.83 на 1 px, прямые ×0.92 на 0.5 px)
  float shadow; float shadowBlur; float shadowY;
  float materialize; // 0..1: стекло появляется ростом линзы, а не прозрачностью
};
Glass defaultGlass() {
  Glass g;
  g.bevel = 13.0; g.amplitude = 41.0; g.dispersion = 0.0; g.frost = 2.4;
  g.gain = 1.015; g.lift = 0.086;
  g.tint = vec3(1.0); g.tintAmount = 0.0;
  g.highlight = 1.0; g.light = normalize(vec2(0.7071, -0.7071));
  g.darkRim = 1.0;
  g.shadow = 0.035; g.shadowBlur = 30.0; g.shadowY = 8.0;
  g.materialize = 1.0;
  return g;
}
// Нормированное расстояние: в шейках smin |∇f| < 1, и полосы по сырому f расползались бы.
float shapeDist(vec2 p, out vec2 n) {
  const float e = 0.5;
  float f = shape(p);
  vec2 gr = vec2(shape(p + vec2(e, 0.0)) - shape(p - vec2(e, 0.0)), shape(p + vec2(0.0, e)) - shape(p - vec2(0.0, e))) / (2.0 * e);
  float gl = length(gr);
  n = gl > 1e-5 ? gr / gl : vec2(0.0, -1.0);
  return f / max(gl, 0.25);
}
vec2 shapeNormal(vec2 p) { vec2 n; shapeDist(p, n); return n; }
// Возвращает цвет поверх фона bg: rgb — итог, a — покрытие стеклом.
vec4 liquidGlass(vec2 p, Glass g, vec3 bg) {
  float m = clamp(g.materialize, 0.0, 1.0);
  vec2 n;
  float dist = shapeDist(p, n);
  float cover = clamp(0.5 - dist * uDpr, 0.0, 1.0);
  // Тень лежит на фоне и видна снаружи; внутри её закрывает стекло.
  float sd = shape(p - vec2(0.0, g.shadowY));
  float shadow = m * g.shadow * exp(-max(sd, 0.0) / g.shadowBlur) * smoothstep(-g.shadowBlur, 0.0, sd);
  vec3 under = bg * (1.0 - shadow);
  if (cover <= 0.0) return vec4(under, 0.0);

  float inside = max(-dist, 0.0);
  // Профиль circle-map, подогнанный к нативному стеклу (RMS 2.4 px).
  float t = clamp(1.0 - inside / g.bevel, 0.0, 1.0);
  float d = g.amplitude * m * uRefraction * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  float sigma = g.frost * m;
  vec3 col;
  if (g.dispersion * uRefraction > 0.001) {
    col.r = sceneBlur(p - n * d * (1.0 + g.dispersion), sigma).r;
    col.g = sceneBlur(p - n * d, sigma).g;
    col.b = sceneBlur(p - n * d * (1.0 - g.dispersion), sigma).b;
  } else {
    col = sceneBlur(p - n * d, sigma);
  }
  col = col * mix(1.0, g.gain, m) + g.lift * m;
  col = mix(col, g.tint, g.tintAmount * m);
  // Блик: полоса 1 px, цвет — преломлённый контент через vibrant-матрицу
  // (1.45 × насыщенность 2.07 + 0.05); два источника с противоположных углов.
  float rim = 1.0 - smoothstep(0.0, 1.0, inside);
  float w = pow(max(dot(n, g.light), 0.0), 3.0) + pow(max(-dot(n, g.light), 0.0), 3.0);
  float l = luma(col);
  vec3 vib = clamp(1.45 * (vec3(l) + 2.07 * (col - vec3(l))) + 0.05, 0.0, 1.0);
  col = mix(col, vib, rim * (0.5 + 0.5 * w) * g.highlight * m);
  // Тёмная кромка iOS 27: кривизна по разнице нормалей вдоль касательной.
  if (g.darkRim > 0.0 && inside < 1.6) {
    vec2 tg = vec2(-n.y, n.x);
    float curv = length(shapeNormal(p + tg * 2.0) - shapeNormal(p - tg * 2.0)) / 4.0;
    float ends = clamp(curv * 28.0, 0.0, 1.0);
    float width = mix(0.5, 1.0, ends);
    float mul = mix(0.925, 0.83, ends);
    float band = 1.0 - smoothstep(width * 0.6, width + 0.4, inside);
    col *= mix(1.0, mul, band * g.darkRim * m);
  }
  return vec4(mix(under, col, cover), cover);
}
`;

  LG.glsl.vertex = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

  // ---------------------------------------------------------------- WebGL

  function compile(gl, type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(sh);
      const numbered = src.split('\n').map((l, i) => `${i + 1}: ${l}`).join('\n');
      throw new Error(`Шейдер не собрался:\n${log}\n---\n${numbered.slice(0, 4000)}`);
    }
    return sh;
  }

  function makeProgram(gl, fragment, vertex = LG.glsl.vertex) {
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vertex));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fragment));
    gl.bindAttribLocation(prog, 0, 'aPos');
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('Программа не слинковалась: ' + gl.getProgramInfoLog(prog));
    const uniforms = {};
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(prog, i);
      const name = info.name.replace(/\[0\]$/, '');
      uniforms[name] = gl.getUniformLocation(prog, info.name);
    }
    return { prog, uniforms };
  }

  // ---------------------------------------------------------------- этапы и сцена на странице

  const stages = [];
  // refraction: true — линза как у Apple; false — как умеет композитор Windows без
  // внедрения в DWM (размытие, тон, блики есть, смещения фона нет).
  const settings = { scene: 'photo', scroll: true, scrollSpeed: 38, refraction: true };
  LG.settings = settings;
  LG.stageNames = STAGES;

  function makeLabel(root) {
    const label = document.createElement('div');
    label.className = 'lg-label';
    label.innerHTML = '<span class="lg-icon"></span><span class="lg-title"></span><span class="lg-detail"></span>';
    root.appendChild(label);
    return label;
  }

  const ICONS = {
    dot: '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="4.2" fill="currentColor"/></svg>',
    check: '<svg viewBox="0 0 16 16" width="15" height="15"><path d="M3.2 8.4 6.5 11.6 12.9 4.6" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    cross: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M4.2 4.2l7.6 7.6M11.8 4.2l-7.6 7.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  };

  const measureCtx = document.createElement('canvas').getContext('2d');
  function textWidth(title, detail) {
    measureCtx.font = `600 14px ${FONT_UI}`;
    let w = 24 + 16 + 10 + measureCtx.measureText(title).width + 24;
    if (detail) {
      measureCtx.font = `400 13px ${FONT_UI}`;
      w += 10 + measureCtx.measureText(detail).width;
    }
    return Math.max(210, Math.min(640, w));
  }
  LG.textWidth = textWidth;

  function stageText(name) {
    const info = STAGES[name];
    let detail = '';
    if (name === 'listening') {
      const s = Math.floor(clock.time - clock.since);
      detail = `0:${String(s).padStart(2, '0')}`;
    } else if (name === 'transcribing') detail = '5,8 с записи';
    else if (name === 'polishing') detail = 'бережно';
    else if (name === 'done') detail = DONE_TEXT;
    else if (name === 'error') detail = 'попробуйте ещё раз';
    return { title: info.title, detail };
  }

  function createStage(concept, root) {
    root.classList.add('lg-stage');
    const canvas = document.createElement('canvas');
    canvas.className = 'lg-canvas';
    root.appendChild(canvas);
    const label = makeLabel(root);
    const error = document.createElement('pre');
    error.className = 'lg-error';
    error.hidden = true;
    root.appendChild(error);

    const gl = canvas.getContext('webgl2', { antialias: false, premultipliedAlpha: false, alpha: false, preserveDrawingBuffer: false });
    const st = { concept, root, canvas, label, error, gl, visible: true, scroll: 0, userScroll: 0, texMode: null, W: 0, H: 0, dpr: 1, broken: false, lastLabel: '' };
    if (!gl) {
      fail(st, new Error('WebGL2 недоступен в этом браузере'));
      return st;
    }
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    st.vao = vao;
    st.sceneTex = gl.createTexture();

    // Колесо и перетаскивание прокручивают фон под стеклом — как в жизни.
    root.addEventListener('wheel', (e) => { st.userScroll += e.deltaY * 0.6; e.preventDefault(); }, { passive: false });
    let dragY = null;
    root.addEventListener('pointerdown', (e) => { dragY = e.clientY; root.setPointerCapture(e.pointerId); });
    root.addEventListener('pointermove', (e) => { if (dragY !== null) { st.userScroll -= e.clientY - dragY; dragY = e.clientY; } });
    root.addEventListener('pointerup', () => { dragY = null; });

    const ctx = {
      gl, canvas, root,
      get W() { return st.W; }, get H() { return st.H; }, get dpr() { return st.dpr; },
      program(fragmentBody, vertex) {
        return makeProgram(gl, fragmentBody, vertex);
      },
      /** Ставит общие юниформы полотна и рисует полноэкранный треугольник. */
      draw(program, uniforms = {}) {
        gl.useProgram(program.prog);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, st.sceneTex);
        const u = program.uniforms;
        if (u.uScene) gl.uniform1i(u.uScene, 0);
        if (u.uRes) gl.uniform2f(u.uRes, canvas.width, canvas.height);
        if (u.uDpr) gl.uniform1f(u.uDpr, st.dpr);
        if (u.uSceneSize) gl.uniform2f(u.uSceneSize, SCENE_W, SCENE_H);
        if (u.uSceneOff) gl.uniform2f(u.uSceneOff, (SCENE_W - st.W) / 2, st.scroll);
        if (u.uSceneScale) gl.uniform1f(u.uSceneScale, SCENE_SCALE);
        if (u.uTime) gl.uniform1f(u.uTime, clock.time);
        if (u.uRefraction) gl.uniform1f(u.uRefraction, settings.refraction ? 1 : 0);
        for (const [name, value] of Object.entries(uniforms)) {
          const loc = u[name];
          if (loc == null) continue;
          if (typeof value === 'number') gl.uniform1f(loc, value);
          else if (value.length === 2) gl.uniform2fv(loc, value);
          else if (value.length === 3) gl.uniform3fv(loc, value);
          else if (value.length === 4) gl.uniform4fv(loc, value);
          else gl.uniform1fv(loc, value);
        }
        gl.bindVertexArray(st.vao);
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      },
      glsl: LG.glsl,
      Spring,
    };
    st.ctx = ctx;
    try {
      concept.setup && concept.setup(ctx);
    } catch (err) {
      fail(st, err);
    }
    new IntersectionObserver((entries) => { for (const e of entries) st.visible = e.isIntersecting; }, { rootMargin: '120px' }).observe(root);
    return st;
  }

  function fail(st, err) {
    st.broken = true;
    st.error.hidden = false;
    st.error.textContent = String(err && err.message ? err.message : err);
    console.error(`[${st.concept.id}]`, err);
  }

  function uploadScene(st) {
    const gl = st.gl;
    gl.bindTexture(gl.TEXTURE_2D, st.sceneTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, sceneCanvas(settings.scene));
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    st.texMode = settings.scene;
  }

  function resize(st) {
    const rect = st.root.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (st.canvas.width !== w || st.canvas.height !== h) {
      st.canvas.width = w;
      st.canvas.height = h;
    }
    st.W = rect.width;
    st.H = rect.height;
    st.dpr = dpr;
  }

  function renderLabel(st, s, info) {
    const label = st.label;
    const show = s.stage !== 'hidden' && info.labelOpacity > 0.01 && !info.hideLabel;
    label.style.opacity = show ? String(info.labelOpacity) : '0';
    if (!show) return;
    const key = `${s.stage}|${s.text.title}|${s.text.detail}`;
    if (key !== st.lastLabel) {
      label.querySelector('.lg-icon').innerHTML = ICONS[STAGES[s.stage].icon] || '';
      label.querySelector('.lg-title').textContent = s.text.title;
      label.querySelector('.lg-detail').textContent = s.text.detail;
      st.lastLabel = key;
    }
    // Текст выбирает цвет по фону под плашкой: как адаптивный материал у Apple.
    let color = info.labelColor;
    if (!color) {
      const luma = sceneLuma(settings.scene, (SCENE_W - st.W) / 2 + info.cx - 120, st.scroll + info.cy - 20, 240, 40);
      st.luma = st.luma == null ? luma : st.luma + (luma - st.luma) * 0.15;
      // Порог по WCAG: белому тексту нужна подложка не светлее ~0.46, чёрному —
      // не темнее; стекло ещё поднимает яркость на ~0.09, отсюда 0.45 по сырому фону.
      color = st.luma > 0.45 ? 'dark' : 'light';
    }
    label.dataset.tone = color === 'dark' || color === 'light' ? color : 'custom';
    if (color !== 'dark' && color !== 'light') label.style.color = color;
    else label.style.color = '';
    label.querySelector('.lg-icon').style.color = info.iconColor || STAGES[s.stage].accent;
    const scale = info.labelScale == null ? 1 : info.labelScale;
    label.style.transform = `translate(${info.cx}px, ${info.cy}px) translate(-50%, -50%) scale(${scale})`;
    label.style.filter = info.labelBlur ? `blur(${info.labelBlur}px)` : '';
  }

  // ---------------------------------------------------------------- цикл

  let last = null;
  function loop(now) {
    const dt = last == null ? 1 / 60 : Math.min(0.05, (now - last) / 1000);
    last = now;
    clock.time += dt;
    advanceAuto(dt);
    stepVoice(dt, clock.stage === 'listening');
    const accentHex = STAGES[clock.stage].accent;
    const text = stageText(clock.stage);
    const snapshot = {
      stage: clock.stage,
      prev: clock.prev,
      t: clock.time - clock.since,
      time: clock.time,
      dt,
      level: voice.level,
      raw: voice.raw,
      history: voice.history,
      bands: voice.bands,
      text,
      targetW: textWidth(text.title, text.detail),
      accent: hexRgb(accentHex),
      accentHex,
      shown: clock.stage !== 'hidden',
      refraction: settings.refraction ? 1 : 0,
    };
    for (const st of stages) {
      if (!st.visible || st.broken) continue;
      resize(st);
      st.scroll += (settings.scroll ? settings.scrollSpeed * dt : 0) + st.userScroll;
      st.userScroll = 0;
      if (st.texMode !== settings.scene) uploadScene(st);
      try {
        const info = st.concept.frame(st.ctx, snapshot) || {};
        if (info.cx == null) info.cx = st.W / 2;
        if (info.cy == null) info.cy = st.H / 2;
        if (info.labelOpacity == null) info.labelOpacity = snapshot.shown ? 1 : 0;
        renderLabel(st, snapshot, info);
      } catch (err) {
        fail(st, err);
      }
    }
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- API

  const pending = [];
  LG.register = function (concept) {
    pending.push(concept);
    if (document.readyState !== 'loading') mountAll();
  };

  function mountAll() {
    while (pending.length) {
      const concept = pending.shift();
      const root = document.querySelector(`[data-concept="${concept.id}"]`);
      if (!root) {
        console.warn('Нет места для концепта', concept.id);
        continue;
      }
      stages.push(createStage(concept, root));
    }
  }

  LG.setScene = (mode) => { settings.scene = mode; };
  LG.setScroll = (on) => { settings.scroll = on; };
  LG.setRefraction = (on) => { settings.refraction = on; };
  LG.setAuto = (on) => {
    clock.auto = on;
    if (on) clock.planLeft = 0;
  };
  LG.show = (name) => { clock.auto = false; setStage(name); };
  LG.onStage = (fn) => stageListeners.push(fn);
  LG.clock = clock;

  document.addEventListener('DOMContentLoaded', mountAll);
  requestAnimationFrame(loop);
})();
