"""Слепой замер ответов Дарви: python src/ask_eval.py <команда>

    questions   собрать набор вопросов из журнала диктовок, если его ещё нет
    run [имя…]  прогнать набор через кандидатов из candidates.json — всех или названных
    report      страница для слепой оценки всех прогонов по набору, откроется в браузере

Зачем вслепую. Модель выбирают по впечатлению от ответов, а впечатление легко
подкрутить знанием, кто отвечал: «это же 120b, значит, лучше». На странице
ответы перемешаны и подписаны буквами; кто есть кто, открывается кнопкой уже
после оценки, вместе со сводкой по кандидатам.

Всё лежит рядом с журналом, в каталоге ask_eval: вопросы личные, ключи чужих
серверов тоже, поэтому в репозиторий отсюда не попадает ничего. Кандидат — это
сервер, модель и глубина раздумий; сервер без url — тот же, что у правки.
Вопросы идут через тот же Asker, что и в приложении: мерим код, который
работает, а не его копию.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import re
import sys
import time
from pathlib import Path

from config import AskConfig, Config, app_data_dir
from core.ask import Asker, AskFailed, Turn
from core.cloud import CloudClient

ROOT = app_data_dir() / "ask_eval"
QUESTIONS = ROOT / "questions.txt"
CANDIDATES = ROOT / "candidates.json"
RUNS = ROOT / "runs"

#: Стартовый набор кандидатов: то, что бесплатно есть на ключе Groq. Чужие
#: серверы дописываются в файл руками: url, api_key, model, effort.
DEFAULT_CANDIDATES = {
    "gpt-oss-120b · low": {"model": "openai/gpt-oss-120b", "effort": "low"},
    "gpt-oss-120b · medium": {"model": "openai/gpt-oss-120b", "effort": "medium"},
    "gpt-oss-120b · high": {"model": "openai/gpt-oss-120b", "effort": "high"},
    "gpt-oss-20b · medium": {"model": "openai/gpt-oss-20b", "effort": "medium"},
}

#: Похоже на вопрос: знак вопроса или вопросительное слово в начале.
_QUESTION = re.compile(
    r"\?|^(что|как|почему|зачем|объясни|расскажи|чем|какой|какая|какие|сколько|где|"
    r"когда|можно ли|есть ли|подскажи)\b",
    re.IGNORECASE,
)

#: Вопрос в то же окно не позже этого после предыдущего — уточнение к нему.
_CHAIN_S = 180

#: Длиннее — это уже постановка задачи агенту, а не вопрос.
_MAX_CHARS = 400


# ---------- набор вопросов ----------


def harvest(rows: list[dict]) -> list[list[str]]:
    """Цепочки вопросов из журнала: вопрос и уточнения к нему.

    Грубо и с запасом: в набор попадут и просьбы к агентам со знаком вопроса.
    Чистит набор человек — файл для того и текстовый.
    """
    chains: list[list[str]] = []
    last: tuple[str, float] | None = None
    for row in rows:
        if row.get("kind", "dictation") != "dictation":
            continue
        text = " ".join((row.get("final") or "").split())
        if not text or len(text) > _MAX_CHARS or not _QUESTION.search(text):
            continue
        at = time.mktime(time.strptime(row["at"], "%Y-%m-%dT%H:%M:%S"))
        app = row.get("app", "")
        if last is not None and last[0] == app and at - last[1] < _CHAIN_S:
            chains[-1].append(text)
        else:
            chains.append([text])
        last = (app, at)
    return chains


def read_questions(path: Path = QUESTIONS) -> list[list[str]]:
    """Строка — вопрос, «+ » в начале — уточнение к вопросу выше, «#» — комментарий."""
    chains: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("+") and chains:
            chains[-1].append(line[1:].strip())
        else:
            chains.append([line.lstrip("+").strip()])
    return chains


def cmd_questions() -> int:
    if QUESTIONS.exists():
        chains = read_questions()
        print(f"Набор уже есть: {QUESTIONS}")
        print(f"  {len(chains)} разговоров, {sum(map(len, chains))} вопросов")
        return 0
    journal = app_data_dir() / "dictations.jsonl"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    chains = harvest(rows)
    ROOT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Вопросы для замера ответов Дарви — собраны из журнала диктовок, почистить руками.",
        "# Строка — вопрос. «+ » в начале — уточнение к вопросу выше, в том же разговоре.",
        "# Строки с «#» не читаются. Лишнее удалить, своё дописать.",
        "",
    ]
    for chain in chains:
        lines.append(chain[0])
        lines.extend(f"+ {text}" for text in chain[1:])
    QUESTIONS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Собрал {len(chains)} разговоров в {QUESTIONS} — почистите перед прогоном.")
    return 0


# ---------- прогон ----------


def load_candidates() -> dict[str, dict]:
    if not CANDIDATES.exists():
        ROOT.mkdir(parents=True, exist_ok=True)
        CANDIDATES.write_text(json.dumps(DEFAULT_CANDIDATES, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Создал {CANDIDATES} с кандидатами Groq; чужие серверы дописываются туда же.")
    return json.loads(CANDIDATES.read_text(encoding="utf-8"))


def make_asker(cfg: Config, spec: dict) -> Asker:
    ask = dataclasses.replace(
        cfg.ask,
        url=spec.get("url", ""),
        api_key=spec.get("api_key", ""),
        model=spec["model"],
        reasoning_effort=spec.get("effort", ""),
        max_tokens=int(spec.get("max_tokens", cfg.ask.max_tokens)),
        keep_audio=False,
    )
    return Asker(ask, CloudClient(cfg.cloud, cfg.llm, ask))


#: «…сброс через 7 с» в тексте отказа по лимиту.
_RESET = re.compile(r"сброс через (\d+)")

#: Отказы, которые проходят сами: минутный лимит, перегрузка, тишина в ответ.
_PASSING = ("лимит", "ответило 503", "ответило 500", "вовремя", "оборвало")


def ask_patiently(asker: Asker, question: str, conversation) -> dict:
    """Один вопрос с ожиданием отказов, которые проходят сами.

    Замер не должен мерить очередь отказов. Исключение — кончившаяся квота на
    сутки: ждать её минутами бесполезно, а каждая попытка её же и тратит, —
    тогда кандидат выбывает из прогона до следующего запуска.
    """
    for attempt in range(5):
        try:
            answer = asker.ask(question, conversation)
        except AskFailed as exc:
            message = str(exc)
            if "квота" in message:
                return {"error": message, "spent": True}
            if not any(mark in message for mark in _PASSING) or attempt == 4:
                return {"error": message}
            match = _RESET.search(message)
            wait = int(match.group(1)) + 2 if match else 15 * (attempt + 1)
            print(f"    {message}; жду {wait} с")
            time.sleep(wait)
            continue
        return {
            "answer": answer.text,
            "first_s": round(answer.first_s, 2),
            "took_s": round(answer.took_s, 2),
            "prompt_tokens": answer.prompt_tokens,
            "completion_tokens": answer.completion_tokens,
            "reasoning_tokens": answer.reasoning_tokens,
            "truncated": answer.truncated,
        }
    return {"error": "не дождался лимита"}


def collect(chains: list[list[str]]) -> tuple[dict[tuple[int, int, str], dict], str]:
    """Ответы всех прогонов по нынешнему набору: (разговор, ход, кандидат) -> строка.

    Удачный ответ побеждает отказ, свежий — старый: повторный прогон затем и
    нужен, чтобы закрыть дыры, а не чтобы отказ затёр готовый ответ. Второе —
    имя первого прогона: ключ оценок в браузере.
    """
    wanted = {
        (number, turn): question
        for number, chain in enumerate(chains, 1)
        for turn, question in enumerate(chain, 1)
    }
    rows: dict[tuple[int, int, str], dict] = {}
    first_run = ""
    for run in sorted(RUNS.glob("*.jsonl")) if RUNS.exists() else []:
        for line in run.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # Прогон по прежней редакции набора сюда не попадает.
            if wanted.get((row["chain"], row["turn"])) != row["question"]:
                continue
            key = (row["chain"], row["turn"], row["candidate"])
            if "answer" in row or "answer" not in rows.get(key, {}):
                rows[key] = row
            first_run = first_run or run.stem
    return rows, first_run


def cmd_run(names: list[str]) -> int:
    if not QUESTIONS.exists():
        print("Набора вопросов нет: сначала python src/ask_eval.py questions")
        return 1
    cfg = Config.load()
    candidates = load_candidates()
    unknown = [name for name in names if name not in candidates]
    if unknown:
        print("Нет таких кандидатов: " + ", ".join(unknown))
        print("Есть: " + ", ".join(candidates))
        return 1
    chosen = {name: candidates[name] for name in (names or candidates)}
    # Свой сервер без ключа пропускаем: иначе вопрос ушёл бы на серверы
    # правки с чужим именем модели и записался бы в прогон отказом.
    keyless = [name for name, spec in chosen.items() if spec.get("url") and not spec.get("api_key", "").strip()]
    for name in keyless:
        print(f"Пропускаю «{name}»: нет api_key")
        del chosen[name]
    if not chosen:
        return 1
    askers = {name: make_asker(cfg, spec) for name, spec in chosen.items()}
    chains = read_questions()
    # Спрашиваем только то, на что ответа ещё нет: у Gemini бесплатно двадцать
    # запросов в сутки, и повторять готовое значило бы недобрать новое.
    done, _ = collect(chains)
    spent: set[str] = set()

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / (time.strftime("%Y%m%d-%H%M") + ".jsonl")
    print(f"{len(chains)} разговоров × {len(chosen)} кандидатов → {out.name}")
    asked = 0
    with out.open("w", encoding="utf-8") as handle:
        # Кандидаты по очереди внутри разговора, а не весь набор подряд:
        # лимиты у Groq на модель, и так они тратятся равномерно.
        for number, chain in enumerate(chains, 1):
            print(f"[{number}/{len(chains)}] {chain[0][:70]}")
            for name, asker in askers.items():
                if name in spent:
                    continue
                # Каждый разговор — с чистого листа, как после закрытой карточки.
                asker.close()
                conversation = asker.conversation()
                for turn, question in enumerate(chain, 1):
                    if len(conversation.turns) < turn - 1:
                        break  # прошлый ход остался без ответа — уточнять нечего
                    have = done.get((number, turn, name))
                    if have is not None and "answer" in have:
                        # Готовый ответ — в историю разговора, как будто его
                        # только что дали: уточнение должно видеть именно его.
                        conversation.turns.append(Turn(question, have["answer"]))
                        continue
                    row = {"candidate": name, "chain": number, "turn": turn, "question": question}
                    row.update(ask_patiently(asker, question, conversation))
                    asked += 1
                    if row.pop("spent", False):
                        spent.add(name)
                        print(f"    {name}: {row['error']} — до следующего запуска")
                        break
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    took = f"{row['took_s']:.1f} с" if "took_s" in row else row["error"]
                    print(f"    {name}: {took}")
    if out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        print("Новых ответов нет." if asked else "Все ответы уже есть.")
    print("Страница для оценки: python src/ask_eval.py report")
    return 0


# ---------- страница ----------


def cmd_report() -> int:
    """Одна страница на набор вопросов: ответы всех прогонов по нему.

    Новый кандидат прогоняется один и ложится на ту же страницу к уже
    оценённым — оценки в браузере привязаны к вопросу и кандидату, а не к
    прогону, и переоценивать старых не нужно.
    """
    if not QUESTIONS.exists():
        print("Набора вопросов нет: сначала python src/ask_eval.py questions")
        return 1
    latest, first_run = collect(read_questions())
    if not latest:
        print("Ни один прогон не совпадает с нынешним набором вопросов: python src/ask_eval.py run")
        return 1

    items: dict[tuple[int, int], dict] = {}
    for row in latest.values():
        key = (row["chain"], row["turn"])
        item = items.setdefault(key, {"chain": row["chain"], "turn": row["turn"], "question": row["question"], "answers": []})
        item["answers"].append(row)

    history: dict[int, list[str]] = {}
    ordered = []
    for key in sorted(items):
        item = items[key]
        item["before"] = list(history.get(item["chain"], []))
        history.setdefault(item["chain"], []).append(item["question"])
        # Порядок ответов свой у каждого вопроса, но один и тот же при
        # пересборке страницы с теми же кандидатами.
        random.Random(f"{first_run}/{key}").shuffle(item["answers"])
        for letter, answer in zip("АБВГДЕЖЗИКЛМН", item["answers"]):
            answer["letter"] = letter
            answer["id"] = f"{key[0]}.{key[1]}.{answer['candidate']}"
        ordered.append(item)

    # Имя первого прогона — ключ оценок в браузере: с ним страница, дополненная
    # новым кандидатом, видит оценки, поставленные до этого.
    data = {"run": first_run, "items": ordered}
    page = ROOT / f"report-{first_run}.html"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page.write_text(_PAGE.replace("/*DATA*/null", payload), encoding="utf-8")
    print(f"Страница: {page}")
    if sys.platform == "win32":
        os.startfile(page)
    return 0


_PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ответы Дарви вслепую</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"></script>
<style>
:root{--bg:#f6f5f2;--card:#fff;--text:#1d1d1b;--muted:#6b6a65;--line:#dedcd5;--accent:#2f6fde;--bad:#c4402f;--good:#1f8a5b}
@media (prefers-color-scheme:dark){:root{--bg:#191917;--card:#22221f;--text:#ecebe6;--muted:#a3a29b;--line:#3a3934;--accent:#7aa7ff;--bad:#ff8a7a;--good:#5fd39b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header b{font-weight:600}main{max-width:1280px;margin:0 auto;padding:16px}
.q{margin:0 0 36px}.q h2{font-size:17px;font-weight:600;margin:0 0 4px}.before{color:var(--muted);font-size:13px;margin:0 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.a{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column}
.a.best{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:6px}
.letter{font-weight:700;font-size:16px}.who{color:var(--muted);font-size:12px;display:none}.revealed .who{display:inline}
.body{flex:1;overflow-wrap:anywhere}.body p{margin:0 0 8px}.body ul,.body ol{margin:0 0 8px;padding-left:20px}
.body pre{background:var(--bg);padding:8px;border-radius:6px;overflow:auto;font-size:13px}.body code{font-size:13px}
.err{color:var(--bad)}.ctl{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;background:none;color:var(--text);padding:3px 8px;font:inherit;font-size:13px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}.seg button.on{background:var(--accent);color:#fff}
.seg.bad button.on{background:var(--bad)}button.star{border:1px solid var(--line);border-radius:8px;background:none;color:var(--text);font:inherit;font-size:13px;padding:3px 8px;cursor:pointer}
button.star.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.act{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:8px;padding:5px 12px;font:inherit;cursor:pointer}
.stats{color:var(--muted);font-size:12px;display:none;margin-top:6px}.revealed .stats{display:block}
table{border-collapse:collapse;margin:8px 0 24px;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:4px 10px;text-align:right}td:first-child,th:first-child{text-align:left}
#summary{display:none}.revealed #summary{display:block}
</style></head><body>
<header><b>Ответы Дарви вслепую</b><span id="progress"></span>
<button class="act" id="reveal">Показать модели</button><button class="act" id="copy">Скопировать оценки</button>
<span id="note" style="color:var(--muted);font-size:13px"></span></header>
<main><section id="summary"></section><div id="list"></div></main>
<script>
const DATA = /*DATA*/null;
const KEY = "ask-eval-" + DATA.run;
let marks = {};
try { marks = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) {}
marks.items = marks.items || {}; marks.best = marks.best || {};
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch (e) {} update(); };

const MATH = /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$/g;
function render(md) {
  const kept = [];
  const safe = md.replace(MATH, m => { kept.push(m); return "@@" + (kept.length - 1) + "@@"; });
  return marked.parse(safe).replace(/@@(\d+)@@/g, (_, i) => kept[+i].replace(/&/g, "&amp;").replace(/</g, "&lt;"));
}
function seg(values, current, onPick, cls) {
  const box = document.createElement("span"); box.className = "seg " + (cls || "");
  for (const v of values) {
    const b = document.createElement("button"); b.textContent = v; if (v === current) b.classList.add("on");
    b.onclick = () => { onPick(current === v ? null : v); }; box.appendChild(b);
  }
  return box;
}
function draw() {
  const list = document.getElementById("list"); list.innerHTML = "";
  for (const item of DATA.items) {
    const qid = item.chain + "." + item.turn;
    const sec = document.createElement("section"); sec.className = "q";
    const h = document.createElement("h2");
    h.textContent = (item.turn > 1 ? "Уточнение · " : "") + item.question; sec.appendChild(h);
    if (item.before.length) { const p = document.createElement("p"); p.className = "before"; p.textContent = "До этого: " + item.before.join(" → "); sec.appendChild(p); }
    const grid = document.createElement("div"); grid.className = "grid";
    for (const a of item.answers) {
      const m = marks.items[a.id] || {};
      const card = document.createElement("div"); card.className = "a" + (marks.best[qid] === a.id ? " best" : "");
      card.innerHTML = '<div class="head"><span class="letter">' + a.letter + '</span><span class="who"></span></div><div class="body"></div><div class="stats"></div><div class="ctl"></div>';
      card.querySelector(".who").textContent = a.candidate;
      const body = card.querySelector(".body");
      if (a.error) { body.innerHTML = '<p class="err"></p>'; body.firstChild.textContent = "Ошибка: " + a.error; }
      else body.innerHTML = render(a.answer);
      if (!a.error) card.querySelector(".stats").textContent =
        "первое слово " + a.first_s.toFixed(1) + " с · ответ " + a.took_s.toFixed(1) + " с · " + a.completion_tokens + " ток. (раздумья " + a.reasoning_tokens + ")" + (a.truncated ? " · ОБОРВАН" : "");
      const ctl = card.querySelector(".ctl");
      ctl.appendChild(seg(["верно", "ошибка"], m.ok, v => { marks.items[a.id] = { ...m, ok: v }; save(); draw(); }, m.ok === "ошибка" ? "bad" : ""));
      ctl.appendChild(seg(["мало", "в самый раз", "много"], m.size, v => { marks.items[a.id] = { ...m, size: v }; save(); draw(); }));
      const star = document.createElement("button"); star.className = "star" + (marks.best[qid] === a.id ? " on" : ""); star.textContent = "лучший";
      star.onclick = () => { marks.best[qid] = marks.best[qid] === a.id ? undefined : a.id; save(); draw(); };
      ctl.appendChild(star);
      grid.appendChild(card);
    }
    sec.appendChild(grid); list.appendChild(sec);
  }
  if (window.renderMathInElement) renderMathInElement(list, { delimiters: [
    { left: "$$", right: "$$", display: true }, { left: "\\[", right: "\\]", display: true },
    { left: "$", right: "$", display: false }, { left: "\\(", right: "\\)", display: false }], throwOnError: false });
  update();
}
function median(xs) { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function update() {
  let total = 0, done = 0;
  const per = {};
  for (const item of DATA.items) for (const a of item.answers) {
    total++; const m = marks.items[a.id] || {}; if (m.ok && m.size) done++;
    const p = per[a.candidate] = per[a.candidate] || { n: 0, ok: 0, bad: 0, little: 0, fit: 0, much: 0, best: 0, first: [], took: [], think: [], cut: 0, fail: 0 };
    p.n++; if (m.ok === "верно") p.ok++; if (m.ok === "ошибка") p.bad++;
    if (m.size === "мало") p.little++; if (m.size === "в самый раз") p.fit++; if (m.size === "много") p.much++;
    if (marks.best[item.chain + "." + item.turn] === a.id) p.best++;
    if (a.error) p.fail++; else { p.first.push(a.first_s); p.took.push(a.took_s); p.think.push(a.reasoning_tokens); if (a.truncated) p.cut++; }
  }
  document.getElementById("progress").textContent = "оценено " + done + " из " + total;
  const rows = Object.entries(per).map(([name, p]) =>
    "<tr><td>" + name + "</td><td>" + p.ok + "</td><td>" + p.bad + "</td><td>" + p.little + " / " + p.fit + " / " + p.much + "</td><td>" + p.best +
    "</td><td>" + (median(p.first) ?? 0).toFixed(1) + "</td><td>" + (median(p.took) ?? 0).toFixed(1) + "</td><td>" + Math.round(median(p.think) ?? 0) + "</td><td>" + p.cut + "</td><td>" + p.fail + "</td></tr>").join("");
  document.getElementById("summary").innerHTML =
    "<table><tr><th>Кандидат</th><th>верно</th><th>ошибка</th><th>мало / в самый раз / много</th><th>лучший</th><th>первое слово, с</th><th>ответ, с</th><th>раздумья, ток.</th><th>оборван</th><th>отказ</th></tr>" + rows + "</table>";
}
document.getElementById("reveal").onclick = () => document.body.classList.toggle("revealed");
document.getElementById("copy").onclick = async () => {
  const out = { run: DATA.run, items: {}, best: {} };
  for (const item of DATA.items) for (const a of item.answers) { const m = marks.items[a.id]; if (m) out.items[a.letter + " " + a.id] = m; }
  for (const [q, id] of Object.entries(marks.best)) if (id) out.best[q] = id;
  const text = JSON.stringify(out);
  try { await navigator.clipboard.writeText(text); document.getElementById("note").textContent = "скопировано"; }
  catch (e) { prompt("Скопируйте оценки:", text); }
};
draw();
</script></body></html>
"""


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "questions":
        return cmd_questions()
    if command == "run":
        return cmd_run(argv[2:])
    if command == "report":
        return cmd_report()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
