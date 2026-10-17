import { test } from 'node:test';
import assert from 'node:assert/strict';
import { INITIAL_CAMERA, project, topicPosition, zoomCamera, brainFaces, folds, fiber } from '../visualization/brain.ts';

test('brain geometry is three-dimensional with two hemispheres', () => {
  const vertices = brainFaces.flatMap(f => f.vertices);
  assert.ok(vertices.some(p => p.x < -.9));
  assert.ok(vertices.some(p => p.x > .9));
  assert.ok(vertices.some(p => p.z > 1));
  assert.ok(vertices.some(p => p.z < -1));
  assert.ok(folds.flat().some(p => p.y < -1));
});
test('perspective rotation and pan affect projected coordinates', () => {
  const p = { x: 1, y: .2, z: .4 };
  const a = project(p, INITIAL_CAMERA, 800, 450);
  const b = project(p, { ...INITIAL_CAMERA, yaw: 1 }, 800, 450);
  assert.notEqual(a.x, b.x);
  const shifted = project(p, { ...INITIAL_CAMERA, panX: 25, panY: -10 }, 800, 450);
  assert.equal(shifted.x, a.x+25); assert.equal(shifted.y, a.y-10);
});
test('topic anchors ignore frequency and fibers retain endpoints', () => {
  const n = { id: 'piano', x: .8, y: .7 };
  const a = topicPosition(n), b = topicPosition({ ...n });
  assert.deepEqual(a, b);
  const path = fiber(a, { x: -.5, y: .3, z: .1 });
  assert.deepEqual(path[0], a);
  assert.ok(Math.abs(path.at(-1)!.x+.5) < 1e-10);
});
test('zoom is bounded and preserves orientation', () => {
  assert.equal(zoomCamera(INITIAL_CAMERA, 100).zoom, 3.5);
  assert.equal(zoomCamera(INITIAL_CAMERA, .001).zoom, .55);
  assert.equal(zoomCamera(INITIAL_CAMERA, 2).yaw, INITIAL_CAMERA.yaw);
});
