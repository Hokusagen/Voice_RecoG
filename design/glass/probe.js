// Проверочный концепт: общее стекло на капсуле, ширина пружиной.
LG.register({
  id: 'probe',
  setup(ctx) {
    this.w = new ctx.Spring(260, 0.5, 0.7);
    this.reveal = new ctx.Spring(0, 0.4, 0.75);
    this.program = ctx.program(ctx.glsl.header + ctx.glsl.common + `
uniform vec2 uCenter; uniform vec2 uSize;
float shape(vec2 p) { return sdPill(p, uCenter, uSize.x, uSize.y); }
` + ctx.glsl.glass + `
void main() {
  vec2 p = cssCoord(gl_FragCoord.xy);
  vec3 bg = sceneAt(p, 0.0);
  Glass g = defaultGlass();
  outColor = vec4(liquidGlass(p, g, bg).rgb, 1.0);
}`);
  },
  frame(ctx, s) {
    this.w.set(s.targetW).step(s.dt);
    const r = this.reveal.set(s.shown ? 1 : 0).step(s.dt);
    const h = 56 * Math.max(0, r);
    ctx.draw(this.program, { uCenter: [ctx.W / 2, ctx.H / 2], uSize: [this.w.value * Math.max(0, r), h] });
    return { cx: ctx.W / 2, cy: ctx.H / 2, labelOpacity: Math.max(0, Math.min(1, r)) };
  },
});
