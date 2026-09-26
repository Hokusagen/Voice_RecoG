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
  const PLAN1 = [['listening', 6.0], ['transcribing', 1.8], ['polishing', 1.8], ['result', 3.6], ['hidden', 1.3]];

  // Второй круг. В «Готово» текста нет: он уже вставлен в окно под курсором,
  // плашка показывает только галочку, поэтому и держится короче. Реакция Дарви
  // укладывается в тот же такт (DARVI.md: не дольше секунды).
  const TITLES2 = { listening: 'Слушаю', transcribing: 'Распознаю', polishing: 'Причёсываю', done: '', error: 'Не расслышал', hidden: '' };
  const PLAN2 = [['listening', 5.0], ['transcribing', 1.6], ['polishing', 1.4], ['result', 2.2], ['hidden', 1.2]];
  // Что «продиктовано» в каждом «Готово»: по этой фразе Дарви решает, как
  // откликнуться. На плашке фразы нет, её показывает страница рядом с демо.
  const PHRASES = {
    none: 'Давай разберём на примере, как энкодер связан с декодером.',
    joy: 'Ура, всё получилось! Спасибо тебе огромное!',
    sad: 'Мне очень жаль. Держись, если что — я рядом.',
  };

  // Часы на каждый круг: у первого свой ритм и тексты, и страница второго круга
  // не должна менять, как выглядят концепты первого.
  function makeClock(round) {
    return {
      round, plan: round === 2 ? PLAN2 : PLAN1,
      time: 0, stage: 'hidden', prev: 'hidden', since: 0,
      auto: true, planIndex: -1, planLeft: 0.6, cycle: 0,
      emotion: null, voice: makeVoice(7),
    };
  }

  function hexRgb(hex) {
    const v = parseInt(hex.slice(1), 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }

  function setStage(c, name, opts = {}) {
    c.prev = c.stage;
    c.stage = name;
    c.since = c.time;
    if (name === 'listening') { c.emotion = null; startSpeech(c.voice); }
    // Эмоция живёт до следующей диктовки: уход после «Готово» — ещё часть реакции.
    if (name === 'done') c.emotion = opts.emotion || null;
    if (name === 'error') c.emotion = null;
    for (const fn of stageListeners) fn(name, { round: c.round, emotion: c.emotion, phrase: phraseOf(c) });
  }
  const stageListeners = [];

  function phraseOf(c) {
    return c.round === 2 && c.stage === 'done' ? PHRASES[c.emotion || 'none'] : '';
  }

  function advanceAuto(c, dt) {
    if (!c.auto) return;
    c.planLeft -= dt;
    if (c.planLeft > 0) return;
    c.planIndex = (c.planIndex + 1) % c.plan.length;
    let [name, seconds] = c.plan[c.planIndex];
    const opts = {};
    if (name === 'result') {
      if (c.round === 2) {
        // По кругу «Готово» чередуется: без эмоции, радость, грусть, затем ошибка.
        // Выбранная на странице реакция ставится в каждое «Готово».
        if (settings.reaction !== 'auto') {
          name = 'done';
          opts.emotion = settings.reaction === 'none' ? null : settings.reaction;
        } else {
          const k = c.cycle % 4;
          name = k === 3 ? 'error' : 'done';
          opts.emotion = [null, 'joy', 'sad', null][k];
          if (name === 'error') seconds = 2.4;
        }
      } else {
        name = c.cycle % 3 === 2 ? 'error' : 'done';
        if (name === 'error') seconds = 2.6;
      }
      c.cycle++;
    }
    c.planLeft = seconds;
    setStage(c, name, opts);
  }

  // ---------------------------------------------------------------- голос

  // Детерминированная «речь»: фразы из слогов 4–6 Гц с паузами. Генератор у
  // каждого голоса свой, чтобы снимок в замороженном времени повторялся кадр в кадр.
  function makeVoice(seed) {
    return {
      seed, time: 0,
      // первый круг: сглаживание как было — атака 25 мс, спад 140 мс
      level: 0, raw: 0, history: new Float32Array(96), bands: new Float32Array(5),
      // второй круг: окно дБ, гамма 0.7, атака 70 мс, спад 280 мс (RESEARCH.md → «Голос»)
      level2: 0, raw2: 0, speech: 0, history2: new Float32Array(96), bands2: new Float32Array(5),
      events: [], sincePeak: 9, rising: false, prevLevel2: 0, mean2: 0, talking: false,
      phrase: 0, syll: 0, gap: 0, amp: 0.7, rate: 5, stress: 1, syllIdx: 0,
    };
  }
  function rand(v) {
    v.seed = (v.seed * 16807) % 2147483647;
    return (v.seed - 1) / 2147483646;
  }
  // Человек нажал клавишу и начинает говорить не сразу: пауза перед первой фразой.
  function startSpeech(v) {
    v.gap = 0.35;
    v.phrase = 1.4 + rand(v) * 1.8;
    v.amp = 0.7 + rand(v) * 0.3;
    v.rate = 4 + rand(v) * 2.2;
  }

  const DB_LO = -56;   // пол окна: шум комнаты и дыхание уходят в ноль
  const DB_HI = -6;    // потолок: громкая речь у микрофона
  function stepVoice(v, dt, speaking) {
    v.time += dt;
    v.events.length = 0;
    let target = 0;
    const wasTalking = v.talking;
    v.talking = false;
    if (speaking) {
      if (v.gap > 0) {
        v.gap -= dt;
      } else {
        v.talking = true;
        v.phrase -= dt;
        const before = Math.floor(v.syll);
        v.syll += dt * v.rate;
        if (Math.floor(v.syll) !== before) {
          // Ударный слог раз в 3–5: громче на треть — живая речь, а не метроном.
          v.syllIdx++;
          v.stress = rand(v) < 0.28 ? 1.3 : 1;
        }
        const s = v.syll % 1;
        const envelope = Math.pow(Math.sin(Math.PI * s), 1.6);
        target = v.amp * v.stress * (0.35 + 0.65 * envelope) * (0.8 + 0.2 * Math.sin(v.time * 1.7));
        if (v.phrase <= 0) {
          v.gap = 0.25 + rand(v) * 0.55;
          v.phrase = 1.2 + rand(v) * 2.4;
          // Фразы разной громкости: тихая оговорка и уверенная фраза отличаются.
          v.amp = 0.35 + rand(v) * 0.65;
          v.rate = 4 + rand(v) * 2.2;
        }
      }
    }
    if (v.talking && !wasTalking) v.events.push({ type: 'phrase' });

    // Первый круг — как было.
    v.raw = Math.min(1, target);
    const k = v.raw > v.level ? 1 - Math.exp(-dt / 0.025) : 1 - Math.exp(-dt / 0.14);
    v.level += (v.raw - v.level) * k;
    v.history.copyWithin(0, 1);
    v.history[v.history.length - 1] = v.level;
    for (let i = 0; i < v.bands.length; i++) {
      const wobble = 0.55 + 0.45 * Math.sin(v.time * (3.1 + i * 1.7) + i * 1.3);
      v.bands[i] += (v.level * wobble - v.bands[i]) * Math.min(1, dt * 18);
    }

    // Второй круг: RMS в дБ, окно −56…−6 дБ, гамма 0.7. Речь почти всегда
    // «включена» (0.65–1), пауза уходит в ноль: голос читается фразами, а не слогами.
    const rms = 0.0015 + 0.3 * target;
    const db = 20 * Math.log10(rms);
    v.raw2 = Math.pow(Math.max(0, Math.min(1, (db - DB_LO) / (DB_HI - DB_LO))), 0.7);
    const k2 = v.raw2 > v.level2 ? 1 - Math.exp(-dt / 0.07) : 1 - Math.exp(-dt / 0.28);
    v.level2 += (v.raw2 - v.level2) * k2;
    // «Говорит сейчас»: медленный вентиль фразы — чтобы в паузах замирать.
    const ks = v.talking ? 1 - Math.exp(-dt / 0.12) : 1 - Math.exp(-dt / 0.5);
    v.speech += ((v.talking ? 1 : 0) - v.speech) * ks;
    v.history2.copyWithin(0, 1);
    v.history2[v.history2.length - 1] = v.level2;
    for (let i = 0; i < v.bands2.length; i++) {
      const wobble = 0.55 + 0.45 * Math.sin(v.time * (1.3 + i * 0.7) + i * 1.3);
      v.bands2[i] += (v.level2 * wobble - v.bands2[i]) * (1 - Math.exp(-dt / 0.12));
    }
    // Пик — вершина сглаженного уровня заметно выше среднего по фразе, не чаще
    // раза в 0.7 с: повод для редкого акцента (капля, блик), а не для реакции на
    // каждый слог. Ударные слоги и громкие фразы дают пики, ровная речь — нет.
    if (v.talking) v.mean2 += (v.level2 - v.mean2) * (1 - Math.exp(-dt / 1.2));
    v.sincePeak += dt;
    const up = v.level2 > v.prevLevel2 + 1e-5;
    const lift = v.level2 - v.mean2;
    if (v.rising && !up && v.level2 > 0.75 && lift > 0.05 && v.sincePeak > 0.7) {
      v.events.push({ type: 'peak', strength: Math.min(1, lift / 0.15) });
      v.sincePeak = 0;
    }
    v.rising = up;
    v.prevLevel2 = v.level2;
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
#ifdef LG_LENS_SHAPE
float lensDist(vec2 p, out vec2 n) {
  const float e = 0.5;
  float f = lensShape(p);
  vec2 gr = vec2(lensShape(p + vec2(e, 0.0)) - lensShape(p - vec2(e, 0.0)), lensShape(p + vec2(0.0, e)) - lensShape(p - vec2(0.0, e))) / (2.0 * e);
  float gl = length(gr);
  n = gl > 1e-5 ? gr / gl : vec2(0.0, -1.0);
  return f / max(gl, 0.25);
}
#endif
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
  // Линза может считаться от другой, гладкой формы, чем силуэт: так морф с
  // лепестками ломает свет как круг, а лепестки видны кромкой и бликом.
  // Концепт объявляет #define LG_LENS_SHAPE и float lensShape(vec2 p) до glass.
#ifdef LG_LENS_SHAPE
  vec2 nl;
  float insideL = max(-lensDist(p, nl), 0.0);
  vec2 nr = nl;
#else
  float insideL = inside;
  vec2 nr = n;
#endif
  // Профиль circle-map, подогнанный к нативному стеклу (RMS 2.4 px).
  float t = clamp(1.0 - insideL / g.bevel, 0.0, 1.0);
  float d = g.amplitude * m * uRefraction * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
  float sigma = g.frost * m;
  vec3 col;
  if (g.dispersion * uRefraction > 0.001) {
    col.r = sceneBlur(p - nr * d * (1.0 + g.dispersion), sigma).r;
    col.g = sceneBlur(p - nr * d, sigma).g;
    col.b = sceneBlur(p - nr * d * (1.0 - g.dispersion), sigma).b;
  } else {
    col = sceneBlur(p - nr * d, sigma);
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
  // reaction — реакция Дарви во втором круге: auto (по кругу) | none | joy | sad.
  // temper — темперамент Дарви: 0 — кот (спокойный), 1 — живее.
  const settings = { scene: 'photo', scroll: true, scrollSpeed: 38, refraction: true, reaction: 'auto', temper: 0 };
  LG.settings = settings;
  LG.stageNames = STAGES;
  LG.phrases = PHRASES;
  const clocks = { 1: makeClock(1), 2: makeClock(2) };

  // Замороженное время для снимков: часы основы идут фиксированным шагом до
  // нужного момента, рисуется один кадр. label: normal | text (без значка) |
  // halo (только ореол, буквы прозрачные) | none — для замера контраста.
  const frozen = { on: false, drawing: true, label: 'normal', trace: null };

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

  // Ширина содержимого подписи второго круга, без полей: значок 16 и зазоры по 10.
  // Пустые заголовок и деталь места не занимают — в «Готово» остаётся одна галочка.
  function contentWidth(title, detail) {
    let w = 16;
    measureCtx.font = `600 14px ${FONT_UI}`;
    if (title) w += 10 + measureCtx.measureText(title).width;
    if (detail) {
      measureCtx.font = `400 13px ${FONT_UI}`;
      w += 10 + measureCtx.measureText(detail).width;
    }
    return Math.ceil(w);
  }
  LG.contentWidth = contentWidth;

  function stageText(c, name) {
    let detail = '';
    if (c.round === 2) {
      if (name === 'listening') detail = `0:${String(Math.floor(c.time - c.since)).padStart(2, '0')}`;
      else if (name === 'transcribing') detail = '5,8 с';
      return { title: TITLES2[name], detail };
    }
    const info = STAGES[name];
    if (name === 'listening') {
      const s = Math.floor(c.time - c.since);
      detail = `0:${String(s).padStart(2, '0')}`;
    } else if (name === 'transcribing') detail = '5,8 с записи';
    else if (name === 'polishing') detail = 'бережно';
    else if (name === 'done') detail = DONE_TEXT;
    else if (name === 'error') detail = 'попробуйте ещё раз';
    return { title: info.title, detail };
  }

  function createStage(concept, root) {
    root.classList.add('lg-stage');
    const round = concept.round === 2 ? 2 : 1;
    root.dataset.round = String(round);
    const canvas = document.createElement('canvas');
    canvas.className = 'lg-canvas';
    root.appendChild(canvas);
    const label = makeLabel(root);
    const error = document.createElement('pre');
    error.className = 'lg-error';
    error.hidden = true;
    root.appendChild(error);

    // В замороженном времени кадр рисуется один раз и должен дожить до снимка.
    const gl = canvas.getContext('webgl2', { antialias: false, premultipliedAlpha: false, alpha: false, preserveDrawingBuffer: frozen.on });
    const st = { concept, round, root, canvas, label, error, gl, visible: true, scroll: 0, userScroll: 0, texMode: null, W: 0, H: 0, dpr: 1, broken: false, lastLabel: '' };
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
      gl, canvas, root, round,
      get W() { return st.W; }, get H() { return st.H; }, get dpr() { return st.dpr; },
      /** true, пока кадр не рисуется: замороженное время прокручивает часы до снимка. */
      get skipping() { return !frozen.drawing; },
      program(fragmentBody, vertex) {
        return makeProgram(gl, fragmentBody, vertex);
      },
      /** Ставит общие юниформы полотна и рисует полноэкранный треугольник. */
      draw(program, uniforms = {}) {
        if (!frozen.drawing) return;
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
        if (u.uTime) gl.uniform1f(u.uTime, clocks[round].time);
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
    // Второй круг, уход: галочка или подпись не пропадают в первый кадр, пока стекло
    // ещё тает ~0.25 с, а гаснут вместе с ним — с последним содержимым и на прежнем месте.
    if (st.round === 2 && s.stage === 'hidden') {
      const op = frozen.label === 'none' ? 0 : (st.lastOpacity || 0) * Math.exp(-s.t / 0.07);
      label.style.opacity = op > 0.01 ? String(op) : '0';
      return;
    }
    const show = s.stage !== 'hidden' && info.labelOpacity > 0.01 && !info.hideLabel && frozen.label !== 'none';
    label.style.opacity = show ? String(info.labelOpacity) : '0';
    st.lastOpacity = show ? info.labelOpacity : 0;
    if (!show) return;
    const key = `${s.stage}|${s.text.title}|${s.text.detail}`;
    if (key !== st.lastLabel) {
      const title = label.querySelector('.lg-title');
      const detail = label.querySelector('.lg-detail');
      label.querySelector('.lg-icon').innerHTML = ICONS[STAGES[s.stage].icon] || '';
      title.textContent = s.text.title;
      detail.textContent = s.text.detail;
      // Пустой span всё равно занимает зазор flex: галочка «Готово» съехала бы вбок.
      title.hidden = !s.text.title;
      detail.hidden = !s.text.detail;
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
    if (frozen.label === 'halo') label.style.color = 'transparent';
    else if (color !== 'dark' && color !== 'light') label.style.color = color;
    else label.style.color = '';
    const icon = label.querySelector('.lg-icon');
    icon.style.color = info.iconColor || STAGES[s.stage].accent;
    icon.style.visibility = info.hideIcon || frozen.label === 'text' || frozen.label === 'halo' ? 'hidden' : '';
    const scale = info.labelScale == null ? 1 : info.labelScale;
    label.style.transform = `translate(${info.cx}px, ${info.cy}px) translate(-50%, -50%) scale(${scale})`;
    label.style.filter = info.labelBlur ? `blur(${info.labelBlur}px)` : '';
  }

  // ---------------------------------------------------------------- цикл

  function snapshot(c, dt) {
    const v = c.voice;
    const two = c.round === 2;
    const accentHex = STAGES[c.stage].accent;
    const text = stageText(c, c.stage);
    const contentW = two ? contentWidth(text.title, text.detail) : 0;
    return {
      round: c.round,
      stage: c.stage,
      prev: c.prev,
      t: c.time - c.since,
      time: c.time,
      dt,
      level: two ? v.level2 : v.level,
      raw: two ? v.raw2 : v.raw,
      history: two ? v.history2 : v.history,
      bands: two ? v.bands2 : v.bands,
      speech: v.speech,
      events: v.events,
      text,
      contentW,
      targetW: two ? Math.max(56, Math.min(640, contentW + 48)) : textWidth(text.title, text.detail),
      accent: hexRgb(accentHex),
      accentHex,
      shown: c.stage !== 'hidden',
      refraction: settings.refraction ? 1 : 0,
      emotion: c.emotion,
      phrase: phraseOf(c),
      temper: settings.temper,
    };
  }

  const r4 = (x) => (typeof x === 'number' ? Math.round(x * 1e4) / 1e4 : x);
  function traceFrame(snap, info) {
    const extra = {};
    if (info.trace) for (const [k, v] of Object.entries(info.trace)) extra[k] = r4(v);
    frozen.trace.frames.push({
      t: r4(snap.t), level: r4(snap.level), raw: r4(snap.raw), speech: r4(snap.speech),
      events: snap.events.map((e) => e.type),
      cx: r4(info.cx), cy: r4(info.cy), label: r4(info.labelOpacity), blur: r4(info.labelBlur || 0), trace: extra,
    });
  }

  function tick(dt) {
    const snaps = {};
    for (const c of Object.values(clocks)) {
      c.time += dt;
      advanceAuto(c, dt);
      stepVoice(c.voice, dt, c.stage === 'listening');
      snaps[c.round] = snapshot(c, dt);
    }
    for (const st of stages) {
      if ((!st.visible && !frozen.on) || st.broken) continue;
      resize(st);
      st.scroll += (settings.scroll ? settings.scrollSpeed * dt : 0) + st.userScroll;
      st.userScroll = 0;
      if (st.texMode !== settings.scene) uploadScene(st);
      const snap = snaps[st.round];
      try {
        const info = st.concept.frame(st.ctx, snap) || {};
        if (info.cx == null) info.cx = st.W / 2;
        if (info.cy == null) info.cy = st.H / 2;
        if (info.labelOpacity == null) info.labelOpacity = snap.shown ? 1 : 0;
        renderLabel(st, snap, info);
        if (frozen.trace && st === stages[0]) traceFrame(snap, info);
      } catch (err) {
        fail(st, err);
      }
    }
  }

  let last = null;
  function loop(now) {
    if (!frozen.on) {
      const dt = last == null ? 1 / 60 : Math.min(0.05, (now - last) / 1000);
      last = now;
      tick(dt);
    }
    requestAnimationFrame(loop);
  }

  // Путь к стадии, как в жизни: снимок «Готово» идёт после настоящей обработки,
  // «hidden» — уход после «Готово». cold — сразу из невидимого состояния.
  const ROUTES = {
    listening: [],
    transcribing: [['listening', 2.6]],
    polishing: [['listening', 2.6], ['transcribing', 1.2]],
    done: [['listening', 2.6], ['transcribing', 1.2], ['polishing', 1.0]],
    error: [['listening', 2.6], ['transcribing', 1.2], ['polishing', 1.0]],
    hidden: [['listening', 2.6], ['transcribing', 1.2], ['polishing', 1.0], ['done', 1.8]],
  };
  const STEP = 1 / 60;

  /** Заморозить время до загрузки концепта: снимок, а не живой показ. */
  LG.freeze = function (labelMode) {
    frozen.on = true;
    if (labelMode) frozen.label = labelMode;
    document.documentElement.classList.add('lg-frozen');
  };

  /** Прогнать часы фиксированным шагом до момента t стадии stage и нарисовать один кадр. */
  LG.runTo = function ({ stage, t = 1, emotion = null, cold = false, drawAll = false, trace = false }) {
    const run = (seconds, mode) => {
      const n = Math.max(1, Math.round(seconds / STEP));
      for (let i = 0; i < n; i++) {
        frozen.drawing = drawAll || (mode === 'last' && i === n - 1);
        tick(STEP);
      }
    };
    const all = (name, opts) => { for (const c of Object.values(clocks)) setStage(c, name, opts); };
    for (const c of Object.values(clocks)) c.auto = false;
    run(0.3, 'none');
    for (const [name, seconds] of cold ? [] : ROUTES[stage]) {
      all(name, { emotion });
      run(seconds, 'none');
    }
    all(stage, { emotion });
    frozen.trace = trace ? { frames: [] } : null;
    run(t, 'last');
    frozen.drawing = true;
    if (trace) writeTrace({ stage, t, emotion, cold });
  };

  const r2 = (x) => Math.round(x * 100) / 100;
  function rectOf(el, origin) {
    const r = el.getBoundingClientRect();
    return { x: r2(r.left - origin.left), y: r2(r.top - origin.top), w: r2(r.width), h: r2(r.height) };
  }

  function writeTrace(meta) {
    const st = stages[0];
    const data = { concept: st ? st.concept.id : null, ...meta, temper: settings.temper, scene: settings.scene, frames: frozen.trace.frames };
    if (st) {
      const origin = st.root.getBoundingClientRect();
      data.stageRect = { x: r2(origin.left), y: r2(origin.top), w: r2(origin.width), h: r2(origin.height) };
      const label = st.label;
      const title = label.querySelector('.lg-title');
      const detail = label.querySelector('.lg-detail');
      const cs = (el) => { const s = getComputedStyle(el); return { color: s.color, opacity: Number(s.opacity) }; };
      const part = (el) => (el.hidden || !el.textContent ? null : { text: el.textContent, ...rectOf(el, origin), ...cs(el) });
      data.label = {
        opacity: Number(label.style.opacity || 0), tone: label.dataset.tone || '', color: getComputedStyle(label).color,
        box: rectOf(label, origin), title: part(title), detail: part(detail),
      };
      data.error = st.broken ? st.error.textContent.slice(0, 2000) : null;
    }
    const pre = document.createElement('pre');
    pre.id = 'lg-trace';
    pre.hidden = true;
    pre.textContent = JSON.stringify(data);
    document.body.appendChild(pre);
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

  LG.mount = mountAll;
  LG.setScene = (mode) => { settings.scene = mode; };
  LG.setScroll = (on) => { settings.scroll = on; };
  LG.setRefraction = (on) => { settings.refraction = on; };
  LG.setAuto = (on) => {
    for (const c of Object.values(clocks)) {
      c.auto = on;
      if (on) c.planLeft = 0;
    }
  };
  // Кнопка «Готово» на странице берёт реакцию из переключателя.
  LG.show = (name, opts = {}) => {
    if (name === 'done' && opts.emotion === undefined) {
      opts = { ...opts, emotion: settings.reaction === 'joy' || settings.reaction === 'sad' ? settings.reaction : null };
    }
    for (const c of Object.values(clocks)) {
      c.auto = false;
      setStage(c, name, opts);
    }
  };
  LG.setReaction = (r) => { settings.reaction = r; };
  LG.setTemper = (v) => { settings.temper = v; };
  LG.onStage = (fn) => stageListeners.push(fn);
  LG.clock = clocks[1];
  LG.clocks = clocks;

  document.addEventListener('DOMContentLoaded', mountAll);
  requestAnimationFrame(loop);
})();
