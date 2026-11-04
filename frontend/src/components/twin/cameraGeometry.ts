/** Presentation-only camera clearance. Never changes navigation or collision policy. */
export type CameraPoint = { x: number; y: number; z: number };
export type CameraBox = { min: CameraPoint; max: CameraPoint };
type Fence = { min_x: number; max_x: number; min_y: number; max_y: number };

export function cameraObstacles(world: { racks?: any[] }): CameraBox[] {
  return (world.racks || []).map(rack => {
    const top = rack.kind === 'partition' ? 3.35 : rack.kind === 'bench' ? 2.5 : 6;
    return { min: { x: rack.x1 - .18, y: 0, z: -rack.y - (rack.depth || 1) - .18 },
      max: { x: rack.x2 + .18, y: top + .12, z: -rack.y + .18 } };
  });
}

export function segmentEntry(start: CameraPoint, end: CameraPoint, box: CameraBox): number | null {
  let near = 0, far = 1;
  for (const axis of ['x', 'y', 'z'] as const) {
    const delta = end[axis] - start[axis];
    if (Math.abs(delta) < 1e-9) {
      if (start[axis] < box.min[axis] || start[axis] > box.max[axis]) return null;
      continue;
    }
    const a = (box.min[axis] - start[axis]) / delta, b = (box.max[axis] - start[axis]) / delta;
    near = Math.max(near, Math.min(a, b)); far = Math.min(far, Math.max(a, b));
    if (near > far) return null;
  }
  return far < 0 || near > 1 ? null : Math.max(0, near);
}

export function clearFollowCamera(anchor: CameraPoint, desired: CameraPoint, boxes: CameraBox[], fence: Fence): CameraPoint {
  const end = { x: Math.max(fence.min_x + .2, Math.min(fence.max_x - .2, desired.x)),
    y: desired.y, z: Math.max(-fence.max_y + .2, Math.min(-fence.min_y - .2, desired.z)) };
  let fraction = 1;
  const distance = Math.hypot(end.x-anchor.x, end.y-anchor.y, end.z-anchor.z);
  for (const box of boxes) {
    const hit = segmentEntry(anchor, end, box);
    if (hit !== null) fraction = Math.min(fraction, Math.max(0, hit - .12 / Math.max(.01, distance)));
  }
  return { x: anchor.x + (end.x-anchor.x)*fraction,
    y: anchor.y + (end.y-anchor.y)*fraction, z: anchor.z + (end.z-anchor.z)*fraction };
}
