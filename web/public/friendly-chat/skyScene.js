const PALETTE = [
  [168, 85, 247],
  [16, 185, 129],
  [244, 63, 94],
  [236, 72, 153],
  [56, 189, 248],
  [255, 255, 255],
];

/**
 * Decorative canvas renderer for the diamond-sky chat surface.
 *
 * This class owns visual animation only. It has no knowledge of sessions,
 * messages, network calls, or DOM actions outside its canvas.
 */
export class SkyScene {
  #canvas;
  #context;
  #diamonds = [];
  #sparkles = [];
  #frame = 0;
  #resizeObserver = null;
  #pointer = { x: 0, y: 0 };
  #targetPointer = { x: 0, y: 0 };
  #reducedMotion = false;
  #disposed = false;
  #startedAt = performance.now();

  constructor(canvas) {
    if (!(canvas instanceof HTMLCanvasElement)) {
      throw new TypeError("SkyScene requires a canvas element");
    }
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) throw new Error("Canvas 2D is unavailable");

    this.#canvas = canvas;
    this.#context = context;
    this.#reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  }

  start() {
    this.#resize();
    this.#seed();
    this.#resizeObserver = new ResizeObserver(() => {
      this.#resize();
      this.#seed();
    });
    this.#resizeObserver.observe(this.#canvas);
    this.#canvas.addEventListener("pointermove", this.#onPointerMove, { passive: true });
    this.#canvas.addEventListener("pointerleave", this.#onPointerLeave, { passive: true });
    this.#render(performance.now());
  }

  dispose() {
    this.#disposed = true;
    window.cancelAnimationFrame(this.#frame);
    this.#resizeObserver?.disconnect();
    this.#canvas.removeEventListener("pointermove", this.#onPointerMove);
    this.#canvas.removeEventListener("pointerleave", this.#onPointerLeave);
  }

  #onPointerMove = (event) => {
    const rect = this.#canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.#targetPointer.x = (event.clientX - rect.left) / rect.width - 0.5;
    this.#targetPointer.y = (event.clientY - rect.top) / rect.height - 0.5;
  };

  #onPointerLeave = () => {
    this.#targetPointer.x = 0;
    this.#targetPointer.y = 0;
  };

  #resize() {
    const rect = this.#canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));

    this.#canvas.width = Math.round(width * ratio);
    this.#canvas.height = Math.round(height * ratio);
    this.#context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.#canvas.dataset.width = String(width);
    this.#canvas.dataset.height = String(height);
  }

  #seed() {
    const width = Number(this.#canvas.dataset.width) || this.#canvas.clientWidth || 1;
    const height = Number(this.#canvas.dataset.height) || this.#canvas.clientHeight || 1;
    const density = this.#reducedMotion ? 22 : Math.min(110, Math.max(48, Math.round((width * height) / 11500)));
    const sparkleCount = this.#reducedMotion ? 34 : Math.min(170, Math.max(70, density * 2));

    this.#diamonds = Array.from({ length: density }, (_, index) => {
      const [r, g, b] = PALETTE[index % PALETTE.length];
      const depth = Math.random();
      return {
        x: Math.random() * width,
        y: Math.random() * height,
        baseX: Math.random() * width,
        baseY: Math.random() * height,
        size: 5 + depth * 20,
        depth,
        rotation: Math.random() * Math.PI,
        rotationSpeed: (Math.random() - 0.5) * 0.0014,
        floatSpeed: 0.35 + Math.random() * 0.85,
        phase: Math.random() * Math.PI * 2,
        color: { r, g, b },
        opacity: 0.2 + depth * 0.66,
      };
    });

    this.#sparkles = Array.from({ length: sparkleCount }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      radius: 0.45 + Math.random() * 1.65,
      phase: Math.random() * Math.PI * 2,
      speed: 0.7 + Math.random() * 1.8,
    }));
  }

  #render = (now) => {
    if (this.#disposed) return;
    const width = Number(this.#canvas.dataset.width) || this.#canvas.clientWidth || 1;
    const height = Number(this.#canvas.dataset.height) || this.#canvas.clientHeight || 1;
    const elapsed = (now - this.#startedAt) / 1000;

    this.#pointer.x += (this.#targetPointer.x - this.#pointer.x) * 0.045;
    this.#pointer.y += (this.#targetPointer.y - this.#pointer.y) * 0.045;

    this.#drawBackground(width, height);
    this.#drawClouds(width, height, elapsed);
    this.#drawSparkles(elapsed);
    this.#drawDiamonds(elapsed);

    if (!this.#reducedMotion) {
      this.#frame = window.requestAnimationFrame(this.#render);
    }
  };

  #drawBackground(width, height) {
    const gradient = this.#context.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#ffffff");
    gradient.addColorStop(0.42, "#f4fbff");
    gradient.addColorStop(1, "#dff4ff");
    this.#context.fillStyle = gradient;
    this.#context.fillRect(0, 0, width, height);

    const glow = this.#context.createRadialGradient(
      width * (0.55 + this.#pointer.x * 0.08),
      height * (0.28 + this.#pointer.y * 0.05),
      0,
      width * 0.52,
      height * 0.28,
      width * 0.7,
    );
    glow.addColorStop(0, "rgba(255,255,255,0.98)");
    glow.addColorStop(0.38, "rgba(186,230,253,0.32)");
    glow.addColorStop(1, "rgba(56,189,248,0)");
    this.#context.fillStyle = glow;
    this.#context.fillRect(0, 0, width, height);
  }

  #drawClouds(width, height, elapsed) {
    const clouds = [
      { x: 0.18, y: 0.2, radius: 0.28, drift: 0.006 },
      { x: 0.78, y: 0.34, radius: 0.32, drift: -0.004 },
      { x: 0.52, y: 0.68, radius: 0.36, drift: 0.003 },
    ];

    for (const cloud of clouds) {
      const centerX = width * (cloud.x + Math.sin(elapsed * cloud.drift + cloud.y) * 0.08);
      const centerY = height * cloud.y;
      const radius = Math.max(width, height) * cloud.radius;
      const fog = this.#context.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
      fog.addColorStop(0, "rgba(255,255,255,0.58)");
      fog.addColorStop(0.5, "rgba(255,255,255,0.18)");
      fog.addColorStop(1, "rgba(255,255,255,0)");
      this.#context.fillStyle = fog;
      this.#context.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);
    }
  }

  #drawSparkles(elapsed) {
    this.#context.save();
    this.#context.globalCompositeOperation = "screen";
    for (const sparkle of this.#sparkles) {
      const pulse = 0.25 + Math.max(0, Math.sin(elapsed * sparkle.speed + sparkle.phase)) * 0.75;
      this.#context.fillStyle = `rgba(255,255,255,${pulse})`;
      this.#context.beginPath();
      this.#context.arc(sparkle.x, sparkle.y, sparkle.radius * pulse, 0, Math.PI * 2);
      this.#context.fill();
    }
    this.#context.restore();
  }

  #drawDiamonds(elapsed) {
    this.#context.save();
    this.#context.globalCompositeOperation = "source-over";

    for (const diamond of this.#diamonds) {
      if (!this.#reducedMotion) diamond.rotation += diamond.rotationSpeed * 16;
      const floatX = Math.cos(elapsed * diamond.floatSpeed + diamond.phase) * (4 + diamond.depth * 8);
      const floatY = Math.sin(elapsed * diamond.floatSpeed + diamond.phase) * (7 + diamond.depth * 10);
      const parallaxX = this.#pointer.x * (12 + diamond.depth * 42);
      const parallaxY = this.#pointer.y * (8 + diamond.depth * 26);
      const x = diamond.baseX + floatX + parallaxX;
      const y = diamond.baseY + floatY + parallaxY;
      const size = diamond.size * (0.88 + Math.sin(elapsed * 0.9 + diamond.phase) * 0.08);

      this.#context.save();
      this.#context.translate(x, y);
      this.#context.rotate(diamond.rotation);
      this.#context.shadowBlur = 12 + diamond.depth * 22;
      this.#context.shadowColor = `rgba(${diamond.color.r},${diamond.color.g},${diamond.color.b},0.52)`;

      const fill = this.#context.createLinearGradient(-size, -size, size, size);
      fill.addColorStop(0, "rgba(255,255,255,0.96)");
      fill.addColorStop(0.38, `rgba(${diamond.color.r},${diamond.color.g},${diamond.color.b},${diamond.opacity})`);
      fill.addColorStop(1, "rgba(255,255,255,0.46)");

      this.#context.beginPath();
      this.#context.moveTo(0, -size);
      this.#context.lineTo(size * 0.78, 0);
      this.#context.lineTo(0, size);
      this.#context.lineTo(-size * 0.78, 0);
      this.#context.closePath();
      this.#context.fillStyle = fill;
      this.#context.fill();
      this.#context.strokeStyle = "rgba(255,255,255,0.92)";
      this.#context.lineWidth = Math.max(0.7, size * 0.045);
      this.#context.stroke();

      this.#context.shadowBlur = 0;
      this.#context.beginPath();
      this.#context.moveTo(0, -size);
      this.#context.lineTo(0, size);
      this.#context.moveTo(-size * 0.78, 0);
      this.#context.lineTo(size * 0.78, 0);
      this.#context.strokeStyle = "rgba(255,255,255,0.5)";
      this.#context.lineWidth = 0.75;
      this.#context.stroke();
      this.#context.restore();
    }

    this.#context.restore();
  }
}
