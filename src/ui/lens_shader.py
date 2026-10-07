"""Шейдер стекла плашки (HLSL 5.0).

Перенос лаборатории design/glass без изменения чисел: материал Линзы
(harness.js → liquidGlass), обход света по событию (lens.js), цвет итогов
(kit.js → statusRim, из «Сияния»), лепестки думающего диска (island.js),
голос «Шёлк» в «Слушаю» (voice/sketches.js).
Расстояния в лаборатории — в CSS px капсулы 56; здесь всё умножается на
uView.w — физических пикселей на пиксель макета.

Шейдер рисует слой поверх живой середины, которую собирает композитор. Где
стекло можно отдать композитору (покой, середина), слой прозрачен; кромку,
тень, значок и подпись он рисует всегда. Подробнее — ui.lens_hud.
"""

HLSL = r"""
Texture2D uScene : register(t0);
Texture2D uText : register(t1);
SamplerState uSamp : register(s0);

cbuffer Params : register(b0) {
    float4 uView;      // xy — размер окна, z — время, w — пикселей на пиксель макета
    float4 uPill;      // xy — центр, zw — размер
    float4 uGlass;     // x — материализация, y — A, z — h, w — доля живой середины
    float4 uLight;     // xy — направление света, z — сила лепестка, w — проход
    float4 uStatus;    // x — вспышка, y — зелёный, z — красный, w — ширина полосы
    float4 uTone;      // x — красный налёт, y — тон фона (1 — светлый), z — радиус размытия, w — тень
    float4 uLabel;     // xy — левый верхний угол подписи, zw — размер
    float4 uLabelFx;   // x — прозрачность, y — размытие, z — ореол
    float4 uIcon;      // xy — центр, z — размер, w — вид
    float4 uIconFx;    // x — прорисовка, y — прозрачность, z — дыхание
    float4 uIconDark;  // цвет значка над тёмным
    float4 uIconLight; // цвет значка над светлым
    float4 uTitleDark; float4 uTitleLight;
    float4 uDetailDark; float4 uDetailLight;
    float4 uMorph;     // x — сила лепестков, y — глубина A, z — глубина B, w — прогресс A→B
    float4 uMorphN;    // x — лепестков A, y — лепестков B, z — поворот
    float4 uVoice;     // x — видимость, y — фраза 0…1, z — слог, w — фаза течения дыма
};

float4 vs_main(uint id : SV_VertexID) : SV_Position {
    float2 uv = float2((id << 1) & 2, id & 2);
    return float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}

float3 sceneAt(float2 p) { return uScene.SampleLevel(uSamp, p / uView.xy, 0.0).rgb; }
// Размытие лаборатории: 12 выборок по золотой спирали в диске радиуса r.
float3 sceneBlur(float2 p, float r) {
    if (r < 0.6) return sceneAt(p);
    float3 acc = 0.0; float w = 0.0;
    [unroll] for (int i = 0; i < 12; i++) {
        float fi = (float)i;
        float a = fi * 2.39996323;
        float rr = r * sqrt((fi + 0.5) / 12.0);
        float k = 1.0 - 0.5 * fi / 12.0;
        acc += sceneAt(p + float2(cos(a), sin(a)) * rr) * k;
        w += k;
    }
    return acc / w;
}
float luma(float3 c) { return dot(c, float3(0.2126, 0.7152, 0.0722)); }
float sdRoundBox(float2 p, float2 b, float r) {
    float2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
float sdSegment(float2 p, float2 a, float2 b) {
    float2 pa = p - a, ba = b - a;
    float h = saturate(dot(pa, ba) / max(dot(ba, ba), 1e-6));
    return length(pa - ba * h);
}
float hash21(float2 p) { p = frac(p * float2(123.34, 456.21)); p += dot(p, p + 45.32); return frac(p.x * p.y); }
float vnoise(float2 p) {
    float2 i = floor(p), f = frac(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    return lerp(lerp(hash21(i), hash21(i + float2(1, 0)), u.x), lerp(hash21(i + float2(0, 1)), hash21(i + float2(1, 1)), u.x), u.y);
}
float fbm(float2 p) {
    float s = 0.0, a = 0.5;
    [unroll] for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + 17.1; a *= 0.5; }
    return s;
}

// Линза считается от гладкой капсулы, силуэт — с лепестками: на морфе свет
// ломается как у круга, а лепестки видны кромкой и бликом (LG_LENS_SHAPE).
float lensShape(float2 p) {
    float2 hs = uPill.zw * 0.5;
    return sdRoundBox(p - uPill.xy, hs, min(hs.x, hs.y));
}
float shape(float2 p) {
    float2 q = p - uPill.xy;
    float2 hs = max(uPill.zw * 0.5, 0.01);
    float r = min(hs.x, hs.y);
    float d = sdRoundBox(q, hs, r);
    if (uMorph.x > 0.001) {
        // Многолистник r(θ)=R·(1+a·cos(nθ)); две формы смешиваются по прогрессу.
        float th = atan2(q.y, q.x) - uMorphN.z;
        float off = r * lerp(uMorph.y * cos(uMorphN.x * th), uMorph.z * cos(uMorphN.y * th), uMorph.w);
        // Гасим лепестки к центру как (ρ/R)², иначе от центра расходятся «спицы».
        float rho = min(length(q) / r, 1.0);
        d -= off * uMorph.x * rho * rho;
    }
    return d;
}
float shapeDist(float2 p, out float2 n) {
    const float e = 0.5;
    float f = shape(p);
    float2 gr = float2(shape(p + float2(e, 0.0)) - shape(p - float2(e, 0.0)),
                       shape(p + float2(0.0, e)) - shape(p - float2(0.0, e))) / (2.0 * e);
    float gl = length(gr);
    n = gl > 1e-5 ? gr / gl : float2(0.0, -1.0);
    return f / max(gl, 0.25);
}
float lensDist(float2 p, out float2 n) {
    const float e = 0.5;
    float f = lensShape(p);
    float2 gr = float2(lensShape(p + float2(e, 0.0)) - lensShape(p - float2(e, 0.0)),
                       lensShape(p + float2(0.0, e)) - lensShape(p - float2(0.0, e))) / (2.0 * e);
    float gl = length(gr);
    n = gl > 1e-5 ? gr / gl : float2(0.0, -1.0);
    return f / max(gl, 0.25);
}
float2 shapeNormal(float2 p) { float2 n; shapeDist(p, n); return n; }

// Слой с предумноженной альфой поверх слоя ниже.
float4 over(float4 top, float4 below) { return top + below * (1.0 - top.a); }

// Цвет итога из «Сияния»: полоса внутри кромки вспыхивает светом стекла и
// пятнами по шуму стягивается в зелёный #4FDCA6 или красный #FF6B74.
float3 statusRim(float3 col, float2 p, float inside, float S) {
    if (uStatus.x < 0.003 || inside > (uStatus.w * 1.7 + 6.0) * S) return col;
    float2 np = p / (30.0 * S);
    float t = uView.z;
    float n1 = fbm(np / 1.6 + float2(t * 0.07, -t * 0.05));
    float n2 = fbm(np * 1.8 + float2(-t * 0.14, t * 0.11) + 7.3);
    float width = uStatus.w * S * (0.8 + 0.4 * n1);
    float prof = pow(1.0 - smoothstep(0.0, width, inside), 1.7);
    float line_ = 1.0 - smoothstep(0.0, 2.0 * S, inside);
    float I = 0.74 * prof + 0.26 * line_;
    float bright = uStatus.x * (0.68 + 0.64 * n2);
    float3 lc = 1.0;
    lc = lerp(lc, float3(0.310, 0.863, 0.651), smoothstep(0.0, 1.0, saturate(uStatus.y * 1.5 - 0.5 * n2)));
    lc = lerp(lc, float3(1.000, 0.420, 0.455), smoothstep(0.0, 1.0, saturate(uStatus.z * 1.5 - 0.5 * n2)));
    float lum = luma(col);
    float dark = 1.0 - smoothstep(0.35, 0.9, lum);
    float light = smoothstep(0.6, 0.8, lum);
    float a = min(0.9, 0.9 * (1.0 - exp(-1.5 * I * bright)) * (1.0 + 0.3 * light));
    return lerp(col, lc, a * lerp(lerp(0.72, 0.9, light), 0.58, dark)) + lc * a * 0.34 * dark;
}

// ---------- голос: Шёлк ----------

// Шёлк по мотивам LiveKit Aura — перенос design/glass/voice: 32 нити — одна и та
// же линия, искажённая синусами со своей фазой; вместе они вьются, как дым.
// Волны бегут вдоль капсулы (минус у фазы по x). Фраза густит дым и раскручивает
// нити, слог трогает только яркость. Координаты — px макета от центра пилюли.
// Рисунок крупнее капсулы в SILK_ZOOM раз, а нити бесконечны: они уходят под
// кромку, и у дыма нет своих концов и краёв — его обрезает только стекло.
// На крупном рисунке завитков на длину стало мало, а нити сливались в одно
// полотно: частота завитков выше, чем у эскиза (SILK_CURL 2.1 против 1.7), и фазы
// нитей разведены шире (SILK_SPREAD) — в складках проступают волокна.
static const float SILK_SEED = 0.6;
static const float SILK_GAIN = 2.1;
static const float SILK_ZOOM = 1.6;
static const float SILK_CURL = 2.1;
static const float SILK_SPREAD = 1.3;
static const int SILK_STRANDS = 32;

struct Silk { float d; float t; float body; };

Silk silkField(float2 q, float hh, float ph, float flow, float level) {
    float2 base = q / (hh * SILK_ZOOM);
    // Нити держатся у оси: сердцевина яркая и плотная, по краям — волокна дыма.
    float amp = lerp(0.07, 0.28, ph);
    float n = (float)SILK_STRANDS;
    float acc = 0.0, accT = 0.0, wide = 0.0;
    [loop] for (int i = 0; i < SILK_STRANDS; i++) {
        float fi = (float)i / n;
        float2 pp = base;
        float fr = SILK_CURL, a = amp;
        [unroll] for (int j = 0; j < 3; j++) {
            float fj = (float)j;
            pp += a * float2(sin(pp.y * fr * 1.3 + fi * 2.4 * SILK_SPREAD + SILK_SEED + fj * 1.7 + flow * (0.6 + 0.5 * fj)),
                             sin(pp.x * fr + fi * 3.1 * SILK_SPREAD + SILK_SEED * 1.3 + fj * 2.3 - flow * (1.0 + 0.6 * fj)));
            fr *= 1.7;
            a *= 0.6;
        }
        float d = abs(pp.y);
        // Волокно — плотная сердцевина в пару пикселей и слабый ореол вокруг. Оно
        // тонкое относительно рисунка: на крупном рисунке толстые волокна сливаются
        // в туман, а тонкие дают складки шёлка.
        float w = exp(-pow(d / 0.05, 1.4)) + 0.06 / (1.0 + d * d / 0.0156);
        acc += w;
        accT += w * fi;
        wide += 1.0 / (1.0 + d * d / 0.2);
    }
    Silk s;
    s.t = accT / max(acc, 1e-4);
    // Нити складываются, а не усредняются: где они сходятся, свет густеет. Яркость
    // отмерена на 24 нити: лишние нити дробят свет на волокна, а не густят его.
    float k = 24.0 / n;
    s.d = 1.0 - exp(-acc * k * 0.13 * SILK_GAIN * lerp(0.5, 1.0, ph) * (0.88 + 0.24 * level));
    s.body = (1.0 - exp(-wide * k * 0.05)) * lerp(0.5, 1.0, ph);
    return s;
}

// Шёлк слоем с предумноженной альфой поверх стекла. На тёмном он светится:
// свет складывается с фоном, сердцевина уходит в белое. На светлом светить
// нечем — там полупрозрачные волокна густого цвета и чуть светлее ось. Под
// нитями — собственное тело дыма, полупрозрачная сине-фиолетовая подложка: на
// ней ось читается как свет, а стекло вокруг остаётся чистым.
float4 voiceSilk(float2 p, float S, float tone) {
    float ph = uVoice.y;
    Silk s = silkField((p - uPill.xy) / S, uPill.w / S * 0.5, ph, uVoice.w, uVoice.z);
    float3 bodyInk = lerp(float3(0.16, 0.38, 0.92), float3(0.42, 0.28, 0.90), s.t);
    float bodyA = s.body * lerp(0.12, 0.08, tone);
    float4 body = float4(bodyInk * bodyA, bodyA);
    float3 glow = lerp(float3(0.10, 0.84, 1.0), float3(0.58, 0.42, 1.0), s.t);
    float3 e = lerp(glow, 1.0, smoothstep(0.7, 1.0, s.d) * 0.5) * s.d;
    // Сложение света (screen) одной альфой по каналам не выразить: слой даёт
    // e + (1 − ā)·фон, где ā — среднее e; rgb больше альфы — это и есть сложение.
    float4 darkLayer = float4(e, (e.r + e.g + e.b) / 3.0);
    float3 ink = lerp(float3(0.0, 0.58, 1.0), float3(0.50, 0.30, 1.0), s.t);
    ink = lerp(ink, float3(0.74, 0.95, 1.0), smoothstep(0.84, 1.0, s.d) * 0.3);
    float la = pow(max(s.d, 0.0), 1.6) * 0.7;
    float4 lightLayer = float4(ink * la, la);
    return over(lerp(darkLayer, lightLayer, tone), body);
}

// ---------- значки: расстояния в долях рамки значка ----------

float iconCover(float d, float S) { return 1.0 - smoothstep(-0.5, 0.5, d); }

float iconDist(float2 p, out float alphaMul) {
    alphaMul = 1.0;
    float size = uIcon.z;
    float2 q = (p - uIcon.xy) / size + 0.5;      // 0..1 в рамке значка
    float kind = uIcon.w;
    float prog = saturate(uIconFx.x);
    float big = 1e6;
    if (kind < 1.5) {
        // Точка: дышит прозрачностью, вокруг мягкий ореол того же цвета.
        alphaMul = lerp(0.6, 1.0, uIconFx.z);
        return (length(q - 0.5) - 0.16) * size;
    }
    float w = 0.06;   // половина толщины штриха
    if (kind < 2.5) {
        // Галочка прорисовывается штрихом по длине ломаной.
        float2 a = float2(0.08, 0.52), b = float2(0.38, 0.80), c = float2(0.92, 0.20);
        float l1 = length(b - a), l2 = length(c - b);
        float target = saturate(prog / 0.8) * (l1 + l2);
        float d = big;
        if (target > 0.0) d = sdSegment(q, a, a + (b - a) * min(target, l1) / l1);
        if (target > l1) d = min(d, sdSegment(q, b, b + (c - b) * (target - l1) / l2));
        return (d - w) * size;
    }
    if (kind < 3.5) {
        float first = saturate(prog / 0.5), second = saturate((prog - 0.4) / 0.5);
        float d = big;
        if (first > 0.0) d = sdSegment(q, float2(0.16, 0.16), lerp(float2(0.16, 0.16), float2(0.84, 0.84), first));
        if (second > 0.0) d = min(d, sdSegment(q, float2(0.84, 0.16), lerp(float2(0.84, 0.16), float2(0.16, 0.84), second)));
        return (d - w) * size;
    }
    if (kind < 4.5) {
        float grow = saturate(prog / 0.65), dot_ = saturate((prog - 0.65) / 0.35);
        float d = big;
        if (grow > 0.0) d = sdSegment(q, float2(0.5, 0.06), lerp(float2(0.5, 0.06), float2(0.5, 0.62), grow)) - w;
        if (dot_ > 0.0) d = min(d, length(q - float2(0.5, 0.88)) - 0.07 * dot_);
        return d * size;
    }
    if (kind < 5.5) {
        float h = 0.45 * saturate(prog * 1.4);
        float d = min(sdRoundBox(q - float2(0.5 - 0.264, 0.5), float2(0.12, h), 0.12),
                      sdRoundBox(q - float2(0.5 + 0.264, 0.5), float2(0.12, h), 0.12));
        return d * size;
    }
    // Микрофон: капсула, дуга-держатель и ножка.
    alphaMul = saturate(prog);
    float capsule = sdRoundBox(q - float2(0.5, 0.30), float2(0.20, 0.26), 0.20);
    float2 c = q - float2(0.5, 0.38);
    float ring = abs(length(c / float2(0.36, 0.33)) - 1.0) * 0.33 - 0.045;
    ring = max(ring, -c.y);          // только нижняя половина дуги
    float stem = sdSegment(q, float2(0.5, 0.76), float2(0.5, 0.96)) - 0.045;
    return min(capsule, min(ring, stem)) * size;
}

float4 ps_main(float4 pos : SV_Position) : SV_Target {
    float2 p = pos.xy;
    float S = uView.w;
    float m = saturate(uGlass.x);
    float tone = uTone.y;

    // ---------- стекло ----------
    float2 n;
    float dist = shapeDist(p, n);
    float cover = saturate(0.5 - dist);
    float sd = shape(p - float2(0.0, 8.0 * S));
    float shadow = uTone.w * m * 0.035 * exp(-max(sd, 0.0) / (30.0 * S)) * smoothstep(-30.0 * S, 0.0, sd);
    float4 result = float4(0.0, 0.0, 0.0, shadow * (1.0 - cover));
    float2 voiceP = p;

    if (cover > 0.0 && m > 0.001) {
        float inside = max(-dist, 0.0);
        float2 nl;
        float insideL = max(-lensDist(p, nl), 0.0);
        float t = saturate(1.0 - insideL / uGlass.z);
        // Выборка у кромки идёт внутрь: A > h, кромка показывает перевёрнутый фон.
        float d = uGlass.y * m * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
        float3 col = sceneBlur(p - nl * d, uTone.z * m);
        // Голос у кромки чуть ломается вместе со стеклом, но слабее фона: при полном
        // смещении кромка отражала нити «стеблями» до самого края.
        voiceP = p - nl * d * 0.3;
        col = col * lerp(1.0, 1.015, m) + 0.086 * m;
        col = lerp(col, float3(1.0, 0.34, 0.38), uTone.x * m);

        // Блик: полоса 1 px цвета контента через vibrant-матрицу, два источника.
        float2 L = uLight.xy;
        float rim = 1.0 - smoothstep(0.0, 1.0 * S, inside);
        float w = pow(max(dot(n, L), 0.0), 3.0) + pow(max(-dot(n, L), 0.0), 3.0);
        float l = luma(col);
        float3 vib = saturate(1.45 * (l + 2.07 * (col - l)) + 0.05);
        col = lerp(col, vib, rim * (0.5 + 0.5 * w) * m);
        // Тёмная кромка iOS 27: на торцах толще и темнее.
        if (inside < 1.6 * S) {
            float2 tg = float2(-n.y, n.x);
            float curv = length(shapeNormal(p + tg * 2.0 * S) - shapeNormal(p - tg * 2.0 * S)) / 4.0;
            float ends = saturate(curv * 28.0 * S);
            float width = lerp(0.5, 1.0, ends) * S;
            float mul = lerp(0.925, 0.83, ends);
            float band = 1.0 - smoothstep(width * 0.6, width + 0.4 * S, inside);
            col *= lerp(1.0, mul, band * m);
        }
        // Обход света: узкий лепесток у кромки вокруг направления на источник.
        float wide = (1.8 + 0.9 * uLight.w) * S;
        if (inside < wide + 0.5 * S) {
            float c = dot(n, L);
            float lobe = pow(max(c, 0.0), 6.0) + 0.5 * pow(max(-c, 0.0), 6.0);
            float k = lobe * uLight.z * m;
            float bright = smoothstep(0.5, 0.85, luma(col));
            float band = 1.0 - smoothstep(0.3 * S, wide, inside);
            col += (1.0 - col) * band * k * (1.0 - 0.6 * bright);
            float edge = 1.0 - smoothstep(0.35 * S, 1.25 * S, inside);
            col *= 1.0 - 0.42 * bright * edge * k;
        }
        col = statusRim(col, p, inside, S);

        // Доля слоя: в покое середину отдаём живому композитору, кромку — нет:
        // там фон смещён больше пикселя и запоздание захвата не видно.
        float edgeZone = 1.0 - smoothstep(1.0 * S, 2.0 * S, inside);
        float statusZone = uStatus.x > 0.003 ? 1.0 - smoothstep(uStatus.w * S, (uStatus.w * 1.7 + 6.0) * S, inside) : 0.0;
        float own = max(max(smoothstep(0.2, 0.55, t), edgeZone), statusZone);
        float a = lerp(1.0, own, uGlass.w) * cover;
        result = over(float4(col * a, a), result);
    }

    // ---------- голос: поверх стекла, под значком и подписью ----------
    if (uVoice.x > 0.003 && cover > 0.0) {
        // У самой кромки голос гаснет: блик и тёмная кромка остаются поверх него.
        float keep = smoothstep(0.6 * S, 2.2 * S, max(-dist, 0.0));
        result = over(voiceSilk(voiceP, S, tone) * (uVoice.x * cover * keep), result);
    }

    // ---------- значок ----------
    if (uIconFx.y > 0.003) {
        float2 di = p - uIcon.xy;
        float r2 = dot(di, di) / (S * S);
        // Ореол под значком: тон, обратный тону значка, — цветная точка не теряется на пёстром.
        if (r2 < 400.0) {
            float halo = exp(-r2 / 72.0) * uIconFx.y * 0.42;
            float3 haloCol = tone > 0.5 ? float3(1.0, 1.0, 1.0) : float3(0.0, 0.0, 0.0);
            result = over(float4(haloCol * halo, halo), result);
        }
        float alphaMul;
        float d = iconDist(p, alphaMul);
        float4 ic = lerp(uIconDark, uIconLight, tone);
        float cov = iconCover(d, S) * alphaMul * uIconFx.y * ic.a;
        if (uIcon.w < 1.5) {
            float glow = exp(-max(d, 0.0) / (3.0 * S)) * (0.18 + 0.12 * uIconFx.z) * uIconFx.y;
            cov = max(cov, glow * (1.0 - cov));
        }
        result = over(float4(ic.rgb * cov, cov), result);
    }

    // ---------- подпись ----------
    if (uLabelFx.x > 0.003) {
        float2 lp = p - uLabel.xy;
        float reach = 6.0 * S;
        if (lp.x > -reach && lp.y > -reach && lp.x < uLabel.z + reach && lp.y < uLabel.w + reach) {
            float2 uv = lp / uView.xy;
            float2 cov = uText.SampleLevel(uSamp, uv, 0.0).rg;
            float blur = uLabelFx.y * S;
            float halo = 0.0;
            // Ореол — размытая маска самих букв: контраст добирается вокруг текста, а
            // не матовостью стекла. Размытие появления — тем же ядром.
            float2 accCov = 0.0; float accW = 0.0;
            [unroll] for (int i = 0; i < 12; i++) {
                float fi = (float)i;
                float ang = fi * 2.39996323;
                float rr = 3.0 * S * sqrt((fi + 0.5) / 12.0);
                float k = 1.0 - 0.5 * fi / 12.0;
                float2 o = float2(cos(ang), sin(ang));
                float2 c2 = uText.SampleLevel(uSamp, uv + o * rr / uView.xy, 0.0).rg;
                halo += (c2.r + c2.g) * k;
                if (blur > 0.6) accCov += uText.SampleLevel(uSamp, uv + o * blur * sqrt((fi + 0.5) / 12.0) / uView.xy, 0.0).rg * k;
                accW += k;
            }
            halo = saturate(halo / accW * 1.6) * uLabelFx.z * uLabelFx.x;
            if (blur > 0.6) cov = accCov / accW;
            float3 haloCol = tone > 0.5 ? float3(1.0, 1.0, 1.0) : float3(0.016, 0.024, 0.04);
            result = over(float4(haloCol * halo, halo), result);
            float4 tc = lerp(uTitleDark, uTitleLight, tone);
            float4 dc = lerp(uDetailDark, uDetailLight, tone);
            float at = cov.r * tc.a * uLabelFx.x;
            float ad = cov.g * dc.a * uLabelFx.x;
            float4 text = float4(tc.rgb * at + dc.rgb * ad, saturate(at + ad));
            result = over(text, result);
        }
    }
    return result;
}
"""
