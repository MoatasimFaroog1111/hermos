(function () {
  "use strict";

  const STATES = Object.freeze({
    IDLE: "idle",
    LISTENING: "listening",
    THINKING: "thinking",
    SPEAKING: "speaking",
    ERROR: "error",
  });

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function lerp(current, target, alpha) {
    return current + (target - current) * clamp(alpha, 0, 1);
  }

  class SeededNoise {
    constructor(seed = Math.random() * 1e9) {
      this.seed = seed % 2147483647;
      if (this.seed <= 0) this.seed += 2147483646;
    }

    next() {
      this.seed = this.seed * 16807 % 2147483647;
      return (this.seed - 1) / 2147483646;
    }

    signed() {
      return this.next() * 2 - 1;
    }

    range(min, max) {
      return min + (max - min) * this.next();
    }
  }

  class AttentionController {
    constructor(noise) {
      this.noise = noise;
      this.gazeYaw = 0;
      this.gazePitch = 0;
      this.targetYaw = 0;
      this.targetPitch = 0;
      this.nextShiftAt = 0;
      this.lastState = STATES.IDLE;
    }

    update(time, deltaTime, state, pointer) {
      const pointerWeight = pointer?.active ? 0.72 : 0;
      const directAttention = state === STATES.LISTENING || state === STATES.SPEAKING;
      const thinking = state === STATES.THINKING;

      if (time >= this.nextShiftAt || state !== this.lastState) {
        this.lastState = state;
        if (thinking) {
          this.targetYaw = this.noise.range(-0.24, 0.24);
          this.targetPitch = this.noise.range(-0.08, 0.14);
          this.nextShiftAt = time + this.noise.range(1.3, 2.8);
        } else if (directAttention) {
          const briefBreak = this.noise.next() < 0.18;
          this.targetYaw = briefBreak ? this.noise.range(-0.10, 0.10) : this.noise.range(-0.025, 0.025);
          this.targetPitch = briefBreak ? this.noise.range(-0.035, 0.035) : this.noise.range(-0.012, 0.012);
          this.nextShiftAt = time + this.noise.range(1.8, 4.1);
        } else {
          this.targetYaw = this.noise.range(-0.11, 0.11);
          this.targetPitch = this.noise.range(-0.045, 0.055);
          this.nextShiftAt = time + this.noise.range(2.4, 5.8);
        }
      }

      const responsiveness = 1 - Math.exp(-deltaTime * (directAttention ? 4.8 : 2.4));
      const targetYaw = lerp(this.targetYaw, pointer?.yaw || 0, pointerWeight);
      const targetPitch = lerp(this.targetPitch, pointer?.pitch || 0, pointerWeight);
      this.gazeYaw = lerp(this.gazeYaw, targetYaw, responsiveness);
      this.gazePitch = lerp(this.gazePitch, targetPitch, responsiveness);

      return {
        yaw: this.gazeYaw,
        pitch: this.gazePitch,
        eyeYaw: clamp(this.gazeYaw * 1.35, -0.28, 0.28),
        eyePitch: clamp(this.gazePitch * 1.15, -0.18, 0.18),
      };
    }
  }

  class BlinkController {
    constructor(noise) {
      this.noise = noise;
      this.value = 0;
      this.phase = "open";
      this.phaseStartedAt = 0;
      this.nextBlinkAt = 0.8 + noise.range(1.1, 3.5);
      this.pendingSecondBlink = false;
    }

    intervalFor(state) {
      if (state === STATES.THINKING) return this.noise.range(3.6, 7.2);
      if (state === STATES.LISTENING) return this.noise.range(2.1, 5.0);
      if (state === STATES.SPEAKING) return this.noise.range(2.5, 5.7);
      return this.noise.range(2.3, 6.2);
    }

    update(time, state) {
      if (this.phase === "open" && time >= this.nextBlinkAt) {
        this.phase = "closing";
        this.phaseStartedAt = time;
        this.pendingSecondBlink = this.noise.next() < 0.12;
      }

      const elapsed = time - this.phaseStartedAt;
      if (this.phase === "closing") {
        this.value = clamp(elapsed / 0.055, 0, 1);
        if (elapsed >= 0.055) {
          this.phase = "closed";
          this.phaseStartedAt = time;
        }
      } else if (this.phase === "closed") {
        this.value = 1;
        if (elapsed >= 0.045) {
          this.phase = "opening";
          this.phaseStartedAt = time;
        }
      } else if (this.phase === "opening") {
        this.value = 1 - clamp(elapsed / 0.085, 0, 1);
        if (elapsed >= 0.085) {
          this.value = 0;
          this.phase = "open";
          this.phaseStartedAt = time;
          if (this.pendingSecondBlink) {
            this.pendingSecondBlink = false;
            this.nextBlinkAt = time + this.noise.range(0.14, 0.24);
          } else {
            this.nextBlinkAt = time + this.intervalFor(state);
          }
        }
      }
      return this.value;
    }
  }

  class ExpressionController {
    constructor(noise) {
      this.noise = noise;
      this.smile = 0.10;
      this.brow = 0.05;
      this.squint = 0;
      this.nextMicroExpressionAt = 0;
      this.microSmile = 0;
      this.microBrow = 0;
    }

    update(time, deltaTime, state, speechEnergy) {
      if (time >= this.nextMicroExpressionAt) {
        this.microSmile = this.noise.range(-0.025, 0.055);
        this.microBrow = this.noise.range(-0.018, 0.05);
        this.nextMicroExpressionAt = time + this.noise.range(2.5, 6.5);
      }

      let targetSmile = 0.10;
      let targetBrow = 0.05;
      let targetSquint = 0;

      if (state === STATES.LISTENING) {
        targetSmile = 0.11;
        targetBrow = 0.16;
      } else if (state === STATES.THINKING) {
        targetSmile = 0.035;
        targetBrow = 0.09;
        targetSquint = 0.035;
      } else if (state === STATES.SPEAKING) {
        targetSmile = 0.17 + speechEnergy * 0.10;
        targetBrow = 0.07 + speechEnergy * 0.05;
      } else if (state === STATES.ERROR) {
        targetSmile = 0.01;
        targetBrow = 0.20;
      }

      targetSmile = clamp(targetSmile + this.microSmile, 0, 0.5);
      targetBrow = clamp(targetBrow + this.microBrow, 0, 0.45);
      const alpha = 1 - Math.exp(-deltaTime * 3.7);
      this.smile = lerp(this.smile, targetSmile, alpha);
      this.brow = lerp(this.brow, targetBrow, alpha);
      this.squint = lerp(this.squint, targetSquint, alpha);
      return { smile: this.smile, brow: this.brow, squint: this.squint };
    }
  }

  class BodyMotionController {
    constructor(noise) {
      this.noise = noise;
      this.weightShift = 0;
      this.targetWeightShift = 0;
      this.nextWeightShiftAt = 0;
      this.gestureSide = 1;
      this.nextGestureAt = 0;
      this.gesture = 0;
    }

    update(time, deltaTime, state, speechEnergy) {
      if (time >= this.nextWeightShiftAt) {
        this.targetWeightShift = this.noise.range(-0.018, 0.018);
        this.nextWeightShiftAt = time + this.noise.range(3.8, 8.4);
      }
      this.weightShift = lerp(
        this.weightShift,
        this.targetWeightShift,
        1 - Math.exp(-deltaTime * 0.75),
      );

      if (state === STATES.SPEAKING && time >= this.nextGestureAt && speechEnergy > 0.18) {
        this.gesture = this.noise.range(0.45, 1.0) * speechEnergy;
        this.gestureSide *= -1;
        this.nextGestureAt = time + this.noise.range(0.8, 2.2);
      } else {
        this.gesture *= Math.exp(-deltaTime * 4.2);
      }

      const listeningNod = state === STATES.LISTENING
        ? Math.max(0, Math.sin(time * 1.55 + 0.4)) * 0.012
        : 0;
      const breathPhase = time * 1.28 + Math.sin(time * 0.13) * 0.5;
      const breath = Math.sin(breathPhase) * 0.0075;
      const speechNod = state === STATES.SPEAKING
        ? Math.sin(time * 4.7) * 0.016 * speechEnergy
        : 0;

      return {
        breath,
        weightShift: this.weightShift,
        headNod: listeningNod + speechNod,
        torsoYaw: this.weightShift * 0.8,
        shoulderLift: Math.abs(breath) * 0.55,
        gesture: this.gesture,
        gestureSide: this.gestureSide,
      };
    }
  }

  class HumanBehaviorEngine {
    constructor(options = {}) {
      this.noise = new SeededNoise(options.seed);
      this.attention = new AttentionController(this.noise);
      this.blink = new BlinkController(this.noise);
      this.expression = new ExpressionController(this.noise);
      this.body = new BodyMotionController(this.noise);
      this.reducedMotion = Boolean(options.reducedMotion);
      this.state = STATES.IDLE;
      this.output = this.snapshot();
    }

    snapshot() {
      return {
        blink: 0,
        gazeYaw: 0,
        gazePitch: 0,
        eyeYaw: 0,
        eyePitch: 0,
        smile: 0.10,
        brow: 0.05,
        squint: 0,
        breath: 0,
        weightShift: 0,
        headNod: 0,
        torsoYaw: 0,
        shoulderLift: 0,
        gesture: 0,
        gestureSide: 1,
      };
    }

    update({ time = 0, deltaTime = 1 / 60, signals = {}, pointer = {} } = {}) {
      this.state = signals.state || STATES.IDLE;
      const motionScale = this.reducedMotion ? 0.30 : 1;
      const speechEnergy = this.state === STATES.SPEAKING
        ? clamp(
          0.16
          + (Number(signals.mouthOpen) || 0) * 0.45
          + (Number(signals.jaw) || 0) * 0.35
          + (Number(signals.mouthWide) || 0) * 0.10,
          0,
          1,
        )
        : 0;

      const attention = this.attention.update(time, deltaTime, this.state, pointer);
      const blink = this.blink.update(time, this.state);
      const expression = this.expression.update(time, deltaTime, this.state, speechEnergy);
      const body = this.body.update(time, deltaTime, this.state, speechEnergy);

      this.output = {
        blink,
        gazeYaw: attention.yaw * motionScale,
        gazePitch: attention.pitch * motionScale,
        eyeYaw: attention.eyeYaw * motionScale,
        eyePitch: attention.eyePitch * motionScale,
        smile: expression.smile,
        brow: expression.brow,
        squint: expression.squint,
        breath: body.breath * motionScale,
        weightShift: body.weightShift * motionScale,
        headNod: body.headNod * motionScale,
        torsoYaw: body.torsoYaw * motionScale,
        shoulderLift: body.shoulderLift * motionScale,
        gesture: body.gesture * motionScale,
        gestureSide: body.gestureSide,
      };
      return this.output;
    }
  }

  window.__HERMES_HUMAN_BEHAVIOR__ = Object.freeze({
    HumanBehaviorEngine,
    STATES,
  });
})();
