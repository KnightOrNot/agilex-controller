/* Native WebGL display of calibrated depth-camera XYZ. No external assets. */
class PointCloudViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl', {antialias: true, alpha: false});
    if (!this.gl) throw Error('当前浏览器未启用 WebGL，无法显示点云。');
    const gl = this.gl;
    const shader = (type, source) => {
      const result = gl.createShader(type);
      gl.shaderSource(result, source); gl.compileShader(result);
      if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
        throw Error(gl.getShaderInfoLog(result));
      }
      return result;
    };
    this.program = gl.createProgram();
    gl.attachShader(this.program, shader(gl.VERTEX_SHADER, `
      attribute vec3 position;
      uniform vec3 center;
      uniform vec2 angles;
      uniform float distance, aspect, pointSize, depthMax;
      varying vec3 color;
      void main() {
        vec3 p = position - center;
        p.y = -p.y; p.z = -p.z;
        float x = cos(angles.x)*p.x - sin(angles.x)*p.z;
        float z = sin(angles.x)*p.x + cos(angles.x)*p.z;
        float y = cos(angles.y)*p.y - sin(angles.y)*z;
        z = sin(angles.y)*p.y + cos(angles.y)*z - distance;
        gl_Position = vec4(1.8*x/aspect, 1.8*y, -1.0002*z - 0.020002, -z);
        gl_PointSize = pointSize;
        float t = clamp(position.z/depthMax, 0.0, 1.0);
        color = clamp(vec3(1.5)-abs(4.0*t-vec3(3.0,2.0,1.0)), 0.0, 1.0);
      }`));
    gl.attachShader(this.program, shader(gl.FRAGMENT_SHADER, `
      precision mediump float;
      varying vec3 color;
      void main() {gl_FragColor = vec4(color, 1.0);}`));
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
      throw Error(gl.getProgramInfoLog(this.program));
    }
    this.buffer = gl.createBuffer();
    this.uniforms = Object.fromEntries(
      ['center', 'angles', 'distance', 'aspect', 'pointSize', 'depthMax']
        .map(name => [name, gl.getUniformLocation(this.program, name)]));
    this.count = 0; this.center = [0, 0, 1]; this.distance = 2;
    this.yaw = 0; this.pitch = 0; this.centered = false;
    let dragging = null;
    canvas.onpointerdown = event => {
      dragging = [event.clientX, event.clientY];
      canvas.setPointerCapture(event.pointerId);
    };
    canvas.onpointermove = event => {
      if (!dragging) return;
      this.yaw += (event.clientX - dragging[0])*0.008;
      this.pitch = Math.max(-1.5, Math.min(1.5,
        this.pitch + (event.clientY-dragging[1])*0.008));
      dragging = [event.clientX, event.clientY]; this.draw();
    };
    canvas.onpointerup = canvas.onpointercancel = () => {dragging = null;};
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      this.distance = Math.max(0.05, Math.min(50,
        this.distance*Math.exp(event.deltaY*0.001)));
      this.draw();
    }, {passive: false});
    canvas.ondblclick = () => {this.centered = false; this.resetView(); this.draw();};
    this.resizeObserver = new ResizeObserver(() => this.draw());
    this.resizeObserver.observe(canvas);
  }
  resetView() {
    if (!this.points?.length) return;
    const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < this.points.length; i++) {
      const axis = i%3;
      low[axis] = Math.min(low[axis], this.points[i]);
      high[axis] = Math.max(high[axis], this.points[i]);
    }
    this.center = low.map((value, i) => (value+high[i])/2);
    this.distance = Math.max(0.3, ...low.map((value, i) => (high[i]-value)*1.4));
    this.yaw = this.pitch = 0; this.centered = true;
  }
  setPoints(points, depthMax) {
    this.points = points; this.count = points.length/3; this.depthMax = depthMax;
    if (!this.centered) this.resetView();
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, points, gl.DYNAMIC_DRAW); this.draw();
  }
  draw() {
    const gl = this.gl, canvas = this.canvas;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(canvas.clientWidth*dpr));
    const height = Math.max(1, Math.round(canvas.clientHeight*dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    gl.clearColor(0.055, 0.075, 0.11, 1); gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const position = gl.getAttribLocation(this.program, 'position');
    gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 3, gl.FLOAT, false, 0, 0);
    gl.uniform3fv(this.uniforms.center, this.center);
    gl.uniform2f(this.uniforms.angles, this.yaw, this.pitch);
    gl.uniform1f(this.uniforms.distance, this.distance);
    gl.uniform1f(this.uniforms.aspect, width/height);
    gl.uniform1f(this.uniforms.pointSize, 2*dpr);
    gl.uniform1f(this.uniforms.depthMax, this.depthMax || 3);
    gl.drawArrays(gl.POINTS, 0, this.count);
  }
}
