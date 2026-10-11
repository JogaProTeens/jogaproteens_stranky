/* Shared by the homepage and the blog pages (needs the "three" import map in <head>). */
/* Dandelion seed: drifts across the page on a gentle wind, now and then. */
(() => {
  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (REDUCED) return;                              // honour reduced-motion
  const PHONE = () => innerWidth < 860;

  const MODEL      = '/brand-assets/models/dandelion-seed.glb';
  const FIRST_WAIT = 12000;                          // first flight after ~12s
  const GAP_MIN    = 45000, GAP_MAX = 95000;         // then every 45-95s
  const FALL_MS    = 25500;                          // ~25.5s to fall (15% quicker)
  const MAX_TILT   = Math.PI/2;                      // 90°: achene may reach horizontal, never above

  let THREE, renderer, scene, camera, seed, canvas, running = false, raf = 0;

  const rand = (a, b) => a + Math.random() * (b - a);

  // jsDelivr first; esm.sh as a fallback if it is unreachable
  async function loadThree(){
    try {
      const T = await import('three');
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
      return [T, GLTFLoader];
    } catch (e) {
      console.info('primary CDN unavailable, trying fallback');
      const base = 'https://esm.sh/three@0.184.0';
      const T = await import(base);
      const { GLTFLoader } = await import(base + '/examples/jsm/loaders/GLTFLoader.js');
      return [T, GLTFLoader];
    }
  }

  async function init(){
    let GLTFLoader;
    [THREE, GLTFLoader] = await loadThree();

    canvas = document.createElement('canvas');
    canvas.id = 'seed-canvas';
    document.body.appendChild(canvas);

    renderer = new THREE.WebGLRenderer({ canvas, alpha:true, antialias:true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, PHONE() ? 1.5 : 2));
    renderer.setSize(innerWidth, innerHeight, false);

    scene  = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(35, innerWidth/innerHeight, 0.1, 100);
    camera.position.z = 10;

    scene.add(new THREE.AmbientLight(0xffffff, 1.4));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(2, 4, 5); scene.add(key);
    const rim = new THREE.DirectionalLight(0xF7C9B8, 0.7);
    rim.position.set(-3, -1, 2); scene.add(rim);

    const gltf = await new GLTFLoader().loadAsync(MODEL);
    const obj = gltf.scene;

    // centre the model on its own origin and normalise its size
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    obj.position.sub(centre);
    const target = PHONE() ? 0.46 : 0.69;   // narrow viewports magnify it
    obj.scale.setScalar(target / Math.max(size.x, size.y, size.z));

    seed = new THREE.Group();
    seed.add(obj);
    seed.visible = false;
    scene.add(seed);

    addEventListener('resize', () => {
      renderer.setPixelRatio(Math.min(devicePixelRatio, PHONE() ? 1.5 : 2));
      renderer.setSize(innerWidth, innerHeight, false);
      camera.aspect = innerWidth/innerHeight;
      camera.updateProjectionMatrix();
    }, {passive:true});

    schedule(1200);
  }

  function visibleSize(z){
    const h = 2 * Math.tan((camera.fov * Math.PI/180) / 2) * (camera.position.z - z);
    return { h, w: h * camera.aspect };
  }

  function fly(){
    if (running) return;
    running = true;

    const depth    = rand(-2.5, 1.5);                // some seeds pass nearer than others
    const { w, h } = visibleSize(depth);
    const margin   = 1.6;

    // falls from above the viewport to below it
    const startY = h/2 + margin;
    const endY   = -(h/2 + margin);

    // Horizontal track: a starting point, a slow sideways drift and two
    // overlapping sways. Every amplitude is a fraction of the visible width,
    // so the path scales to the screen instead of overshooting narrow ones.
    const baseX  = rand(-0.22, 0.22) * w;
    const drift  = rand(-0.12, 0.12) * w;
    const swayA1 = rand(0.05, 0.13) * w, swayF1 = rand(0.7, 1.5), swayP1 = rand(0, 6.28);
    const swayA2 = rand(0.02, 0.05) * w, swayF2 = rand(1.8, 3.2), swayP2 = rand(0, 6.28);
    const xLimit = w * 0.46;                         // keep it inside the frame

    const dur = FALL_MS * rand(0.85, 1.25);

    // The achene is the ballast, so the pappus never ends up below it.
    // Free spin about the vertical axis, plus a lean that may swing anywhere
    // in the lower hemisphere: down to horizontal in any direction, never above.
    seed.rotation.order = 'YXZ';
    let yaw = rand(0, 6.28);
    const yawRate = rand(-0.55, 0.55);               // spin about its own axis
    const tiltBase = rand(0.25, 0.95);               // resting lean
    const tiltAmp  = rand(0.20, 0.65);               // how much the lean breathes
    const tiltFreq = rand(0.45, 1.15);
    const azRate   = rand(-1.6, 1.6);                // the lean circles slowly
    let az = rand(0, 6.28);

    seed.rotation.set(0, yaw, 0);
    seed.position.set(baseX, startY, depth);
    seed.visible = true;
    canvas.classList.add('on');

    const t0 = performance.now();

    (function step(now){
      const t = Math.min((now - t0) / dur, 1);

      // near-constant fall, with a touch of ease so it drifts in gently
      const fall = t < .12 ? (t*t)/0.12*0.5 + t*0.5 : t;

      seed.position.y = startY + (endY - startY) * fall;
      let px = baseX + drift * t
             + Math.sin(t * Math.PI * 2 * swayF1 + swayP1) * swayA1
             + Math.sin(t * Math.PI * 2 * swayF2 + swayP2) * swayA2;
      if (px >  xLimit) px =  xLimit;                // never wander off the edge
      if (px < -xLimit) px = -xLimit;
      seed.position.x = px;

      const d = 0.016;
      yaw += yawRate * d;
      az  += azRate  * d;
      let tilt = tiltBase + Math.sin(t * Math.PI * 2 * tiltFreq) * tiltAmp;
      if (tilt < 0) tilt = -tilt;
      if (tilt > MAX_TILT) tilt = MAX_TILT;          // never above horizontal
      seed.rotation.y = yaw;
      seed.rotation.x = Math.cos(az) * tilt;
      seed.rotation.z = Math.sin(az) * tilt;

      renderer.render(scene, camera);

      if (t < 1){ raf = requestAnimationFrame(step); }
      else {
        seed.visible = false;
        canvas.classList.remove('on');
        renderer.render(scene, camera);
        running = false;
        schedule(rand(GAP_MIN, GAP_MAX));
      }
    })(t0);
  }

  function schedule(ms){
    setTimeout(() => {
      if (document.hidden) return schedule(8000);    // wait for the tab to come back
      fly();
    }, ms);
  }

  const start = () => init().catch(err => console.warn('seed animation skipped:', err));
  if ('requestIdleCallback' in window) requestIdleCallback(() => setTimeout(start, FIRST_WAIT));
  else setTimeout(start, FIRST_WAIT);
})();
