(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const MODES = Object.freeze({ HUMAN: "human", HOLOGRAM: "hologram" });
  const MORPH_ALIASES = Object.freeze({
    blinkLeft: ["eyeBlinkLeft", "EyeBlinkLeft", "blinkLeft"],
    blinkRight: ["eyeBlinkRight", "EyeBlinkRight", "blinkRight"],
    jaw: [
      "jawOpen", "JawOpen", "mouthOpen", "viseme_aa", "viseme_DD", "viseme_kk",
      "viseme_CH", "viseme_SS", "viseme_nn", "viseme_RR",
    ],
    round: ["mouthFunnel", "mouthPucker", "viseme_O", "viseme_U"],
    wide: ["mouthStretchLeft", "mouthStretchRight", "viseme_E", "viseme_I"],
    smile: ["mouthSmileLeft", "mouthSmileRight", "mouthSmile"],
    brow: ["browInnerUp", "browOuterUpLeft", "browOuterUpRight"],
  });

  const RIG_ROLE_ALIASES = Object.freeze({
    head: ["mixamorighead", "head", "headjoint", "headbone", "headtop", "headmesh"],
    neck: ["mixamorigneck", "neck", "neckjoint", "neckbone"],
    chest: [
      "mixamorigspine2", "mixamorigspine1", "upperchest", "chest", "spine3", "spine2",
      "spine1", "spine",
    ],
    hips: ["mixamorighips", "hips", "pelvis", "rootjoint"],
    leftShoulder: [
      "mixamorigleftshoulder", "leftshoulder", "shoulderleft", "shoulderl", "clavicleleft",
      "claviclel",
    ],
    rightShoulder: [
      "mixamorigrightshoulder", "rightshoulder", "shoulderright", "shoulderr", "clavicleright",
      "clavicler",
    ],
    leftUpperArm: [
      "mixamorigleftarm", "leftupperarm", "upperarmleft", "upperarml", "leftarm", "armleft",
      "arml",
    ],
    rightUpperArm: [
      "mixamorigrightarm", "rightupperarm", "upperarmright", "upperarmr", "rightarm", "armright",
      "armr",
    ],
  });

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function normalizeName(name) {
    return String(name || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  }

  function inferRigRole(name) {
    const normalized = normalizeName(name);
    if (!normalized) return null;

    const entries = Object.entries(RIG_ROLE_ALIASES);
    for (const [role, aliases] of entries) {
      for (const alias of aliases) {
        if (
          normalized === alias
          || normalized.endsWith(alias)
          || (alias.length >= 7 && normalized.includes(alias))
        ) return role;
      }
    }
    return null;
  }

  function speechGestureEnergy(signals = {}) {
    if (signals.state !== "speaking") return 0;
    const mouthOpen = clamp(Number(signals.mouthOpen) || 0, 0, 1);
    const jaw = clamp(Number(signals.jaw) || 0, 0, 1);
    const mouthWide = clamp(Number(signals.mouthWide) || 0, 0, 1);
    return clamp(0.18 + mouthOpen * 0.52 + jaw * 0.34 + mouthWide * 0.12, 0, 1);
  }

  function perspectiveFitDistance({
    width = 0,
    height = 0,
    depth = 0,
    fovDegrees = 28,
    aspect = 1,
    padding = 1.12,
  } = {}) {
    const safeWidth = Math.max(0, Number(width) || 0);
    const safeHeight = Math.max(0, Number(height) || 0);
    const safeDepth = Math.max(0, Number(depth) || 0);
    const safeFov = clamp(Number(fovDegrees) || 28, 1, 179);
    const safeAspect = Math.max(0.05, Number(aspect) || 1);
    const safePadding = Math.max(1, Number(padding) || 1);
    const tanHalfFov = Math.tan((safeFov * Math.PI / 180) / 2);
    if (!Number.isFinite(tanHalfFov) || tanHalfFov <= 0) return 4.7;

    const heightDistance = safeHeight / (2 * tanHalfFov);
    const widthDistance = safeWidth / (2 * tanHalfFov * safeAspect);
    const depthAllowance = safeDepth * 0.5;
    return Math.max(
      0.5,
      (Math.max(heightDistance, widthDistance) + depthAllowance) * safePadding,
    );
  }

  class ThreeAvatarRenderer {
    constructor(canvas, controller, options = {}) {
      this.canvas = canvas;
      this.controller = controller;
      this.mode = options.mode || MODES.HUMAN;
      this.modelUrl = options.modelUrl || "";
      this.onStatus = options.onStatus || (() => {});
      this.signals = controller.signals;
      this.materials = new Set();
      this.morphBindings = new Map();
      this.rig = Object.create(null);
      this.rigScores = Object.create(null);
      this.appliedMotion = new Map();
      this.pointerYaw = 0;
      this.pointerPitch = 0;
      this.currentYaw = 0;
      this.currentPitch = 0;
      this.pointerActive = false;
      this.attentionPulse = 0;
      this.startTime = performance.now();
      this.lastFrameTime = this.startTime;
      this.raf = 0;
      this.destroyed = false;
      this.procedural = false;
      this.framedRoot = null;
      this.previousTouchAction = canvas.style.touchAction;
      canvas.style.touchAction = "none";
      this.reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches || false;
      this.unsubscribe = controller.subscribe(signals => { this.signals = signals; });
      this.onPointerMove = event => this.trackPointer(event);
      this.onPointerDown = event => this.pointerDown(event);
      this.onPointerUp = event => this.pointerUp(event);
      this.onPointerCancel = event => this.pointerUp(event);
      this.onPointerLeave = () => {
        this.pointerActive = false;
      };
      canvas.addEventListener("pointermove", this.onPointerMove);
      canvas.addEventListener("pointerdown", this.onPointerDown);
      canvas.addEventListener("pointerup", this.onPointerUp);
      canvas.addEventListener("pointercancel", this.onPointerCancel);
      canvas.addEventListener("pointerleave", this.onPointerLeave);
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(canvas);
    }

    async init() {
      if (!SDK.graphics?.loadThreeRuntime) {
        throw new Error("Hermes Plugin SDK graphics runtime is unavailable.");
      }
      this.onStatus("loading");
      const runtime = await SDK.graphics.loadThreeRuntime();
      if (this.destroyed) return;
      this.THREE = runtime.THREE;
      this.GLTFLoader = runtime.GLTFLoader;
      this.initScene();

      if (this.modelUrl) {
        try {
          await this.loadGLB(this.modelUrl);
          if (this.destroyed) return;
          this.onStatus("glb");
        } catch (error) {
          console.warn("[hermes-avatar] GLB load failed; using procedural fallback.", error);
          this.buildProceduralHuman();
          this.onStatus("procedural-fallback");
        }
      } else {
        this.buildProceduralHuman();
        this.onStatus("procedural");
      }

      this.applyMode();
      this.resize();
      this.render();
    }

    initScene() {
      const THREE = this.THREE;
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.08;

      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 100);
      this.camera.position.set(0, 0.12, 4.7);
      this.camera.lookAt(0, 0.05, 0);

      const hemisphere = new THREE.HemisphereLight(0xd9f8ff, 0x10151d, 1.7);
      const key = new THREE.DirectionalLight(0xffeadf, 3.2);
      key.position.set(-2.2, 3.0, 4.2);
      const rim = new THREE.DirectionalLight(0x5de7ff, 2.0);
      rim.position.set(2.8, 1.5, -2.0);
      const fill = new THREE.PointLight(0x8b78ff, 1.3, 8);
      fill.position.set(2.0, -0.2, 2.5);
      this.stateLight = new THREE.PointLight(0x51e8ff, 1.5, 7);
      this.stateLight.position.set(-1.8, 0.4, 2.1);
      this.scene.add(hemisphere, key, rim, fill, this.stateLight);
    }

    async loadGLB(url) {
      const loader = new this.GLTFLoader();
      const gltf = await loader.loadAsync(url);
      if (this.destroyed) return;

      this.root = gltf.scene || gltf.scenes?.[0];
      if (!this.root) throw new Error("GLB contains no scene.");

      this.scene.add(this.root);
      this.fitModel(this.root);
      this.indexModel(this.root);

      if (gltf.animations?.length) {
        this.mixer = new this.THREE.AnimationMixer(this.root);
        const idle = gltf.animations.find(clip => /idle|breath|stand|loop/i.test(clip.name))
          || gltf.animations[0];
        this.idleAction = this.mixer.clipAction(idle);
        this.idleAction.reset().fadeIn(0.18).play();
      }
    }

    fitModel(root) {
      const THREE = this.THREE;
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3());
      if (!Number.isFinite(size.y) || size.y <= 0) return;

      root.scale.multiplyScalar(3.25 / size.y);
      const fitted = new THREE.Box3().setFromObject(root);
      const center = fitted.getCenter(new THREE.Vector3());
      root.position.x -= center.x;
      root.position.y -= center.y - 0.05;
      root.position.z -= center.z;
      this.framedRoot = root;
    }

    frameModel(root) {
      if (!root || !this.camera || !this.THREE) return;
      const THREE = this.THREE;
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      if (
        !Number.isFinite(size.x)
        || !Number.isFinite(size.y)
        || !Number.isFinite(size.z)
        || size.y <= 0
      ) return;

      const distance = perspectiveFitDistance({
        width: size.x,
        height: size.y,
        depth: size.z,
        fovDegrees: this.camera.fov,
        aspect: this.camera.aspect,
        padding: 1.12,
      });
      this.camera.position.set(center.x, center.y, center.z + distance);
      this.camera.lookAt(center.x, center.y, center.z);
    }

    rigCandidateScore(object, role) {
      const normalized = normalizeName(object?.name);
      const aliases = RIG_ROLE_ALIASES[role] || [];
      let score = object?.isBone ? 100 : object?.isGroup ? 40 : 10;
      for (const alias of aliases) {
        if (normalized === alias) score += 40;
        else if (normalized.endsWith(alias)) score += 25;
        else if (alias.length >= 7 && normalized.includes(alias)) score += 12;
      }
      return score;
    }

    indexModel(root) {
      root.traverse(object => {
        const lower = String(object.name || "").toLowerCase();
        const role = inferRigRole(object.name);
        if (role) {
          const score = this.rigCandidateScore(object, role);
          if (!this.rig[role] || score > (this.rigScores[role] || -Infinity)) {
            this.rig[role] = object;
            this.rigScores[role] = score;
          }
        }

        if (!this.eyeLeft && /eye.*left|left.*eye/.test(lower)) this.eyeLeft = object;
        if (!this.eyeRight && /eye.*right|right.*eye/.test(lower)) this.eyeRight = object;

        if (!object.isMesh) return;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) if (material) this.captureMaterial(material);

        if (!object.morphTargetDictionary || !object.morphTargetInfluences) return;
        for (const [name, index] of Object.entries(object.morphTargetDictionary)) {
          const key = normalizeName(name);
          if (!this.morphBindings.has(key)) this.morphBindings.set(key, []);
          this.morphBindings.get(key).push({ mesh: object, index });
        }
      });

      this.head = this.rig.head || this.rig.neck || this.rig.chest || null;
      this.neck = this.rig.neck || null;
      this.chest = this.rig.chest || null;
      this.hips = this.rig.hips || null;
      this.leftShoulder = this.rig.leftShoulder || null;
      this.rightShoulder = this.rig.rightShoulder || null;
      this.leftUpperArm = this.rig.leftUpperArm || null;
      this.rightUpperArm = this.rig.rightUpperArm || null;
    }

    captureMaterial(material) {
      if (this.materials.has(material)) return;
      material.userData.__dhBase = {
        color: material.color?.clone?.() || null,
        emissive: material.emissive?.clone?.() || null,
        emissiveIntensity: material.emissiveIntensity,
        transparent: material.transparent,
        opacity: material.opacity,
        wireframe: material.wireframe,
        depthWrite: material.depthWrite,
      };
      this.materials.add(material);
    }

    material(color, roughness = 0.6, metalness = 0.01) {
      const value = new this.THREE.MeshStandardMaterial({ color, roughness, metalness });
      this.captureMaterial(value);
      return value;
    }

    sphere(name, scale, position, material, parent) {
      const mesh = new this.THREE.Mesh(
        new this.THREE.SphereGeometry(1, 34, 24),
        material,
      );
      mesh.name = name;
      mesh.scale.set(...scale);
      mesh.position.set(...position);
      (parent || this.root).add(mesh);
      return mesh;
    }

    buildProceduralHuman() {
      const THREE = this.THREE;
      this.procedural = true;
      this.root = new THREE.Group();
      this.root.name = "ProceduralDigitalHuman";
      this.scene.add(this.root);

      const skin = this.material(0x9b6349, 0.72);
      const skinLight = this.material(0xb77c5d, 0.70);
      const hair = this.material(0x151214, 0.78, 0.03);
      const eye = this.material(0xe7ece8, 0.32);
      const iris = this.material(0x2b6457, 0.38);
      const pupil = this.material(0x07090a, 0.28);
      const lip = this.material(0x7a3131, 0.58);
      const mouth = this.material(0x17090c, 0.90);
      const cloth = this.material(0x0c2635, 0.62, 0.12);

      this.sphere("Shoulders", [1.42, 0.50, 0.54], [0, -1.34, -0.10], cloth);
      this.sphere("Torso", [0.88, 0.58, 0.44], [0, -1.02, -0.03], cloth);
      this.sphere("Neck", [0.31, 0.47, 0.28], [0, -0.50, 0], skin);

      this.head = new THREE.Group();
      this.head.name = "Head";
      this.head.position.set(0, 0.36, 0);
      this.root.add(this.head);

      this.sphere("Face", [0.72, 0.92, 0.66], [0, 0, 0], skin, this.head);
      this.sphere("Jaw", [0.56, 0.44, 0.57], [0, -0.40, 0.16], skinLight, this.head);
      this.sphere("CheekLeft", [0.24, 0.20, 0.16], [-0.36, -0.05, 0.52], skinLight, this.head);
      this.sphere("CheekRight", [0.24, 0.20, 0.16], [0.36, -0.05, 0.52], skinLight, this.head);
      this.sphere("EarLeft", [0.105, 0.20, 0.075], [-0.70, 0.01, 0.02], skin, this.head);
      this.sphere("EarRight", [0.105, 0.20, 0.075], [0.70, 0.01, 0.02], skin, this.head);
      this.sphere("HairTop", [0.74, 0.40, 0.67], [0, 0.67, -0.02], hair, this.head);
      this.sphere("HairLeft", [0.17, 0.48, 0.20], [-0.60, 0.34, -0.12], hair, this.head);
      this.sphere("HairRight", [0.17, 0.48, 0.20], [0.60, 0.34, -0.12], hair, this.head);
      this.sphere("NoseBridge", [0.08, 0.23, 0.075], [0, 0, 0.62], skinLight, this.head);
      this.sphere("NoseTip", [0.115, 0.085, 0.095], [0, -0.16, 0.68], skinLight, this.head);

      this.eyeLeft = this.makeEye(-0.265, eye, iris, pupil);
      this.eyeRight = this.makeEye(0.265, eye, iris, pupil);
      this.browLeft = this.sphere("BrowLeft", [0.19, 0.035, 0.035], [-0.28, 0.37, 0.57], hair, this.head);
      this.browRight = this.sphere("BrowRight", [0.19, 0.035, 0.035], [0.28, 0.37, 0.57], hair, this.head);
      this.mouthCavity = this.sphere("MouthCavity", [0.19, 0.025, 0.028], [0, -0.34, 0.63], mouth, this.head);
      this.upperLip = this.sphere("UpperLip", [0.22, 0.028, 0.027], [0, -0.31, 0.655], lip, this.head);
      this.lowerLip = this.sphere("LowerLip", [0.22, 0.030, 0.027], [0, -0.37, 0.655], lip, this.head);
    }

    makeEye(x, eyeMaterial, irisMaterial, pupilMaterial) {
      const group = new this.THREE.Group();
      group.position.set(x, 0.18, 0.585);
      this.head.add(group);
      const white = this.sphere("EyeWhite", [0.155, 0.080, 0.055], [0, 0, 0], eyeMaterial, group);
      const iris = this.sphere("Iris", [0.056, 0.056, 0.025], [0, 0, 0.053], irisMaterial, group);
      const pupil = this.sphere("Pupil", [0.024, 0.024, 0.014], [0, 0, 0.073], pupilMaterial, group);
      group.userData.parts = { white, iris, pupil };
      return group;
    }

    trackPointer(event) {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      this.pointerYaw = clamp(x * 0.38, -0.42, 0.42);
      this.pointerPitch = clamp(-y * 0.22, -0.24, 0.24);
      this.pointerActive = true;
    }

    pointerDown(event) {
      this.trackPointer(event);
      this.attentionPulse = 1;
      try {
        this.canvas.setPointerCapture?.(event.pointerId);
      } catch {
        // Pointer capture is best-effort across browsers.
      }
    }

    pointerUp(event) {
      try {
        if (this.canvas.hasPointerCapture?.(event.pointerId)) {
          this.canvas.releasePointerCapture?.(event.pointerId);
        }
      } catch {
        // no-op
      }
      if (event.pointerType !== "mouse") this.pointerActive = false;
    }

    resize() {
      if (!this.renderer || !this.camera) return;
      const rect = this.canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / Math.max(height, 1);
      if (this.framedRoot && !this.procedural) this.frameModel(this.framedRoot);
      this.camera.updateProjectionMatrix();
    }

    setMode(mode) {
      this.mode = mode;
      this.applyMode();
    }

    applyMode() {
      if (!this.THREE) return;
      const hologram = this.mode === MODES.HOLOGRAM;
      for (const material of this.materials) {
        const base = material.userData.__dhBase || {};
        if (hologram) {
          if (material.color) material.color.set(0x49e8ff);
          if (material.emissive) material.emissive.set(0x104d60);
          if ("emissiveIntensity" in material) material.emissiveIntensity = 0.85;
          material.transparent = true;
          material.opacity = 0.72;
          material.depthWrite = false;
        } else {
          if (material.color && base.color) material.color.copy(base.color);
          if (material.emissive && base.emissive) material.emissive.copy(base.emissive);
          if ("emissiveIntensity" in material && base.emissiveIntensity !== undefined) {
            material.emissiveIntensity = base.emissiveIntensity;
          }
          material.transparent = base.transparent ?? false;
          material.opacity = base.opacity ?? 1;
          material.wireframe = base.wireframe ?? false;
          material.depthWrite = base.depthWrite ?? true;
        }
        material.needsUpdate = true;
      }
    }

    setMorph(aliases, value) {
      for (const alias of aliases) {
        const bindings = this.morphBindings.get(normalizeName(alias)) || [];
        for (const binding of bindings) {
          if (binding.mesh.morphTargetInfluences) {
            binding.mesh.morphTargetInfluences[binding.index] = clamp(value, 0, 1);
          }
        }
      }
    }

    applyGLBSignals() {
      const signals = this.signals;
      this.setMorph(MORPH_ALIASES.blinkLeft, signals.blink);
      this.setMorph(MORPH_ALIASES.blinkRight, signals.blink);
      this.setMorph(MORPH_ALIASES.jaw, Math.max(signals.jaw, signals.mouthOpen * 0.78));
      this.setMorph(MORPH_ALIASES.round, signals.mouthRound);
      this.setMorph(MORPH_ALIASES.wide, signals.mouthWide);
      this.setMorph(MORPH_ALIASES.smile, signals.smile);
      this.setMorph(MORPH_ALIASES.brow, signals.browLift);
    }

    applyProceduralSignals() {
      const signals = this.signals;
      const blinkScale = signals.blink ? 0.07 : 1;
      const gazeX = clamp(this.currentYaw * 0.55, -0.08, 0.08);
      const gazeY = clamp(-this.currentPitch * 0.45, -0.05, 0.05);

      for (const eye of [this.eyeLeft, this.eyeRight]) {
        if (!eye?.userData.parts) continue;
        eye.userData.parts.white.scale.y = 0.080 * blinkScale;
        eye.userData.parts.iris.scale.y = 0.056 * blinkScale;
        eye.userData.parts.pupil.scale.y = 0.024 * blinkScale;
        eye.userData.parts.iris.position.x = gazeX;
        eye.userData.parts.iris.position.y = gazeY;
        eye.userData.parts.pupil.position.x = gazeX;
        eye.userData.parts.pupil.position.y = gazeY;
      }

      const width = 0.20 + signals.mouthWide * 0.14
        - signals.mouthRound * 0.055 + signals.smile * 0.035;
      const height = 0.018 + signals.mouthOpen * 0.11;
      if (this.mouthCavity) {
        this.mouthCavity.scale.set(width * 0.86, height, 0.028);
        this.mouthCavity.visible = signals.mouthOpen > 0.07;
        this.mouthCavity.position.y = -0.34 - signals.jaw * 0.055;
      }
      if (this.upperLip) {
        this.upperLip.scale.x = width;
        this.upperLip.position.y = -0.31 - signals.jaw * 0.025;
      }
      if (this.lowerLip) {
        this.lowerLip.scale.x = width * (0.98 + signals.mouthRound * 0.04);
        this.lowerLip.scale.y = 0.030 + signals.mouthOpen * 0.020;
        this.lowerLip.position.y = -0.37 - signals.jaw * 0.075;
      }
      if (this.browLeft) this.browLeft.position.y = 0.37 + signals.browLift * 0.07;
      if (this.browRight) this.browRight.position.y = 0.37 + signals.browLift * 0.07;
    }

    clearMotionPose() {
      for (const [node, offset] of this.appliedMotion.entries()) {
        if (!node) continue;
        node.rotation.x -= offset.rx;
        node.rotation.y -= offset.ry;
        node.rotation.z -= offset.rz;
        node.position.x -= offset.px;
        node.position.y -= offset.py;
        node.position.z -= offset.pz;
      }
      this.appliedMotion.clear();
    }

    applyMotion(node, offset = {}) {
      if (!node) return;
      const delta = {
        rx: Number(offset.rx) || 0,
        ry: Number(offset.ry) || 0,
        rz: Number(offset.rz) || 0,
        px: Number(offset.px) || 0,
        py: Number(offset.py) || 0,
        pz: Number(offset.pz) || 0,
      };
      node.rotation.x += delta.rx;
      node.rotation.y += delta.ry;
      node.rotation.z += delta.rz;
      node.position.x += delta.px;
      node.position.y += delta.py;
      node.position.z += delta.pz;

      const previous = this.appliedMotion.get(node) || {
        rx: 0, ry: 0, rz: 0, px: 0, py: 0, pz: 0,
      };
      this.appliedMotion.set(node, {
        rx: previous.rx + delta.rx,
        ry: previous.ry + delta.ry,
        rz: previous.rz + delta.rz,
        px: previous.px + delta.px,
        py: previous.py + delta.py,
        pz: previous.pz + delta.pz,
      });
    }

    applyCharacterMotion(time, deltaTime) {
      const motion = this.reducedMotion ? 0.25 : 1;
      const lerp = 1 - Math.exp(-Math.max(deltaTime, 1 / 240) * 9.5);
      if (!this.pointerActive) {
        this.pointerYaw *= Math.exp(-deltaTime * 3.2);
        this.pointerPitch *= Math.exp(-deltaTime * 3.2);
      }
      this.currentYaw += (this.pointerYaw - this.currentYaw) * lerp;
      this.currentPitch += (this.pointerPitch - this.currentPitch) * lerp;
      this.attentionPulse *= Math.exp(-deltaTime * 3.7);

      const speech = speechGestureEnergy(this.signals) * motion;
      const idleYaw = Math.sin(time * 0.47) * 0.035 * motion;
      const idlePitch = Math.sin(time * 0.31 + 0.7) * 0.018 * motion;
      const idleRoll = Math.sin(time * 0.23 + 1.3) * 0.010 * motion;
      const breath = Math.sin(time * 1.55) * 0.008 * motion;
      const speechBeat = speech > 0
        ? (0.45 + Math.abs(Math.sin(time * 5.9)) * 0.55) * speech
        : 0;
      const speechNod = Math.sin(time * 6.4) * 0.030 * speechBeat;
      const speechTurn = Math.sin(time * 2.35 + 0.8) * 0.038 * speech;
      const speechRoll = Math.sin(time * 3.15) * 0.018 * speech;
      const attentionNod = Math.sin((1 - this.attentionPulse) * Math.PI * 1.6)
        * 0.038 * this.attentionPulse * motion;

      if (this.procedural) {
        this.applyMotion(this.head, {
          rx: this.currentPitch * 0.68 + idlePitch + speechNod + attentionNod,
          ry: this.currentYaw * 0.82 + idleYaw + speechTurn,
          rz: idleRoll + speechRoll,
        });
        this.applyMotion(this.root, {
          ry: Math.sin(time * 0.28) * 0.010 * motion + speechTurn * 0.12,
          py: breath * 0.45,
        });
        return;
      }

      const lookNode = this.rig.head || this.rig.neck || this.rig.chest || this.root;
      this.applyMotion(lookNode, {
        rx: this.currentPitch * 0.82 + idlePitch + speechNod + attentionNod,
        ry: this.currentYaw * 0.92 + idleYaw + speechTurn,
        rz: idleRoll + speechRoll,
      });

      if (this.rig.neck && this.rig.neck !== lookNode) {
        this.applyMotion(this.rig.neck, {
          rx: this.currentPitch * 0.18 + speechNod * 0.22,
          ry: this.currentYaw * 0.23 + speechTurn * 0.22,
          rz: speechRoll * 0.18,
        });
      }

      const torso = this.rig.chest || this.rig.hips || this.root;
      if (torso && torso !== lookNode) {
        this.applyMotion(torso, {
          rx: breath * 0.38 + speechBeat * 0.014,
          ry: Math.sin(time * 0.30) * 0.012 * motion + speechTurn * 0.32,
          rz: Math.sin(time * 0.39 + 0.5) * 0.008 * motion + speechRoll * 0.38,
          py: breath * 0.20,
        });
      }

      const armEnergy = speechBeat * 0.085;
      const alternating = Math.sin(time * 2.05);
      this.applyMotion(this.leftShoulder, {
        rz: armEnergy * (0.32 + Math.max(0, alternating) * 0.36),
        rx: -armEnergy * 0.24,
      });
      this.applyMotion(this.rightShoulder, {
        rz: -armEnergy * (0.32 + Math.max(0, -alternating) * 0.36),
        rx: -armEnergy * 0.24,
      });
      this.applyMotion(this.leftUpperArm, {
        rz: armEnergy * (0.42 + Math.max(0, alternating) * 0.48),
        rx: -armEnergy * 0.34,
      });
      this.applyMotion(this.rightUpperArm, {
        rz: -armEnergy * (0.42 + Math.max(0, -alternating) * 0.48),
        rx: -armEnergy * 0.34,
      });

      if (!this.rig.head && !this.rig.neck && !this.rig.chest) {
        this.applyMotion(this.root, {
          rx: this.currentPitch * 0.12 + speechNod * 0.22,
          ry: this.currentYaw * 0.30 + idleYaw * 0.45 + speechTurn * 0.28,
          rz: idleRoll * 0.32 + speechRoll * 0.24,
          py: breath * 0.18,
        });
      }
    }

    updateStateLight(time) {
      if (!this.stateLight) return;
      const colors = {
        listening: 0x55efff,
        thinking: 0x8d7cff,
        speaking: 0x53ffd0,
        error: 0xff5878,
        idle: 0x51e8ff,
      };
      this.stateLight.color.setHex(colors[this.signals.state] || colors.idle);
      this.stateLight.intensity = this.signals.state === "speaking"
        ? 1.8 + Math.sin(time * 8) * 0.35
        : 1.35;
      if (this.mode === MODES.HOLOGRAM) this.stateLight.intensity *= 1.3;
    }

    render = () => {
      if (this.destroyed || !this.renderer || !this.scene || !this.camera) return;
      const now = performance.now();
      const time = (now - this.startTime) / 1000;
      const deltaTime = clamp((now - this.lastFrameTime) / 1000, 1 / 240, 0.08);
      this.lastFrameTime = now;

      // Remove our previous additive offsets first. The GLB mixer can then write
      // the authoritative animation pose, after which interaction/speech motion
      // is layered on top instead of being overwritten by the animation clip.
      this.clearMotionPose();
      if (this.mixer) this.mixer.update(deltaTime);
      this.applyCharacterMotion(time, deltaTime);

      if (this.procedural) this.applyProceduralSignals();
      else this.applyGLBSignals();

      this.updateStateLight(time);
      this.renderer.render(this.scene, this.camera);
      this.raf = requestAnimationFrame(this.render);
    };

    destroy() {
      this.destroyed = true;
      cancelAnimationFrame(this.raf);
      this.resizeObserver?.disconnect();
      this.unsubscribe?.();
      this.clearMotionPose();
      this.canvas.style.touchAction = this.previousTouchAction;
      this.canvas.removeEventListener("pointermove", this.onPointerMove);
      this.canvas.removeEventListener("pointerdown", this.onPointerDown);
      this.canvas.removeEventListener("pointerup", this.onPointerUp);
      this.canvas.removeEventListener("pointercancel", this.onPointerCancel);
      this.canvas.removeEventListener("pointerleave", this.onPointerLeave);

      if (this.root) {
        this.root.traverse(object => {
          object.geometry?.dispose?.();
          const materials = object.material
            ? (Array.isArray(object.material) ? object.material : [object.material])
            : [];
          for (const material of materials) {
            for (const key of ["map", "normalMap", "roughnessMap", "metalnessMap", "emissiveMap"]) {
              material[key]?.dispose?.();
            }
            material.dispose?.();
          }
        });
      }
      this.renderer?.dispose();
    }
  }

  window.__HERMES_AVATAR_RENDERER__ = Object.freeze({
    ThreeAvatarRenderer,
    MODES,
    morphAliases: MORPH_ALIASES,
    inferRigRole,
    speechGestureEnergy,
    perspectiveFitDistance,
  });
})();
