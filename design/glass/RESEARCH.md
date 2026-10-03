# Выжимка исследования (сентябрь 2026)

Сжатый итог исследования перед первым кругом: пять тем (Apple, веб-реконструкции, морф,
голосовые интерфейсы, Windows) и пять уточнений. Сырой отчёт — `research.json` рядом, только на
этой машине.

## Оптика Apple Liquid Glass — замер нативного iOS 26

Снимок GlassExplorer (квадрат 200 pt) сверен с исходной картинкой попиксельно, плюс дамп фильтра
macOS 26 (ShatteredGlass).

- **Выборка у кромки идёт внутрь** по нормали: `src = p − n·d`, `d = A·(1 − √(1 − t²))`,
  `t = clamp(1 − dist/h, 0, 1)`; профиль circle-map (RMS 2.4 px к замеру).
- **Числа.** Квадрат 200 pt: h ≈ 19 pt, A ≈ 67 pt. Круг 50 pt (дамп macOS): h 12.5, A 40. Рост
  примерно как размер^0.3. Для капсулы 56 px: h ≈ 13, A ≈ 41 (при 100% DPI; умножать на масштаб).
- **A больше h и радиуса торца**, поэтому кромка «зеркальная»: верх показывает перевёрнутый и
  сжатый низ, как стеклянный стержень. Рыбьего глаза и выталкивания наружу нет.
- **Центр 1:1** (подгонка m = 1.00, при 1.05 ошибка втрое больше) — лупы нет.
- **Интерьер:** размытие σ ≈ 1.8 pt в iOS 26 beta 1 (позже матовее), тон `out = in·1.015 + 0.086`,
  насыщенность не трогается. Размытие в бортике то же, что в центре.
- **Блик** — жёсткая полоса 1 pt цвета самого контента через vibrant-матрицу
  `1.45·(lum + 2.07·(c − lum)) + 0.05`, два источника под +45° и −135°. Широкий белый блик
  выглядит пластиком.
- **Тени почти нет:** iOS 26 — до −4.5% на 30–40 pt. iOS 27 — тёмная кромка вместо тени: ~1 pt
  ×0.83 на торцах, ~0.5 pt ×0.92 на прямых.
- **Появление — материализация:** растёт искривление света, а не прозрачность (WWDC25/219).
- **Большое стекло «толще»:** сильнее линза и тень.
- **Читаемость:** regular адаптирует тон и переключается светлое↔тёмное (маленькие элементы —
  да, большие — нет); clear над ярким требует затемняющего слоя 35% (HIG Materials). Тинт — только
  для смысла, не для красоты.

## Слияние капель — нормированный smin

- **Ядро:** квартичное (Килес), k = наибольшее вздутие формы в px. Мостик живёт при зазоре ≤ 2k,
  влияние начинается с 5.33k.
- **Калибровка по снимку Apple** (кнопки 80 pt, spacing 40): k = 3S/16 ≈ 0.19·S. Spacing у Apple —
  это начало влияния, а не зазор появления мостика.
- **Для капсулы 56 px:** k в покое 5.25, в движении 7–8 (по видео Apple в движении k больше в
  1.3–1.5 раза), потолок 10 — выше форма «ватная».
- **Неактивную каплю** убирать из smin множителем presence, иначе она раздувает капсулу изнутри.
- **Кромку и блик** строить по `f/|∇f|`: в шейках |∇f| ≈ 0.54–0.74, и полосы по сырому f
  расползаются.

## Движение

- **Пружины Apple:** длительность + отскок, ζ = 1 − bounce. smooth — 0.5 с / 0; snappy — 0.5 /
  0.15; bouncy — 0.5 / 0.3; отскок больше 0.4 — перебор. Перелёт только там, где есть импульс
  (WWDC18/803). При смене цели на лету пружина сохраняет скорость.
- **Material 3 Expressive:** spatial fast 0.6/800 (перелёт 9.5%), default 0.8/380. LoadingIndicator —
  7 форм (SoftBurst, Cookie9Sided, Pentagon, Pill, Sunny, Cookie4Sided, Oval), слот 650 мс,
  пружина 0.6/200. Морф — жанр для ожидания от 200 мс до 5 с, ровно наш случай.
- **Жидкость = поверхностное натяжение:** низкие моды Рэлея доминируют, мелкая рябь гаснет быстро.
  Равномерный шум на всех частотах — «дешёвый блоб».
- **Деформация только по причине:** голос, импульс смены состояния, слияние. В покое не больше 1 px.
- **Амплитуды для 56 px:** дыхание ≤ 3–4 px, рябь ≤ 2.5–3 px, толчок при смене состояния 1–2 px.
- **Радиус капсулы** следует за h/2 в каждом кадре, иначе посреди морфа появляются «плечи».

## Голос

- **Громкость:** в окне дБ (например −68…−30 или −60…0) с гаммой 0.7, не линейный RMS.
- **Сглаживание:** быстрая атака, спад 250–400 мс. Слог длится ~200 мс; при спаде короче 150 мс
  форма дёргается на каждом слоге.
- **Голос модулирует живую систему, а не рисует геометрию** (ElevenLabs Orb, LiveKit Aura, Apple
  Aurora): базовое движение идёт всегда, голос сдвигает его параметры.
- **Состояние — темпом и фактурой**, а не новым цветом.
- **Никакой бегущей по периметру кометы:** глаз читает её как спиннер или RGB-подсветку.
- **Тренд — голосовой UI сжимается:** в iOS 27 вместо свечения по рамке тёмная капля из Dynamic
  Island; Microsoft убрала полноэкранный оверлей голосового ввода.
- **Движение честное:** его вызывает реальный сигнал (Wispr Flow, Superwhisper: живая волна —
  знак рабочего микрофона).

## Текст в «Готово»

- **Глифы не преломляются и не двигаются:** меняются только прозрачность и короткое размытие на
  появлении (до 300 мс).
- **Контраст 4.5:1** — по худшему пикселю под буквами (95-й и 5-й перцентили), а не по среднему.
- **Segoe UI Semibold 14 px** (Segoe UI Variable в Windows 10 нет); сглаживание всегда серое —
  иначе в анимации скачет толщина.
- **Не больше двух строк,** радиус 28 фиксирован.
- **Время показа:** около 68 мс на знак вслух, молча в 1.3 раза быстрее, умноженное на системную
  настройку длительности уведомлений.

## Windows

- **Композитор без задержки** (Windows.UI.Composition в Win32-окне через pywinrt):
  BackdropBrush + GaussianBlur — проверено, работает и при выключенных «Эффектах прозрачности».
  Кроме того, без задержки: цветокоррекция, маски, пружины, «жидкий клей» через VisualSurface +
  размытие + порог альфы (`windows/goo_probe.py`: перемычка есть при зазоре 6 px, рвётся при 70).
- **Композитор не умеет:** DisplacementMap (E_INVALIDARG; в Win2D прямо: «not supported by
  Windows.UI.Composition») и свой HLSL. Значит, настоящей линзы в композиторе нет.
- **HostBackdropBrush и системный акрил** рисуют чёрное, пока «Эффекты прозрачности» выключены,
  а у пользователя они выключены.
- **Анимация пути** (PathKeyFrameAnimation) до 20H2 — с известной ошибкой.
- **Исключение из захвата** (WDA_EXCLUDEFROMCAPTURE) принимают окна без поверхности
  перенаправления (DComp, композиция); отказ только у UpdateLayeredWindow с попиксельной альфой
  (`windows/wda_matrix.py`).
- **Свой шейдер:** GDI-захват полосы 760×170 — 13.3 мс (ровно период 75 Гц); кадр на GPU 0.6 мс
  против 14–26 мс на numpy. Свопчейн на NVIDIA в этом гибриде даёт 60 Гц на мониторе 75 Гц.
- **Линза без задержки — только внутри DWM.** Образцы: dwm_lut (свой шейдер на весь кадр,
  Win10 20H2+) и DWMBlurGlass (своё размытие за окнами, Win10 2004+). Цена: права
  администратора, недокументированные хуки, ломается обновлениями Windows.
- **Гибрид (октябрь 2026, `windows/hybrid_probe.py`) — рабочий путь.** Середину рисует композитор:
  BackdropBrush → размытие → ColorMatrix тона Apple. Кромку Линзы рисует свой шейдер D3D11 по
  GDI-захвату, свопчейн встроен в ту же композицию через ICompositorInterop. Замер полосами
  480 px/с под стеклом: середина отстаёт на 0 px. Кромка из захвата на кадр-два позже, но это
  заметно только на рывках колеса мыши; при плавной прокрутке не видно. Окно без
  перенаправления, поэтому кольца вокруг плашки нет. Шейдер выдаёт 60 к/с.
- **«frost 2.4» лаборатории — радиус, а не σ.** sceneBlur — диск из 12 выборок с весами
  1…0.54: дисперсия 0.223·r² на ось, σ ≈ 0.47·r ≈ 1.13 px. Композитору нужна настоящая σ
  (иначе середина вдвое мутнее кромки) и оптимизация QUALITY: BALANCED уменьшает картинку.
- **Сдвинуть живой фон композитор не может.** BackdropBrush прямо в Transform2D —
  E_INVALIDARG на SetSourceParameter. Через размытие фабрика собирается (LoadStatus 0), но ни
  переворот, ни масштаб 0.5 картинку не меняют: фон берётся по месту на экране. Поэтому
  линзу из вложенных колец с Transform2D собрать нельзя.

## Источники (проверены)

- Apple: [Meet Liquid Glass — WWDC25/219](https://developer.apple.com/videos/play/wwdc2025/219/) ·
  [Get to know the new design system — WWDC25/356](https://developer.apple.com/videos/play/wwdc2025/356/) ·
  [HIG Materials](https://developer.apple.com/design/human-interface-guidelines/materials) ·
  [GlassEffectContainer](https://developer.apple.com/documentation/swiftui/glasseffectcontainer) ·
  [Animate with springs — WWDC23](https://developer.apple.com/videos/play/wwdc2023/10158/) ·
  [Designing Fluid Interfaces — WWDC18](https://developer.apple.com/videos/play/wwdc2018/803/)
- Реконструкции: [kube.io — Liquid Glass in the Browser](https://kube.io/blog/liquid-glass-css-svg/) ·
  [Kyant0/AndroidLiquidGlass](https://github.com/Kyant0/AndroidLiquidGlass) ·
  [AlexStrNik/ShatteredGlass](https://github.com/AlexStrNik/ShatteredGlass) ·
  [iyinchao/liquid-glass-studio](https://github.com/iyinchao/liquid-glass-studio)
- Морф: [Inigo Quilez — smooth minimum](https://iquilezles.org/articles/smin/) ·
  [Inigo Quilez — distance estimation](https://iquilezles.org/articles/distance/) ·
  [androidx graphics-shapes Morph.kt](https://raw.githubusercontent.com/androidx/androidx/androidx-main/graphics/graphics-shapes/src/commonMain/kotlin/androidx/graphics/shapes/Morph.kt)
- Голос: [tornikegomareli/Aurora](https://github.com/tornikegomareli/Aurora) ·
  [ElevenLabs Orb](https://github.com/elevenlabs/ui/blob/main/apps/www/registry/elevenlabs-ui/ui/orb.tsx) ·
  [MacStories — iOS 27 Review: Siri](https://www.macstories.net/stories/ios-and-ipados-27-review/5/)
- Критика: [NN/g — Liquid Glass Is Cracked](https://www.nngroup.com/articles/liquid-glass/)
- Windows: [Using the Visual Layer with Win32](https://learn.microsoft.com/en-us/windows/uwp/composition/using-the-visual-layer-with-win32) ·
  [Win2D DisplacementMapEffect](https://microsoft.github.io/Win2D/WinUI2/html/T_Microsoft_Graphics_Canvas_Effects_DisplacementMapEffect.htm) ·
  [ledoge/dwm_lut](https://github.com/ledoge/dwm_lut) ·
  [Maplespe/DWMBlurGlass](https://github.com/Maplespe/DWMBlurGlass)
