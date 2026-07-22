var exports = {};

exports.rubberband = function(overshoot, dimension, constant) {
  var c = constant != null ? constant : 0.55;
  return (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));
};

exports.project = function(velocity, decelerationRate) {
  var d = decelerationRate != null ? decelerationRate : 0.998;
  return (velocity / 1000) * d / (1 - d);
};

exports.VelocityTracker = function() {
  this.maxSamples = 5;
  this.points = [];
};

exports.VelocityTracker.prototype.addPoint = function(y, t) {
  this.points.push({ y: y, t: t });
  if (this.points.length > this.maxSamples) {
    this.points.shift();
  }
};

exports.VelocityTracker.prototype.reset = function(y, t) {
  this.points = [{ y: y, t: t }];
};

exports.VelocityTracker.prototype.velocity = function() {
  if (this.points.length < 2) {
    return 0;
  }
  var a = this.points[0];
  var b = this.points[this.points.length - 1];
  var dt = (b.t - a.t) / 1000;
  if (dt <= 0) {
    return 0;
  }
  return (b.y - a.y) / dt;
};

exports.spring = function(target, options) {
  var opts = options || {};
  var damping = opts.damping != null ? opts.damping : 1.0;
  var response = opts.response != null ? opts.response : 0.4;
  var initialVelocity = opts.initialVelocity || 0;
  var onUpdate = opts.onUpdate || null;
  var onComplete = opts.onComplete || null;
  var onStop = opts.onStop || null;

  var zeta = Math.max(damping, 0.01);
  var settleTime = Math.max(response, 0.05);
  var omegaN = 4.605 / (zeta * settleTime);
  var stiffness = omegaN * omegaN;
  var dampingC = 2 * zeta * omegaN;

  var value = target;
  var velocity = initialVelocity;
  var dest = target;
  var timer = null;
  var done = false;

  function tick() {
    if (done) {
      return;
    }
    var dt = 0.016;
    var disp = value - dest;
    var accel = -stiffness * disp - dampingC * velocity;
    velocity = velocity + accel * dt;
    value = value + velocity * dt;

    if (Math.abs(disp) < 0.05 && Math.abs(velocity) < 0.1) {
      value = dest;
      velocity = 0;
      done = true;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      if (onUpdate) {
        onUpdate(value);
      }
      if (onComplete) {
        onComplete();
      }
      return;
    }
    if (onUpdate) {
      onUpdate(value);
    }
  }

  timer = setInterval(tick, 16);
  tick();

  return {
    retarget: function(newTarget, newVelocity) {
      dest = newTarget;
      if (newVelocity != null) {
        velocity = newVelocity;
      }
      if (done) {
        done = false;
        timer = setInterval(tick, 16);
        tick();
      }
    },
    stop: function() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      if (!done && onStop) {
        done = true;
        onStop();
      }
      done = true;
    }
  };
};

module.exports = exports;
