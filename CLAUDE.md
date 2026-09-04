# VoiceTyper — контекст для Claude Code

Голосовой ввод: зажал клавишу, продиктовал, отпустил — текст вставился в
активное окно. Windows и macOS, Python 3.12, PySide6. Подробности в README.md,
история версий в CHANGELOG.md, версия в `src/config.py` (`APP_VERSION`).

## Как работаем

- Код, комментарии, коммиты и ответы — по-русски. Комментарии объясняют,
  почему сделано так, а не что делает строка.
- Коммит-сообщения: первая строка — суть, дальше короткий список пунктов.
  Каждая законченная задача — отдельный коммит; пушить только по просьбе.
- Интерфейс смотрим живьём (`python src/demo.py` гоняет плашку по состояниям),
  а не по рендерам. В анимации минимализм: одно движение в кадре.
- Отчёты и эксперименты не коммитим, только код и документы.

## Запуск из исходников

```
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt     # или requirements-lite.txt: без локальных моделей
python src/main.py
```

Лог: `voicetyper.log` в каталоге данных — `%APPDATA%\VoiceTyper` на Windows,
`~/Library/Application Support/VoiceTyper` на macOS. Там же `config.json`,
`dictations.jsonl` (журнал диктовок) и `crash.log`.

Сборка: `python build.py --yes` (полная), `--lite` (только облако).
Релиз: тег `vX.Y.Z` на коммите с той же версией запускает GitHub Actions.

## Состояние macOS-порта (сентябрь 2026)

Портировано вслепую с Windows и на живом Mac ещё не запускалось. CI на
macOS-раннере проверяет только импорт модулей. Что именно платформенное:

- `core/hotkeys.py` — бэкенд pynput (на Windows — keyboard).
- `core/paster.py` — pbcopy/pbpaste и Cmd+V через pynput.
- `core/sounds.py` — afplay; `core/autostart.py` — LaunchAgent;
  `main.py` — файл-замок вместо мьютекса; `config.app_data_dir()`.
- `ui/live.py` живое стекло — только Windows; на Mac работает статичный
  снимок из `ui/glass.py`, ему нужно разрешение «Запись экрана».

Порядок отладки на Mac: запуск из исходников → разрешения (микрофон,
Универсальный доступ, Запись экрана; выдаются приложению-родителю: Терминалу
или VS Code) → горячая клавиша (F8 на Mac занята плеером, возможно, нужен
другой дефолт) → вставка в TextEdit и VS Code → `.app` из релиза (не подписан,
снимать карантин: `xattr -dr com.apple.quarantine VoiceTyper.app`) →
автозапуск и звуки. Всё, что заработает или сломается, записывать в README
(раздел «Установка») и CHANGELOG.

## Облако

`cloud.api_key` в config.json — ключ Groq пользователя, в код и в вывод не
попадает. Лимиты бесплатного тарифа: 8k токенов в минуту, 1000 правок в сутки.
