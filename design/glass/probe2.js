// Проверочный концепт второго круга: минимальный пример кусков из kit.js.
// Слушаю — капсула и свечение у значка по голосу; обработка — морф M3 в диске
// (линза от описанного круга); «Готово» и «Ошибка» — цвет итогов в кромке.
LG.register({
  id: 'probe2',
  round: 2,
  setup(ctx) {
    this.w = new ctx.Spring(160, 0.5, 0.8);
    this.mat = new ctx.Spring(0, 0.3, 0.9);
    this.status = new LG.StatusFlash();
    this.morph = new LG.Morph();
    this.program = ctx.program(ctx.glsl.header + ctx.glsl.common + ctx.glsl.morph + `
uniform vec2 uCenter; uniform vec2 uSize; uniform float uDisc;
uniform vec4 uA; uniform vec2 uAe; uniform vec4 uB; uniform vec2 uBe; uniform vec2 uMorph;
uniform vec3 uGlow; uniform float uMat;
float shape(vec2 p) {
  float pill = sdPill(p, uCenter, uSize.x, uSize.y);
  if (uDisc < 0.001) return pill;
  float disc = sdMorph(p, uCenter, uSize.y * 0.5, uA, uAe, uB, uBe, uMorph.x, uMorph.y);
  return mix(pill, disc, uDisc);
}
#define LG_LENS_SHAPE
float lensShape(vec2 p) { return sdPill(p, uCenter, max(uSize.x, uSize.y * 1.08), uSize.y * mix(1.0, 1.08, uDisc)); }
` + ctx.glsl.glass + ctx.glsl.status + ctx.glsl.touch + `
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  if (uMat < 0.002 || shape(p) > 90.0) { outColor = vec4(bg, 1.0); return; }
  Glass g = defaultGlass();
  g.materialize = uMat;
  vec4 gc = liquidGlass(p, g, bg);
  vec2 n;
  float inside = max(-shapeDist(p, n), 0.0);
  vec3 col = statusRim(gc.rgb, p, inside, gc.a);
  col = touchGlow(col, p, uGlow.xy, 30.0, uGlow.z, gc.a);
  outColor = vec4(col, 1.0);
}`);
  },
  frame(ctx, s) {
    const thinking = s.stage === 'transcribing' || s.stage === 'polishing';
    const final = s.stage === 'done' || s.stage === 'error';
    this.w.set(thinking || s.stage === 'done' ? 56 : s.targetW).step(s.dt);
    const m = this.mat.set(s.shown ? 1 : 0).step(s.dt);
    this.status.step(s);
    if (thinking) this.morph.step(s.dt); else this.morph.reset();
    const mu = this.morph.uniforms;
    const disc = thinking ? Math.max(0, Math.min(1, 1 - (this.w.value - 56) / 20)) : 0;
    const cx = ctx.W / 2;
    const cy = ctx.H / 2;
    const w = Math.max(56, this.w.value);
    const glow = s.stage === 'listening' ? s.level * s.speech : 0;
    ctx.draw(this.program, {
      uCenter: [cx, cy], uSize: [w, 56], uDisc: disc, uMat: Math.max(0, Math.min(1, m)),
      uA: mu.A, uAe: mu.Ae, uB: mu.B, uBe: mu.Be, uMorph: [mu.t, mu.rot],
      uStatus: this.status.uniform, uGlow: [cx - w / 2 + 32, cy, glow],
    });
    const fit = w >= s.targetW - 30 ? 1 : 0;
    return {
      cx, cy, labelOpacity: (thinking ? 0 : fit) * Math.min(1, m),
      hideLabel: thinking || (final && w > 90),
      trace: { w, glow, flash: this.status.flash, morph: mu.t },
    };
  },
});
