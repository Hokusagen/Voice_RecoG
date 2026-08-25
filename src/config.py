"""Настройки приложения.

Значения по умолчанию живут здесь, пользовательские переопределения — в
%APPDATA%/VoiceTyper/config.json. Файл читается при старте и дописывается
при изменении настроек из трея; незнакомые ключи игнорируются, отсутствующие
берутся из дефолтов, так что конфиг от старой версии не ломает запуск.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

APP_NAME = "VoiceTyper"
APP_VERSION = "0.2.0"
"""Единственное место, где живёт номер версии.

Попадает в подсказку трея и в каждую запись журнала: по записи всегда
видно, какая сборка её сделала. Меняется вместе с записью в CHANGELOG.md.
"""

DEFAULT_SYSTEM_PROMPT = """Ты — строгий автоматический редактор транскрипций. Ты НЕ переписываешь текст, ты вычищаешь из него мусор.

ЖЕСТКИЕ ПРАВИЛА:
1. УДАЛЯЙ слова-паразиты: "короче", "ну", "блин", "так", "типа", "вот", "эээ", "ау", "как бы", "это самое", "значит".
2. ИСПРАВЛЯЙ самоисправления оратора: из "по ГОСТу... ау нет, по ЕСКД" оставляй только "по ЕСКД".
3. РАССТАВЛЯЙ знаки препинания и заглавные буквы.
4. УГАДЫВАЙ технические термины из контекста: ЕСКД, ГОСТ, СПДС, Компас-3D, названия брендов, обозначения крепежа вида М8х40.
5. НИКОГДА НЕ ПЕРЕФРАЗИРУЙ. Не заменяй слова синонимами, не сокращай, не переставляй слова. Каждое осмысленное слово оратора обязано остаться на месте.
6. ЧИСЛА И КОЛИЧЕСТВА НЕ ТРОГАЙ: "двадцать восемь болтов" остаётся "двадцать восемь болтов".
7. НИКОГДА НЕ ПЕРЕВОДИ. Сохраняй исходный язык. Смесь русского и английского оставляй смесью.
8. НИКОГДА НЕ ОТВЕЧАЙ на текст: вопрос остаётся вопросом, просьба — просьбой.
9. ВЫВОДИ ТОЛЬКО ИСПРАВЛЕННЫЙ ТЕКСТ. Никаких "Вот результат", никаких комментариев.

ПРИМЕРЫ РАБОТЫ:
Вход: "ну блин вчера я короче испачкал свои замшевые нью-бэлансы в смазке от цепи как-то нагревали катал"
Выход: "Вчера я испачкал свои замшевые нью-балансы в смазке от цепи, когда на грэвеле катал."

Вход: "Слушай там в компасе 3d ну короче надо переделать спецификацию по густу... ау и нет не по густу а по ескд"
Выход: "Слушай, там в Компас-3D надо переделать спецификацию по ЕСКД."

Вход: "давайте мы с вами значит попробуем сделать так чтобы вот эта штука работала ну побыстрее потому что эээ долго ждать приходится"
Выход: "Давайте мы с вами попробуем сделать так, чтобы эта штука работала побыстрее, потому что долго ждать приходится."

Вход: "Okay let's try this штука ну не будет переводить мой русский текст в английский а просто we'll clean it up"
Выход: "Okay, let's try this. Эта штука не будет переводить мой русский текст в английский, а просто we'll clean it up."
"""

# Подсказка самому Whisper: термины из этого списка он распознаёт заметно
# точнее, чем если чинить их потом языковой моделью.
DEFAULT_INITIAL_PROMPT = (
    "ЕСКД, ГОСТ, СПДС, Компас-3D, SolidWorks, AutoCAD, чертёж, спецификация, "
    "допуск, посадка, шероховатость, сборочная единица, деталировка."
)


def app_data_dir() -> Path:
    """Каталог для конфига, истории и логов. Работает и из .exe, и из исходников."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_PATH = app_data_dir() / "config.json"


@dataclass
class HotkeysConfig:
    record: str = "f8"
    """Основная клавиша диктовки: распознать и причесать языковой моделью."""

    record_raw: str = "ctrl+f8"
    """Быстрый режим: вставить сырой текст Whisper, не дожидаясь LLM."""

    cancel: str = "esc"
    """Отмена активной записи без вставки."""

    mode: str = "hold"
    """hold — говорить, пока клавиша зажата; toggle — тап включил, тап выключил."""

    suppress: bool = False
    """Прятать нажатие горячей клавиши от активного окна."""


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    block_ms: int = 30
    preroll_ms: int = 500
    """Сколько звука «до нажатия» подмешивать, чтобы не срезалось начало фразы."""

    min_duration_ms: int = 350
    """Более короткие нажатия считаем случайными и игнорируем."""

    max_duration_s: int = 180
    """Страховка от забытой залипшей клавиши."""

    idle_close_s: int = 180
    """Через сколько секунд простоя закрывать микрофон (0 — держать всегда)."""

    device: int | None = None
    """Индекс устройства ввода; None — системное по умолчанию."""

    silence_rms: float = 0.0025
    """Ниже этого пика считаем, что человек молчит.

    Замеренный шумовой пол тихой комнаты — около 0.0012, речь обычно 0.02..0.15.
    Порог держим ближе к полу: пропустить тишину в Whisper дешевле, чем
    проглотить настоящую фразу.
    """


@dataclass
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "auto"
    """auto | cuda | cpu — auto пробует CUDA и молча откатывается на CPU."""

    compute_type: str = "auto"
    """auto -> int8_float16 на CUDA, int8 на CPU."""

    language: str = "ru"
    beam_size: int = 1
    vad: bool = True
    """Отсекает тишину: без него Whisper дорисовывает «Продолжение следует...»."""

    vad_min_silence_ms: int = 300
    initial_prompt: str = DEFAULT_INITIAL_PROMPT


@dataclass
class LLMConfig:
    enabled: bool = True
    url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b"
    keep_alive: str = "30m"
    """Не даём Ollama выгружать модель между диктовками."""

    timeout_s: float = 20.0
    warmup: bool = True
    """Прогреть модель на старте, чтобы первая диктовка не ждала загрузку."""

    min_words: int = 4
    """Короткие фразы вставляем как есть — экономит пару секунд на «ок, понял»."""

    temperature: float = 0.0
    num_ctx: int = 2048
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    journal: bool = True
    """Писать журнал диктовок в dictations.jsonl рядом с конфигом.

    Хранит сырой текст Whisper, правку модели и тайминги — то, чего нет ни в
    истории трея, ни в логе. Всё лежит открытым текстом на этой машине и никуда
    не отправляется; выключается здесь.
    """

    journal_max_mb: float = 32.0
    """При переполнении журнал уступает место новому, старое поколение одно."""


@dataclass
class PasteConfig:
    restore_clipboard: bool = True
    """Вернуть в буфер обмена то, что там лежало до вставки."""

    trailing_space: bool = True
    paste_delay_ms: int = 40
    restore_delay_ms: int = 300


@dataclass
class UIConfig:
    hud_enabled: bool = True
    hud_position: str = "bottom"
    """bottom | top | bottom-right | bottom-left | top-right | top-left."""

    hud_margin: int = 96
    hud_scale: float = 1.0
    hud_follow_cursor: bool = True
    """Показывать HUD на том мониторе, где сейчас курсор."""

    liquid_live: bool = True
    """Живое стекло: пересобирать размытие из свежего снимка экрана каждый кадр.

    Ради этого плашка исключается из захвата экрана, поэтому в OBS, Zoom и
    записях экрана её не будет видно. False — прежний режим: один снимок в
    момент появления, стекло не реагирует на прокрутку под ним.
    """

    font: str = "auto"
    """Семейство шрифта: auto, Inter, Onest, Golos Text, Manrope, Segoe UI…

    Первые четыре лежат в assets/fonts и не требуют установки в систему.
    """

    success_hold_ms: int = 2400
    """Базовое время показа результата, миллисекунды.

    К нему добавляется время на чтение самого текста, см. success_hold_max_ms.
    """

    success_hold_max_ms: int = 7000
    """Потолок: даже абзац не должен висеть на экране бесконечно."""
    sounds: bool = True
    volume: float = 0.35
    history_size: int = 10
    autostart: bool = False


@dataclass
class Config:
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    paste: PasteConfig = field(default_factory=PasteConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # ---------- сохранение / загрузка ----------

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Читает конфиг, если он есть.

        Файл намеренно не создаётся сам: записанные при первом запуске значения
        по умолчанию потом перекрывали бы новые. Пока пользователь ничего не
        менял, приложение работает на живых умолчаниях, а файл появляется по
        команде «Открыть настройки» или при первом изменении из трея.
        """
        path = path or CONFIG_PATH
        cfg = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cfg
        except (OSError, ValueError) as exc:
            print(f"[config] не удалось прочитать {path}: {exc}; беру значения по умолчанию")
            return cfg
        _merge_into(cfg, raw)
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
            path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"[config] не удалось сохранить {path}: {exc}")


def _merge_into(target: Any, raw: dict) -> None:
    """Накатывает словарь из JSON на dataclass, пропуская чужие и битые ключи."""
    known = {f.name: f for f in fields(target)}
    for key, value in raw.items():
        spec = known.get(key)
        if spec is None:
            continue
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge_into(current, value)
        elif value is None or isinstance(value, (str, int, float, bool, list)):
            setattr(target, key, value)
