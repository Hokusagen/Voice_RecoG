"""Формулы в ответах Дарви: LaTeX модели — в строку текста, которая не рвётся.

Модели пишут формулы в LaTeX по привычке: в прогонах ask_eval 6.10 так писали и
gpt-oss, и Gemini, и Ministral, а юникодный текст, который промпт просил взамен,
в узкой карточке переносился посреди формулы. Поэтому LaTeX разрешён, а
формулу набираем сами: переменные курсивом, индексы настоящие, греческие буквы
и знаки — символами, дробь — через косую черту. Дробь в два этажа — уже
настоящий набор: библиотека и шрифт, их вес не замерен.

Здесь только разбор, без Qt. Тот же разбор даёт плоский текст — для вставки в
окно и для подсказки Whisper.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

NBSP = "\u00a0"


@dataclass
class Formula:
    latex: str
    display: bool
    """Стоит отдельной строкой: карточка ставит её по центру."""


@dataclass
class Run:
    """Кусок набранной формулы с одним видом."""

    text: str
    italic: bool = False
    bold: bool = False
    script: int = 0
    """1 — верхний индекс, −1 — нижний."""


# ---------- где формулы в тексте ----------

#: Метка формулы на время разбора Markdown. Символы из личной области юникода
#: разбор не тронет, а в ответах модели их не бывает. Без меток Markdown съел бы
#: LaTeX сам: «x_i и y_j» — курсив, «\(» — экранированная скобка.
_MARK = re.compile("\ue000(\\d+)\ue001")

#: Код не трогаем: «$Sprite.texture» в Godot — не формула.
_CODE = re.compile(r"(```|~~~).*?(?:\1|\Z)|`[^`\n]+`", re.S)

#: Одиночный доллар — по правилам Pandoc: после открывающего не пробел, перед
#: закрывающим не пробел, и за ним не цифра. Иначе «0,10 $/млн … 0,50 $/млн»
#: из ответа про цены стал бы формулой.
_MATH = re.compile(
    r"\$\$(?P<d1>.+?)\$\$"
    r"|\\\[(?P<d2>.+?)\\\]"
    r"|\\\((?P<i1>.+?)\\\)"
    r"|(?<![\\$\w])\$(?=[^\s$])(?P<i2>[^$\n]+?)(?<=\S)\$(?!\d)",
    re.S,
)

#: Два русских слова подряд вне \text{} — это проза между двумя долларами,
#: а не формула: «0,50 $/млн и формула ($\sigma$)» правила Pandoc пропускают.
_PROSE = re.compile(r"[А-Яа-яЁё]+\s+[А-Яа-яЁё]+")
_TEXT_ARG = re.compile(r"\\(?:text\w*|mbox|operatorname)\{[^{}]*\}")


def mark(index: int) -> str:
    return f"\ue000{index}\ue001"


def split(markdown: str, partial: bool = False) -> tuple[str, list[Formula]]:
    """Текст с метками вместо формул и сами формулы по порядку меток.

    partial — ответ ещё идёт потоком: незакрытую формулу в хвосте прячем,
    иначе она мелькает сырым LaTeX, пока не придёт закрывающий знак.
    """
    found: list[Formula] = []
    parts: list[str] = []
    last = 0
    for code in _CODE.finditer(markdown):
        parts.append(_marked(markdown[last:code.start()], found))
        parts.append(code.group(0))
        last = code.end()
    tail = _marked(markdown[last:], found)
    if partial:
        tail = tail[:_unfinished(tail)]
    parts.append(tail)
    return "".join(parts), found


#: Начало формулы, которой ещё нет конца. Закрытые к этому времени уже стали
#: метками, так что любой оставшийся «$$», «\[» или «\(» — незакрытый. Одиночный
#: доллар — если за ним не цифра и до конца строки нет второго: «$5» — цена, а
#: если «$» окажется не формулой, строка покажется целиком, как только кончится.
_OPENED = re.compile(r"\$\$|\\\[|\\\(|(?<![\\$\w])\$(?=[^\s\d]|\Z)[^$\n]*\Z")


def _unfinished(text: str) -> int:
    match = _OPENED.search(text)
    return len(text) if match is None else match.start()


def _marked(text: str, found: list[Formula]) -> str:
    parts: list[str] = []
    last = pos = 0
    while (match := _MATH.search(text, pos)) is not None:
        single = match.group("i2")
        if single is not None and _PROSE.search(_TEXT_ARG.sub("", single)):
            # Не формула. Ищем дальше со следующего знака: закрывающий доллар
            # ложной пары может открывать настоящую формулу.
            pos = match.start() + 1
            continue
        latex = next(group for group in match.group("d1", "d2", "i1", "i2") if group is not None)
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        before = text[start:match.start()]
        after = text[match.end():len(text) if end < 0 else end]
        # Выносная формула — только если строка её целиком: тогда она своим
        # абзацем, с тем же отступом, чтобы не выпасть из пункта списка.
        alone = match.group("d1", "d2") != (None, None) and not before.strip() and not after.strip()
        found.append(Formula(latex.strip(), alone))
        placeholder = mark(len(found) - 1)
        parts.append(text[last:match.start()])
        parts.append(f"\n\n{before}{placeholder}\n" if alone else placeholder)
        last = pos = match.end()
    parts.append(text[last:])
    return "".join(parts)


def unmark(text: str, found: list[Formula]) -> str:
    """Метки в готовом тексте — обратно формулами, уже плоским текстом."""
    return _MARK.sub(lambda m: plain(found[int(m.group(1))].latex), text)


def to_plain(markdown: str) -> str:
    """Весь текст с формулами плоским текстом, без разбора Markdown."""
    return unmark(*split(markdown))


# ---------- набор одной формулы ----------

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π", "varpi": "ϖ",
    "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_RELATIONS = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈",
    "sim": "∼", "simeq": "≃", "cong": "≅", "equiv": "≡", "propto": "∝", "ll": "≪", "gg": "≫",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "supseteq": "⊇", "to": "→", "rightarrow": "→", "longrightarrow": "⟶", "leftarrow": "←",
    "gets": "←", "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "leftrightarrow": "↔", "iff": "⇔", "implies": "⇒", "mapsto": "↦", "perp": "⊥",
    "parallel": "∥", "mid": "∣", "coloneqq": "≔", "triangleq": "≜", "doteq": "≐",
    "prec": "≺", "succ": "≻", "models": "⊨", "vdash": "⊢",
}
_OPERATORS = {
    "cdot": "·", "cdotp": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗",
    "star": "⋆", "circ": "∘", "bullet": "•", "oplus": "⊕", "otimes": "⊗", "odot": "⊙",
    "cup": "∪", "cap": "∩", "setminus": "∖", "wedge": "∧", "land": "∧", "vee": "∨",
    "lor": "∨", "bmod": "mod",
}
_ORDINARY = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀", "exists": "∃", "nexists": "∄",
    "emptyset": "∅", "varnothing": "∅", "neg": "¬", "lnot": "¬", "ldots": "…", "dots": "…",
    "cdots": "⋯", "vdots": "⋮", "ddots": "⋱", "prime": "′", "top": "⊤", "bot": "⊥",
    "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "angle": "∠",
    "triangle": "△", "square": "□", "dagger": "†", "degree": "°", "backslash": "\\",
    "vert": "|", "Vert": "‖", "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
}
_OPEN = {"langle": "⟨", "lfloor": "⌊", "lceil": "⌈", "lbrace": "{"}
_CLOSE = {"rangle": "⟩", "rfloor": "⌋", "rceil": "⌉", "rbrace": "}"}
_BIG = {
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭",
    "oint": "∮", "bigcup": "⋃", "bigcap": "⋂", "bigoplus": "⨁", "bigotimes": "⨂",
    "bigvee": "⋁", "bigwedge": "⋀",
}
_FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh",
    "tanh", "coth", "ln", "log", "lg", "exp", "max", "min", "sup", "inf", "lim", "liminf",
    "limsup", "arg", "det", "dim", "ker", "deg", "gcd", "Pr", "hom",
}
_ACCENTS = {
    "hat": "\u0302", "widehat": "\u0302", "bar": "\u0304", "overline": "\u0305",
    "tilde": "\u0303", "widetilde": "\u0303", "vec": "\u20d7", "dot": "\u0307",
    "ddot": "\u0308", "check": "\u030c", "acute": "\u0301", "grave": "\u0300", "breve": "\u0306",
}
_BLACKBOARD = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "E": "𝔼", "P": "ℙ", "1": "𝟙"}
#: Рукописные буквы — только те, что есть в основной плоскости юникода: их
#: знают обычные шрифты. ℒ — функция потерь, её в ML пишут именно так.
_CALLIGRAPHIC = {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ", "L": "ℒ", "M": "ℳ", "R": "ℛ"}
_TEXT = {"text", "textrm", "textnormal", "textup", "textsf", "texttt", "mbox", "hbox"}
_UPRIGHT = {"mathrm", "mathsf", "mathtt", "mathfrak"}
_BOLD_ITALIC = {"boldsymbol", "bm", "pmb"}
"""\\mathbf в TeX прямой — так пишут векторы; курсивный жирный — \\boldsymbol."""

_SIZERS = {
    "left", "right", "middle", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr",
    "biggl", "biggr", "Biggl", "Biggr",
}
_IGNORED = {
    "displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "not", "nonumber",
    "notag", "it", "bf", "rm", "cal",
}
_SPACES = {",", ":", ";", " ", ">", "quad", "qquad", "enspace", "thinspace"}
_ESCAPED = {"{": ("{", "open"), "}": ("}", "close"), "|": ("‖", "ord"), "%": ("%", "ord"),
            "_": ("_", "ord"), "&": ("&", "ord"), "#": ("#", "ord"), "$": ("$", "ord")}

_SUP = dict(zip(
    "0123456789+−-=()niabcdefghijklmoprstuvwxyzABDEGHIJKLMNOPRTUVW⊤′",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂᵀ′",
))
_SUB = dict(zip("0123456789+−-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"))

_TOKEN = re.compile(r"\\([A-Za-z]+)\*?|\\(.)|(\s+)|(.)", re.S)

#: После этих атомов минус — вычитание, а не знак числа.
_OPERAND = {"var", "num", "close", "ord", "text", "group"}


def runs(latex: str) -> list[Run]:
    """Формула кусками для карточки: курсив, жирный, индексы."""
    out = _Out()
    _render(_Parser(latex).sequence(), out, script=0, italic=True, bold=False)
    return out.runs


def plain(latex: str) -> str:
    """Формула одной строкой обычного текста: индексы — символами, где они есть."""
    pieces: list[str] = []
    for script, text in _by_script(runs(latex)):
        pieces.append(_script_text(text, script) if script else text)
    return "".join(pieces).replace(NBSP, " ")


class _Parser:
    """LaTeX формулы — в дерево из кортежей. Узлы:

    ("atom", текст, вид) — вид: var, num, op, rel, open, close, punct, ord,
    text, fn, big, space; ("sup" | "sub", узлы); ("frac", числитель,
    знаменатель); ("sqrt", подкоренное, степень или None); ("style", узлы,
    bold | upright | italic); ("accent", узлы, знак); ("group", узлы).
    """

    def __init__(self, latex: str) -> None:
        self.tokens = [
            ("cmd", m.group(1)) if m.group(1) is not None
            else ("esc", m.group(2)) if m.group(2) is not None
            else ("ws", m.group(3)) if m.group(3) is not None
            else ("ch", m.group(4))
            for m in _TOKEN.finditer(latex)
        ]
        self.pos = 0

    def sequence(self, end: str | None = None) -> list:
        nodes: list = []
        while self.pos < len(self.tokens):
            kind, value = self.tokens[self.pos]
            self.pos += 1
            if kind == "ch" and value == end:
                break
            node = self.node(kind, value)
            if node is not None:
                nodes.append(node)
        return nodes

    def argument(self) -> list:
        self._skip_spaces()
        if self.pos >= len(self.tokens):
            return []
        kind, value = self.tokens[self.pos]
        self.pos += 1
        if (kind, value) == ("ch", "{"):
            return self.sequence("}")
        node = self.node(kind, value)
        return [] if node is None else [node]

    def optional(self) -> list | None:
        self._skip_spaces()
        if self.pos < len(self.tokens) and self.tokens[self.pos] == ("ch", "["):
            self.pos += 1
            return self.sequence("]")
        return None

    def raw_text(self) -> str:
        """Аргумент \\text{…} как есть: пробелы в нём значимы, в отличие от формулы."""
        self._skip_spaces()
        if self.pos >= len(self.tokens):
            return ""
        if self.tokens[self.pos] != ("ch", "{"):
            self.pos += 1
            return self._token_text(self.tokens[self.pos - 1])
        self.pos += 1
        depth, pieces = 1, []
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            self.pos += 1
            if token == ("ch", "{"):
                depth += 1
            elif token == ("ch", "}"):
                depth -= 1
                if not depth:
                    break
            else:
                pieces.append(self._token_text(token))
        return "".join(pieces)

    def node(self, kind: str, value: str):
        if kind == "ws":
            return None
        if kind == "esc":
            if value in _SPACES:
                return ("atom", NBSP, "space")
            if value == "\\":
                return ("atom", ";", "punct")
            if value in _ESCAPED:
                return ("atom", *_ESCAPED[value])
            return None
        if kind == "cmd":
            return self.command(value)
        return self.char(value)

    def char(self, c: str):
        if c == "{":
            return ("group", self.sequence("}"))
        if c == "^":
            return ("sup", self.argument())
        if c == "_":
            return ("sub", self.argument())
        if c in "}&":
            return None
        if c == "~":
            return ("atom", NBSP, "space")
        if "a" <= c.lower() <= "z":
            return ("atom", c, "var")
        if c.isdigit() or c == ".":
            return ("atom", c, "num")
        if c.isalpha():
            # Кириллица в формуле — подписи вроде x_{наблюд}: прямым, как текст.
            return ("atom", c, "text")
        simple = {
            "+": ("+", "op"), "-": ("−", "op"), "*": ("∗", "op"), "=": ("=", "rel"),
            "<": ("<", "rel"), ">": (">", "rel"), ":": (":", "rel"), ",": (",", "punct"),
            ";": (";", "punct"), "(": ("(", "open"), "[": ("[", "open"), ")": (")", "close"),
            "]": ("]", "close"), "'": ("′", "ord"),
        }
        return ("atom", *simple.get(c, (c, "ord")))

    def command(self, name: str):
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            return ("frac", self.argument(), self.argument())
        if name in ("binom", "dbinom", "tbinom"):
            # Как в русских учебниках: C с n внизу и k вверху.
            n, k = self.argument(), self.argument()
            return ("group", [("atom", "C", "var"), ("sub", n), ("sup", k)])
        if name == "sqrt":
            index = self.optional()
            return ("sqrt", self.argument(), index)
        if name in _TEXT:
            return ("atom", self.raw_text().replace(" ", NBSP), "text")
        if name in ("operatorname", "DeclareMathOperator"):
            return ("atom", self.raw_text(), "fn")
        if name == "textbf":
            return ("style", [("atom", self.raw_text().replace(" ", NBSP), "text")], "bold")
        if name == "mathbf":
            return ("style", self.argument(), "bold")
        if name in _BOLD_ITALIC:
            return ("style", self.argument(), "bold italic")
        if name in ("mathit", "textit", "emph"):
            return ("style", self.argument(), "italic")
        if name == "mathbb":
            return ("atom", "".join(_BLACKBOARD.get(c, c) for c in self.raw_text()), "ord")
        if name in ("mathcal", "mathscr"):
            return ("atom", "".join(_CALLIGRAPHIC.get(c, c) for c in self.raw_text()), "ord")
        if name in _UPRIGHT:
            return ("style", self.argument(), "upright")
        if name in _ACCENTS:
            return ("accent", self.argument(), _ACCENTS[name])
        if name in _SIZERS:
            # \left. — пустая скобка: её не рисуют.
            if self.pos < len(self.tokens) and self.tokens[self.pos] == ("ch", "."):
                self.pos += 1
            return None
        if name in ("begin", "end"):
            self.raw_text()
            return None
        if name in ("pmod",):
            return ("group", [("atom", NBSP + "(mod" + NBSP, "text"), *self.argument(), ("atom", ")", "close")])
        if name in _SPACES:
            return ("atom", NBSP, "space")
        if name in _IGNORED:
            return None
        if name in _GREEK:
            return ("atom", _GREEK[name], "ord")
        if name in _RELATIONS:
            return ("atom", _RELATIONS[name], "rel")
        if name in _OPERATORS:
            return ("atom", _OPERATORS[name], "op")
        if name in _ORDINARY:
            return ("atom", _ORDINARY[name], "ord")
        if name in _OPEN:
            return ("atom", _OPEN[name], "open")
        if name in _CLOSE:
            return ("atom", _CLOSE[name], "close")
        if name in _BIG:
            return ("atom", _BIG[name], "big")
        # Незнакомая команда — её имя прямым шрифтом: \softmax читается и так.
        return ("atom", name, "fn")

    def _skip_spaces(self) -> None:
        while self.pos < len(self.tokens) and self.tokens[self.pos][0] == "ws":
            self.pos += 1

    @staticmethod
    def _token_text(token: tuple[str, str]) -> str:
        kind, value = token
        if kind == "ws":
            return " "
        if kind == "cmd":
            for table in (_GREEK, _RELATIONS, _OPERATORS, _ORDINARY, _OPEN, _CLOSE, _BIG):
                if value in table:
                    return table[value]
            return value
        if kind == "esc":
            return _ESCAPED.get(value, ("", ""))[0] or (" " if value in _SPACES else "")
        return value


class _Out:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    def add(self, text: str, italic: bool, bold: bool, script: int) -> None:
        if not text:
            return
        last = self.runs[-1] if self.runs else None
        if last is not None and (last.italic, last.bold, last.script) == (italic, bold, script):
            last.text += text
        else:
            self.runs.append(Run(text, italic, bold, script))


def _render(nodes: list, out: _Out, script: int, italic: bool, bold: bool) -> None:
    """Дерево — в куски текста. Пробелы вокруг знаков — только на основной
    строке: в индексах их не ставит и TeX."""
    previous = None
    gap_next = False
    for node in nodes:
        tag = node[0]
        if tag in ("sup", "sub"):
            level = 1 if tag == "sup" else -1
            if script and level != script:
                # Индекс внутри индекса Qt не поднимет ещё раз: e^{x_i}
                # иначе читалось бы как e в степени «xi».
                out.add("_" if level < 0 else "^", False, bold, script)
            _render(node[1], out, script or level, italic, bold)
            continue
        kind = node[2] if tag == "atom" else "group"
        # \ln\frac{p}{1-p}: без скобок «ln p/(1 − p)» читается как (ln p)/(1 − p).
        argument = tag == "frac" and previous == "fn"
        if gap_next and not script and not argument and kind not in ("open", "punct", "rel", "op", "close"):
            out.add(NBSP, False, bold, script)
        elif kind in ("fn", "big") and previous in _OPERAND and not script:
            # «y log ŷ», а не «ylog ŷ»: перед функцией TeX ставит отбивку.
            out.add(NBSP, False, bold, script)
        gap_next = False
        if tag == "atom":
            text = node[1]
            spaced = not script
            if kind == "op":
                unary = previous not in _OPERAND
                if spaced and not unary:
                    text = f"{NBSP}{text}{NBSP}"
            elif kind == "rel":
                if spaced:
                    text = f"{NBSP}{text}{NBSP}" if previous is not None else f"{text}{NBSP}"
            elif kind == "punct" and spaced:
                text = f"{text}{NBSP}"
            out.add(text, italic and kind == "var", bold, script)
            gap_next = kind in ("fn", "big")
            previous = kind
        elif tag == "frac":
            if argument:
                out.add("(", False, bold, script)
            _render(_wrapped(node[1], strict=False), out, script, italic, bold)
            out.add("/", False, bold, script)
            _render(_wrapped(node[2], strict=True), out, script, italic, bold)
            if argument:
                out.add(")", False, bold, script)
            previous = "group"
        elif tag == "sqrt":
            if node[2]:
                _render(node[2], out, 1, italic, bold)
            out.add("√", False, bold, script)
            _render(_wrapped(node[1], strict=True), out, script, italic, bold)
            previous = "group"
        elif tag == "style":
            style = node[2]
            _render(node[1], out, script, italic="italic" in style, bold=bold or "bold" in style)
            previous = "group"
        elif tag == "accent":
            inner = _Out()
            _render(node[1], inner, script, italic, bold)
            if inner.runs:
                first = inner.runs[0]
                first.text = first.text[:1] + node[2] + first.text[1:]
            for run in inner.runs:
                out.add(run.text, run.italic, run.bold, run.script)
            previous = "group"
        elif tag == "group":
            _render(node[1], out, script, italic, bold)
            previous = "group"


def _wrapped(nodes: list, strict: bool) -> list:
    """Часть дроби или корня — в скобки, если без них она читается иначе.

    strict — для знаменателя и корня: там скобки нужны и произведению,
    «1/2n» читают по-разному, а «2x/3» — одинаково.
    """
    flat = _flatten(nodes)
    depth, operands, compound = 0, 0, False
    for index, node in enumerate(flat):
        if node[0] == "frac":
            compound = compound or depth == 0
            operands += 1
            continue
        if node[0] != "atom":
            if node[0] not in ("sup", "sub") and depth == 0:
                operands += 1
            continue
        kind = node[2]
        if kind == "open":
            if depth == 0:
                operands += 1
            depth += 1
        elif kind == "close":
            depth -= 1
        elif depth == 0:
            if kind in ("rel", "punct", "space", "big") or (kind == "op" and index > 0) or node[1] == "/":
                compound = True
            elif kind in ("var", "num", "ord", "text", "fn") and not (kind == "num" and _after_num(flat, index)):
                operands += 1
    if compound or (strict and operands > 1):
        return [("atom", "(", "open"), *nodes, ("atom", ")", "close")]
    return nodes


def _after_num(flat: list, index: int) -> bool:
    """Цифра после цифры — то же число, а не второй множитель."""
    return index > 0 and flat[index - 1][0] == "atom" and flat[index - 1][2] == "num"


def _flatten(nodes: list) -> list:
    flat: list = []
    for node in nodes:
        if node[0] in ("group", "style"):
            flat.extend(_flatten(node[1]))
        else:
            flat.append(node)
    return flat


def _by_script(pieces: list[Run]) -> list[tuple[int, str]]:
    grouped: list[tuple[int, str]] = []
    for run in pieces:
        if grouped and grouped[-1][0] == run.script:
            grouped[-1] = (run.script, grouped[-1][1] + run.text)
        else:
            grouped.append((run.script, run.text))
    return grouped


def _script_text(text: str, script: int) -> str:
    table = _SUP if script > 0 else _SUB
    letters = text.replace(NBSP, "")
    if all(c in table or unicodedata.combining(c) for c in letters):
        return "".join(table.get(c, c) for c in letters)
    sign = "^" if script > 0 else "_"
    return sign + (letters if len(letters) == 1 else f"({letters})")
