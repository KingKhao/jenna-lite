// Jenna's living galaxy: a wireframe orb in front of the real night sky. One renderer, one WebGL context, three
// passes per frame: deep space (full-screen shader: a faint nebula wash and the orb's bloom) -> the sky sphere
// (real constellations with their stick figures, a faint starfield and a few distant galaxies, turning slowly
// past a camera that sits inside it) -> clear depth -> orb (its own camera). Framework-free; depends only on the
// vendored three.js and the pure data/math in galaxy-core.js. Never talks to Jenna's backend: the app calls
// setState() and attaches audio.
import * as THREE from "./three.module.min.js";
import * as G from "./galaxy-core.js";

const NOISE = /* glsl */`
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;} vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);} vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
 vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;
 vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
 i=mod289(i);vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
 float n_=0.142857142857;vec3 ns=n_*D.wyz-D.xzx;vec4 j=p-49.0*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
 vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
 vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
 vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
 vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
 vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
 return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}`;

const ORB_VERT = /* glsl */`${NOISE}
uniform float uTime, uSpeed, uDisp, uTreble, uBass;
varying vec3 vN; varying vec3 vV; varying float vD;
void main(){
  vec3 n = normalize(position); float t = uTime * uSpeed;
  float noise = 0.5 * snoise(n * 1.2 + t) + 0.3 * snoise(n * 2.6 + t * 1.3) + 0.2 * uTreble * snoise(n * 5.5 + t * 1.8);
  float push = uBass * 0.06 * sin(uTime * 6.0 - n.y * 4.0);      // a small bass wave
  float d = clamp(noise * uDisp + push, -0.45, 0.45);
  vec3 p = n * (1.0 + d); vD = d;
  vec4 mv = modelViewMatrix * vec4(p, 1.0); vV = -mv.xyz; vN = normalize(normalMatrix * n);
  gl_Position = projectionMatrix * mv;
}`;
const ORB_FRAG = /* glsl */`
uniform vec3 uColor, uColor2; uniform float uOpacity, uFresnel;
varying vec3 vN; varying vec3 vV; varying float vD;
void main(){
  float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), uFresnel);   // edges glow, the face you look at is clear
  vec3 c = mix(uColor, uColor2, clamp(vD * 3.0, 0.0, 1.0));              // parts that push out lean to colour 2
  gl_FragColor = vec4(c, (0.012 + f) * uOpacity);   // a dense mesh adds up fast: keep the face nearly clear
}`;
const GLOW_FRAG = /* glsl */`
uniform vec3 uColor; uniform float uGlow, uLight;
varying vec3 vN; varying vec3 vV; varying float vD;
void main(){
  // back faces of a bigger shell: strongest just outside the orb, fading to nothing at the shell's edge (a halo,
  // not a disc - flip the falloff and it turns into a solid blob)
  float a = pow(abs(dot(normalize(vN), normalize(vV))), 2.6) * uGlow * mix(0.55, 0.35, uLight);
  gl_FragColor = vec4(uColor, a);
}`;
const PLAIN_VERT = /* glsl */`varying vec3 vN; varying vec3 vV; varying float vD;
void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = -mv.xyz; vN = normalize(normalMatrix * normal); vD = 0.0;
  gl_Position = projectionMatrix * mv; }`;

const SKY_VERT = /* glsl */`varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const SKY_FRAG = /* glsl */`
uniform float uTime, uAspect, uLight, uEnergy, uGlow; uniform vec3 uOrb;
varying vec2 vUv;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y); }
float fbm(vec2 p){ float s = 0.0, a = 0.5; mat2 r = mat2(0.8, -0.6, 0.6, 0.8);
  for (int i = 0; i < 5; i++){ s += a * vnoise(p); p = r * p * 2.03 + 11.7; a *= 0.5; } return s; }
float stars(vec2 p, float density, float thresh, float size, float speed){
  vec2 g = p * density, c = floor(g); float h = hash(c);
  if (h < thresh) return 0.0;
  vec2 o = vec2(hash(c + 3.1), hash(c + 7.7)) * 0.6 + 0.2; float d = length(fract(g) - o);
  float tw = 0.6 + 0.4 * sin(uTime * speed * (0.5 + h) + h * 60.0);
  return smoothstep(size, 0.0, d) * tw;
}
void main(){
  vec2 uv = vUv; vec2 sp = vec2((uv.x - 0.5) * uAspect, uv.y - 0.5);      // square in screen space
  float r = length(sp); float t = uTime * 0.012;
  vec3 dark = mix(vec3(0.012, 0.018, 0.045), vec3(0.003, 0.005, 0.014), smoothstep(0.2, 0.9, r));
  vec3 dawn = mix(vec3(0.93, 0.95, 0.98), vec3(0.84, 0.88, 0.94), smoothstep(0.1, 1.0, r));
  vec3 col = mix(dark, dawn, uLight);
  float n1 = smoothstep(0.52, 0.85, fbm(sp * 2.2 + vec2(t, -t * 0.6)));
  float n2 = smoothstep(0.55, 0.88, fbm(sp * 1.7 + vec2(-t * 0.8, t * 0.4) + 5.0));
  float n3 = smoothstep(0.56, 0.90, fbm(sp * 2.9 + vec2(t * 0.5, t) + 9.0));
  float neb = 0.30 + 0.35 * uEnergy;   // a wash behind the stars, not a feature of its own
  vec3 nebula = n1 * vec3(0.05, 0.30, 0.24) + n2 * vec3(0.20, 0.07, 0.32) + n3 * vec3(0.05, 0.12, 0.38);
  col += nebula * neb * mix(0.55, 0.22, uLight) * (uLight > 0.5 ? -0.6 : 1.0);
  float bloom = exp(-r * r * 9.0) * 0.55 + exp(-r * r * 30.0) * 0.35 + exp(-r * r * 2.2) * 0.12;
  col += uOrb * bloom * (0.18 + uGlow * 0.35 + uEnergy * 0.45) * mix(1.0, 0.35, uLight);
  col += vec3(0.75, 0.95, 1.0) * exp(-r * r * 260.0) * 0.12 * (1.0 - uLight);   // tiny pale-cyan core
  col *= mix(1.0, 0.82, smoothstep(0.45, 1.05, r));                                // vignette
  gl_FragColor = vec4(col, 1.0);
}`;
// stars: a fixed screen size from the star's magnitude (they're "at infinity"), a sharp core with a soft halo,
// and a slow twinkle - each star on its own phase so the sky shimmers instead of blinking in step
const STAR_VERT = /* glsl */`attribute float aSize; attribute vec3 aColor; attribute float aPhase;
uniform float uScale, uPx, uTime; varying vec3 vC; varying float vTw;
void main(){ vC = aColor; vTw = 0.82 + 0.18 * sin(uTime * (0.6 + aPhase * 1.7) + aPhase * 40.0);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = aSize * uScale * uPx * (0.9 + 0.1 * vTw); gl_Position = projectionMatrix * mv; }`;
const STAR_FRAG = /* glsl */`uniform float uBright, uLight; varying vec3 vC; varying float vTw;
void main(){ float d = length(gl_PointCoord - 0.5) * 2.0; if (d > 1.0) discard;
  float a = exp(-d * d * 9.0) + 0.25 * exp(-d * d * 2.2);
  vec3 c = mix(vC, vec3(0.13, 0.17, 0.27), uLight);          // on the light sky: ink-coloured stars
  gl_FragColor = vec4(c, min(1.0, a * uBright * vTw) * mix(1.0, 0.6, uLight)); }`;

// a distant galaxy, drawn once into a canvas: spiral (two log-spiral arms of dust and young blue stars around a
// warm core), edge-on (a thin bright disc with a dust lane) or elliptical (a soft warm glow)
function galaxyTexture(kind, seed, hue) {
  const r = G.rng(seed), c = document.createElement("canvas"); c.width = c.height = 256;
  const g = c.getContext("2d"), cx = 128;
  const arm = hue < 0.5 ? [150, 190, 255] : [190, 170, 255], core = [255, 228, 190];
  const dot = (x, y, rad, rgb, a) => { const gr = g.createRadialGradient(x, y, 0, x, y, rad);
    gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`); g.fillStyle = gr; g.fillRect(x - rad, y - rad, rad * 2, rad * 2); };
  if (kind === "elliptical") {
    dot(cx, cx, 120, core.join(","), 0.55); dot(cx, cx, 40, "255,240,220", 0.6);
  } else if (kind === "edge") {
    g.save(); g.translate(cx, cx); g.scale(1, 0.16);
    dot(0, 0, 118, arm.join(","), 0.55); dot(0, 0, 46, core.join(","), 0.8); g.restore();
    g.fillStyle = "rgba(8,10,20,0.55)"; g.fillRect(14, cx - 2, 228, 3);          // the dust lane
  } else {
    dot(cx, cx, 120, arm.join(","), 0.16);
    for (let k = 0; k < 2; k++) for (let i = 0; i < 520; i++) {
      const t = r(), ang = t * Math.PI * 3.1 + k * Math.PI + (r() - 0.5) * 0.5, rad = 10 + t * 104;
      const x = cx + Math.cos(ang) * rad + (r() - 0.5) * 9, y = cx + Math.sin(ang) * rad + (r() - 0.5) * 9;
      dot(x, y, 2 + r() * 5, r() < 0.25 ? "200,220,255" : arm.join(","), 0.10 + 0.25 * (1 - t));
    }
    dot(cx, cx, 34, core.join(","), 0.85); dot(cx, cx, 10, "255,250,240", 0.9);
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function colorVec(a) { return new THREE.Color(a[0], a[1], a[2]); }

export function createGalaxy(container, opts = {}) {
  const o = { seed: 7, theme: null, performance: "auto", ...opts,
              layers: { sky: true, network: true, orb: true, ...(opts.layers || {}) } };
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  const mqDark = matchMedia("(prefers-color-scheme: dark)"), mqReduce = matchMedia("(prefers-reduced-motion: reduce)");
  let theme = o.theme || store.get("galaxy-theme") || "dark";   // night mode by default; the toggle remembers a choice
  let reduced = mqReduce.matches;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.autoClear = false;
  let pxRatio = Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(pxRatio);
  renderer.domElement.className = "galaxy-canvas";
  renderer.domElement.setAttribute("aria-hidden", "true");
  container.appendChild(renderer.domElement);
  const live = document.createElement("div");   // names the state for screen readers
  live.className = "galaxy-live"; live.setAttribute("aria-live", "polite"); live.setAttribute("role", "status");
  live.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);";
  container.appendChild(live);

  // ---- pass 1: sky ----
  const skyScene = new THREE.Scene(), skyCam = new THREE.Camera();
  const skyMat = new THREE.ShaderMaterial({ vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, depthTest: false, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uAspect: { value: 1 }, uLight: { value: 0 }, uEnergy: { value: 0 }, uGlow: { value: 0.3 },
                uOrb: { value: colorVec(G.FORGE) } } });
  const skyQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), skyMat);
  skyQuad.frustumCulled = false; skyScene.add(skyQuad);

  // ---- pass 2: the sky sphere (real constellations, a faint starfield, distant galaxies) ----
  // The camera sits at the centre looking out; the sphere turns about the celestial pole, so constellations rise
  // in from one side and drift across. It starts facing Orion, Taurus and Gemini.
  const netScene = new THREE.Scene(), netCam = new THREE.PerspectiveCamera(68, 1, 0.1, 400);
  netCam.position.set(0, 0, 0);
  const netGroup = new THREE.Group(); netScene.add(netGroup);
  netGroup.rotation.y = -0.42;   // the opening view: Orion up-left of the orb, Taurus and the Pleiades above, Sirius below
  const starUniforms = (scale, bright) => ({ uScale: { value: scale }, uPx: { value: pxRatio }, uBright: { value: bright },
    uLight: { value: 0 }, uTime: { value: 0 } });
  const nodeMat = new THREE.ShaderMaterial({ vertexShader: STAR_VERT, fragmentShader: STAR_FRAG, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, uniforms: starUniforms(6.2, 1.1) });      // the named constellation stars
  const dustMat = new THREE.ShaderMaterial({ vertexShader: STAR_VERT, fragmentShader: STAR_FRAG, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, uniforms: starUniforms(5.6, 0.95) });     // the faint field
  const lineMat = new THREE.LineBasicMaterial({ color: 0x9fc6ff, transparent: true, opacity: 0.16, depthWrite: false,
    blending: THREE.AdditiveBlending });
  const galaxyMats = [];
  let net = null;
  function starGeometry(list, seedOffset) {
    const pos = new Float32Array(list.length * 3), col = new Float32Array(list.length * 3), size = new Float32Array(list.length),
      phase = new Float32Array(list.length), r = G.rng(o.seed + seedOffset);
    list.forEach((st, i) => { pos.set(st.p, i * 3); col.set(st.color, i * 3); size[i] = st.size; phase[i] = r(); });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3)); geo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
    geo.setAttribute("aSize", new THREE.BufferAttribute(size, 1)); geo.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
    return geo;
  }
  function buildNetwork(perf) {
    if (net) {
      netGroup.remove(net.points, net.lines, net.dust, ...net.galaxies);
      net.points.geometry.dispose(); net.lines.geometry.dispose(); net.dust.geometry.dispose();
      for (const m of galaxyMats.splice(0)) { m.map.dispose(); m.dispose(); }
    }
    const L = G.skyLayout(o.seed, perf);
    const lp = new Float32Array(L.lines.length * 6);
    L.lines.forEach(([a, b], i) => { lp.set(L.stars[a].p, i * 6); lp.set(L.stars[b].p, i * 6 + 3); });
    const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
    const galaxies = L.galaxies.map(gx => {
      const m = new THREE.SpriteMaterial({ map: galaxyTexture(gx.kind, gx.seed, gx.hue), transparent: true, opacity: 0.72,
        depthWrite: false, blending: THREE.AdditiveBlending });
      galaxyMats.push(m);
      const sp = new THREE.Sprite(m); sp.position.set(...gx.p);
      sp.scale.set(gx.size, gx.size * (gx.kind === "spiral" ? 0.45 + 0.55 * Math.abs(Math.cos(gx.tilt)) : 1), 1);
      sp.userData = { spin: gx.spin, tilt: gx.tilt }; m.rotation = gx.tilt;
      return sp;
    });
    net = { points: new THREE.Points(starGeometry(L.stars, 1), nodeMat), lines: new THREE.LineSegments(lg, lineMat),
            dust: new THREE.Points(starGeometry(L.field, 2), dustMat), galaxies,
            counts: { stars: L.stars.length, lines: L.lines.length, field: L.field.length, galaxies: galaxies.length } };
    netGroup.add(...galaxies, net.dust, net.lines, net.points);
  }

  // ---- pass 3: orb ----
  const orbScene = new THREE.Scene(), orbCam = new THREE.PerspectiveCamera(45, 1, 0.1, 50);
  orbCam.position.set(0, 0, 4.2);
  const orbUniforms = { uTime: { value: 0 }, uSpeed: { value: 0.2 }, uDisp: { value: 0.02 }, uTreble: { value: 0 }, uBass: { value: 0 },
    uColor: { value: colorVec(G.FORGE) }, uColor2: { value: colorVec(G.STATES.idle.color2) }, uOpacity: { value: 0.5 },
    uFresnel: { value: 2.6 }, uGlow: { value: 0.3 }, uLight: { value: 0 } };
  const orbMat = new THREE.ShaderMaterial({ vertexShader: ORB_VERT, fragmentShader: ORB_FRAG, uniforms: orbUniforms, wireframe: true,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const glowMat = new THREE.ShaderMaterial({ vertexShader: PLAIN_VERT, fragmentShader: GLOW_FRAG, uniforms: orbUniforms,
    side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const orbGroup = new THREE.Group(); orbScene.add(orbGroup);
  let orb = null;
  const glow = new THREE.Mesh(new THREE.IcosahedronGeometry(1.3, 5), glowMat);
  orbGroup.add(glow);
  function buildOrb(perf) {
    if (orb) { orbGroup.remove(orb); orb.geometry.dispose(); }
    orb = new THREE.Mesh(new THREE.IcosahedronGeometry(1, perf ? 12 : 24), orbMat);
    orbGroup.add(orb);
  }
  const ringMats = [], rings = [];
  [[1.55, 0.9, 0.2, 0.31], [1.65, -0.5, 1.1, -0.23], [1.75, 0.3, -0.8, 0.17]].forEach(([r, rx, rz, sp]) => {
    const m = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.0045, 6, 200), m);
    ring.rotation.set(rx, 0, rz); ring.userData.speed = sp;
    ringMats.push(m); rings.push(ring); orbGroup.add(ring);
  });

  // ---- audio taps (analysers only: what he hears never changes) ----
  let actx = null, micTap = null, playTaps = [];
  const ac = () => (actx ||= new (window.AudioContext || window.webkitAudioContext)());
  function tap(node) {
    const an = ac().createAnalyser(); an.fftSize = 256; an.smoothingTimeConstant = 0.6;
    node.connect(an); return { an, buf: new Uint8Array(an.frequencyBinCount), node };
  }
  function read(t, gain, floor) { t.an.getByteFrequencyData(t.buf); return G.audioLevels(t.buf, { gain, floor }); }

  // ---- state ----
  let state = "idle", cur = { ...G.STATES.idle }, level = { voice: 0, bass: 0, treble: 0 }, energy = 0;
  let burstUntil = 0;   // celebrate(): the orb erupts gold for a few seconds, then settles
  let perfState = { perf: false, slow: 0 }, perfMode = o.performance, clock = 0, last = performance.now(), raf = 0, fpsAvg = 60;
  let alive = true, testTone = null, firstFrame = null;
  const frameHooks = [];   // add-ons drawing in the orb layer (the helper constellation) get (dt, ctx) every frame

  function applyTheme() {
    const light = theme === "light" ? 1 : 0;
    skyMat.uniforms.uLight.value = light; nodeMat.uniforms.uLight.value = light; dustMat.uniforms.uLight.value = light;
    orbUniforms.uLight.value = light;
    const blend = light ? THREE.NormalBlending : THREE.AdditiveBlending;   // additive vanishes on a light sky
    for (const m of [nodeMat, dustMat, lineMat, orbMat, glowMat, ...ringMats, ...galaxyMats]) { m.blending = blend; m.needsUpdate = true; }
    lineMat.color.set(light ? 0x3b5578 : 0x9fc6ff);
    container.dataset.theme = theme;
  }
  function applyPerf(perf) {
    pxRatio = perf ? 1 : Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pxRatio); nodeMat.uniforms.uPx.value = pxRatio; dustMat.uniforms.uPx.value = pxRatio;
    buildOrb(perf); buildNetwork(perf); applyTheme(); resize();
  }
  function resize() {
    const w = container.clientWidth || 1, h = container.clientHeight || 1;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
    for (const c of [netCam, orbCam]) { c.aspect = w / h; c.updateProjectionMatrix(); }
    // 4.2 units back on a wide screen; on a tall phone back off so the orb spans ~58% of the width
    orbCam.position.z = Math.max(4.2, 4.17 / (w / h));
    skyMat.uniforms.uAspect.value = w / h;
  }
  const ro = new ResizeObserver(resize); ro.observe(container);
  const onReduce = e => { reduced = e.matches; };
  mqReduce.addEventListener("change", onReduce);

  function frame(now) {
    if (!alive) return;
    const dt = Math.min(0.1, Math.max(0.001, (now - last) / 1000)); last = now;
    fpsAvg = G.ease(fpsAvg, 1 / dt, 0.05, dt);
    const ps = G.perfStep(perfState, fpsAvg, dt, perfMode);
    if (ps.perf !== perfState.perf) applyPerf(ps.perf);
    perfState = ps;
    clock = G.advanceClock(clock, dt, reduced);
    const tgt = G.STATES[state];
    cur = G.easeParams(cur, tgt, 0.05, dt);   // ~1 s to settle; nothing snaps

    // audio: the mic only while listening, her playback while speaking, synthetic speech when there's no real tap
    let raw = { voice: 0, bass: 0, treble: 0 };
    if (state === "listening" && micTap && actx.state === "running") raw = read(micTap, 2.4, 0.04);
    else if (state === "speaking" || testTone) {
      // real audio only counts when the audio clock is actually running (browsers suspend it until a tap)
      const running = actx && actx.state === "running" && playTaps.length;
      const heard = running ? playTaps.map(t => read(t, 1.3, 0)).reduce((a, b) => (b.voice > a.voice ? b : a), raw) : null;
      raw = heard ? heard : G.syntheticLevel(clock);
    } else if (state === "listening") raw = G.syntheticLevel(clock * 0.8);
    level = { voice: G.smoothLevel(level.voice, raw.voice, dt), bass: G.smoothLevel(level.bass, raw.bass, dt),
              treble: G.smoothLevel(level.treble, raw.treble, dt) };
    // the galaxy answers HER (speaking / thinking), not him
    let drive = state === "speaking" || state === "processing" || testTone ? Math.max(level.voice, state === "processing" ? 0.25 : 0) : 0;
    const burst = reduced ? 0 : Math.max(0, (burstUntil - performance.now()) / 3500);
    if (burst > 0) drive = Math.max(drive, 0.35 + 0.65 * burst);
    energy = G.ease(energy, drive, drive > energy ? 0.12 : 0.04, dt);

    // orb
    const cyc = tgt.cycle ? 0.5 + 0.5 * Math.sin(clock * 0.9) : 0;
    const c1 = cur.color.map((v, i) => v + (cur.color2[i] - v) * cyc * 0.7);
    if (burst > 0) { const gold = [1.0, 0.78, 0.25]; for (let i = 0; i < 3; i++) c1[i] += (gold[i] - c1[i]) * burst * 0.8; }
    orbUniforms.uColor.value.setRGB(...c1); orbUniforms.uColor2.value.setRGB(...cur.color2);
    orbUniforms.uTime.value = clock; orbUniforms.uSpeed.value = cur.noiseSpeed;
    orbUniforms.uDisp.value = G.displacementScale(cur, clock, level) * (1 + (tgt.cycle ? 0.15 * Math.sin(clock * 2.4) : 0));
    orbUniforms.uTreble.value = level.treble; orbUniforms.uBass.value = level.bass;
    orbUniforms.uOpacity.value = cur.opacity; orbUniforms.uFresnel.value = cur.fresnel;
    orbUniforms.uGlow.value = cur.glow + level.voice * 0.4;
    orbGroup.rotation.y += cur.rot * dt; orbGroup.rotation.x = Math.sin(clock * 0.13) * 0.12;
    const s = 1 + level.voice * 0.06 + level.bass * 0.04; orb.scale.setScalar(s); glow.scale.setScalar(s);
    rings.forEach((r, i) => { r.rotation.y += r.userData.speed * dt * (1 + cur.rot * 2); ringMats[i].opacity = cur.rings * 0.35;
      ringMats[i].color.setRGB(...c1); });

    // the sky: turns about the celestial pole (a constellation crosses the screen in ~6 minutes) while the view
    // drifts slowly north and south so the Dipper and Scorpius come round too. When she speaks the figures light up.
    netGroup.rotation.y += (0.0042 + energy * 0.006) * dt * (reduced ? 0.25 : 1);
    const pitch = -0.02 + 0.32 * Math.sin(clock * 0.0045), yawWobble = Math.sin(clock * 0.0031) * 0.08;
    netCam.lookAt(Math.sin(yawWobble) * 10, Math.tan(pitch) * 10, -10);
    lineMat.opacity = (theme === "light" ? 0.22 : 0.16) + energy * 0.45;
    nodeMat.uniforms.uBright.value = 1.0 + energy * 0.5; nodeMat.uniforms.uTime.value = clock; dustMat.uniforms.uTime.value = clock;
    for (const gx of net.galaxies) gx.material.rotation = gx.userData.tilt + clock * gx.userData.spin;

    // sky
    skyMat.uniforms.uTime.value = clock; skyMat.uniforms.uEnergy.value = energy; skyMat.uniforms.uGlow.value = cur.glow;
    skyMat.uniforms.uOrb.value.setRGB(...c1);

    renderer.setClearColor(theme === "light" ? 0xeef2f8 : 0x02040b, 1);
    renderer.clear();
    if (o.layers.sky) renderer.render(skyScene, skyCam);
    if (o.layers.network) renderer.render(netScene, netCam);
    renderer.clearDepth();
    for (const h of frameHooks) { try { h(dt, { clock, reduced, energy, state, color: c1, perf: perfState.perf }); } catch (e) { console.warn("galaxy hook", e); } }
    if (o.layers.orb) renderer.render(orbScene, orbCam);
    if (firstFrame) { firstFrame(); firstFrame = null; }
    raf = requestAnimationFrame(frame);
  }

  buildOrb(false); buildNetwork(false); applyTheme(); resize();
  live.textContent = G.STATE_LABELS[state];
  raf = requestAnimationFrame(frame);

  return {
    setState(s) { if (!G.STATES[s] || s === state) return; state = s; live.textContent = G.STATE_LABELS[s]; },
    celebrate() { burstUntil = performance.now() + 3500; },
    getState: () => state,
    setTheme(t) { theme = t === "light" ? "light" : "dark"; store.set("galaxy-theme", theme); applyTheme(); },
    getTheme: () => theme,
    setPerformance(mode) { perfMode = mode; const ps = G.perfStep(perfState, fpsAvg, 0, mode); if (ps.perf !== perfState.perf) applyPerf(ps.perf); perfState = ps; },
    setReducedMotion(on) { reduced = !!on; },
    attachMic(stream) { this.detachMic(); try { micTap = tap(ac().createMediaStreamSource(stream)); } catch (e) { micTap = null; } },
    detachMic() { if (micTap) { try { micTap.node.disconnect(micTap.an); } catch (e) {} micTap = null; } },
    // Tap an <audio> element she's speaking through. The element is routed source -> destination unchanged;
    // the analyser only listens.
    attachPlayback(el) {
      try { const src = ac().createMediaElementSource(el); src.connect(ac().destination); const t = tap(src); playTaps.push(t);
        el.addEventListener("ended", () => { playTaps = playTaps.filter(x => x !== t); try { src.disconnect(); } catch (e) {} }, { once: true });
        if (actx.state === "suspended") actx.resume(); } catch (e) {}
    },
    testTone(on) {   // a test signal for the demo: the galaxy should light up
      if (on && !testTone) { const osc = ac().createOscillator(), g = ac().createGain(), lfo = ac().createOscillator(), lg = ac().createGain();
        // harmonic-rich like a voice (a pure sine has nothing in the 10-60% "voice" bins), syllable-rate wobble
        osc.type = "sawtooth"; osc.frequency.value = 180; lfo.frequency.value = 4.5; lg.gain.value = 0.12; g.gain.value = 0.14;
        lfo.connect(lg); lg.connect(g.gain); osc.connect(g); g.connect(ac().destination); const t = tap(g); playTaps.push(t);
        osc.start(); lfo.start(); testTone = { osc, lfo, g, t }; if (actx.state === "suspended") actx.resume(); }
      if (!on && testTone) { testTone.osc.stop(); testTone.lfo.stop(); testTone.g.disconnect(); playTaps = playTaps.filter(x => x !== testTone.t); testTone = null; }
    },
    // for add-ons: the orb layer (scene + camera) and a per-frame hook; returns an unhook function
    orbLayer: () => ({ scene: orbScene, camera: orbCam, container }),
    onFrame(fn) { frameHooks.push(fn); return () => { const i = frameHooks.indexOf(fn); if (i >= 0) frameHooks.splice(i, 1); }; },
    debug: () => ({ state, theme, perf: perfState.perf, fps: Math.round(fpsAvg), energy: +energy.toFixed(3), level: { ...level },
                    pxRatio, counts: net && net.counts, orbDetail: orb && orb.geometry.parameters.detail, reduced }),
    ready: () => new Promise(r => { firstFrame = r; }),
    destroy() {
      alive = false; cancelAnimationFrame(raf); ro.disconnect(); mqReduce.removeEventListener("change", onReduce);
      this.testTone(false); this.detachMic(); playTaps = [];
      if (actx) { actx.close(); actx = null; }
      for (const sc of [skyScene, netScene, orbScene]) sc.traverse(x => { if (x.geometry) x.geometry.dispose(); });
      for (const m of [skyMat, nodeMat, dustMat, lineMat, orbMat, glowMat, ...ringMats]) m.dispose();
      for (const m of galaxyMats) { m.map.dispose(); m.dispose(); }
      renderer.dispose(); renderer.forceContextLoss();
      renderer.domElement.remove(); live.remove();
    },
  };
}
