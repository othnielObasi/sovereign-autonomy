"""Robot camera: a heading-up, top-down view of the area around the robot.

What the vision model sees. Deliberately plain, with no text or labels, so the
model has to recognise hazards from shape and colour the way it would in a
real overhead or fisheye view: racks dark, people orange, the forklift yellow,
spills light cyan (kept well apart from the robot's dark blue, which the vision
model otherwise confuses them with), pallets brown. The robot sits low in the
frame facing up, so most of the view is what lies ahead.
"""
from __future__ import annotations

import io
import math
from typing import Iterable, Tuple

from PIL import Image, ImageDraw

FLOOR = (214, 211, 203)
LANE = (196, 192, 182)
RACK = (74, 62, 52)
PERSON = (240, 120, 30)
PERSON_HEAD = (120, 55, 10)
FORKLIFT = (235, 190, 20)
SPILL = (110, 210, 235)
PALLET = (150, 95, 45)
OTHER = (110, 110, 120)
ROBOT = (25, 90, 200)
OUTSIDE = (40, 40, 40)

KIND_COLOUR = {"spill": SPILL, "pallet": PALLET, "dropped_pallet": PALLET, "handcart": (100, 90, 170),
               "tote_stack": (60, 130, 140)}


def render(world, size: int = 512, view_m: float = 12.0) -> bytes:
    r = world.robot
    scale = size / view_m
    ox, oy = size / 2, size * 0.72          # robot position in the image
    rot = math.pi / 2 - r.theta             # rotate so the heading points up

    def to_px(x: float, y: float) -> Tuple[float, float]:
        dx, dy = x - r.x, y - r.y
        rx = dx * math.cos(rot) - dy * math.sin(rot)
        ry = dx * math.sin(rot) + dy * math.cos(rot)
        return ox + rx * scale, oy - ry * scale

    img = Image.new("RGB", (size, size), OUTSIDE)
    d = ImageDraw.Draw(img)
    g = world.layout.geofence
    d.polygon([to_px(g["min_x"], g["min_y"]), to_px(g["max_x"], g["min_y"]),
               to_px(g["max_x"], g["max_y"]), to_px(g["min_x"], g["max_y"])], fill=FLOOR)
    # main corridor floor marking
    d.polygon([to_px(g["min_x"], 12.0), to_px(g["max_x"], 12.0), to_px(g["max_x"], 15.0), to_px(g["min_x"], 15.0)],
              fill=LANE)

    for rack in world.layout.racks:
        d.polygon([to_px(rack.x1, rack.y1), to_px(rack.x2, rack.y1), to_px(rack.x2, rack.y2), to_px(rack.x1, rack.y2)],
                  fill=RACK)

    def blob(x, y, rad, colour):
        cx, cy = to_px(x, y)
        rr = max(2.0, rad * scale)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=colour)

    def box(x, y, half_w, half_h, heading, colour):
        c, s = math.cos(heading), math.sin(heading)
        pts = [(x + c * ax - s * ay, y + s * ax + c * ay)
               for ax, ay in ((-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h))]
        d.polygon([to_px(*p) for p in pts], fill=colour)

    for c in list(world.layout.static) + list(world.active_spawns):
        colour = KIND_COLOUR.get(c.kind, OTHER)
        if c.kind == "spill":
            blob(c.x, c.y, c.r, colour)
            blob(c.x + c.r * 0.5, c.y - c.r * 0.3, c.r * 0.6, colour)
        else:
            box(c.x, c.y, c.r * 0.9, c.r * 0.9, 0.0, colour)

    for v in world.vehicles():
        heading = 0.0
        if v.idx + 1 < len(v.route):
            tx, ty = v.route[v.idx + 1]
            heading = math.atan2(ty - v.pos[1], tx - v.pos[0])
        box(v.pos[0], v.pos[1], v.radius, v.radius * 0.6, heading, FORKLIFT)
        fx, fy = v.pos[0] + math.cos(heading) * v.radius * 1.3, v.pos[1] + math.sin(heading) * v.radius * 1.3
        box(fx, fy, 0.35, 0.45, heading, (120, 120, 120))   # forks

    for p in world.people():
        blob(p.pos[0], p.pos[1], 0.3, PERSON)
        blob(p.pos[0], p.pos[1], 0.13, PERSON_HEAD)

    # the robot, facing up
    tri = [(ox, oy - 0.55 * scale), (ox - 0.4 * scale, oy + 0.4 * scale), (ox + 0.4 * scale, oy + 0.4 * scale)]
    d.polygon(tri, fill=ROBOT)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def visible_hazards(world, view_m: float = 12.0) -> Iterable[dict]:
    """Ground truth for what is inside the frame, used to score the vision model."""
    r = world.robot
    half = view_m / 2
    for p in world.people():
        d = math.hypot(p.pos[0] - r.x, p.pos[1] - r.y)
        if d < half * 1.2:
            yield {"type": "person", "distance_m": round(d, 2)}
    for v in world.vehicles():
        d = math.hypot(v.pos[0] - r.x, v.pos[1] - r.y) - v.radius
        if d < half * 1.2:
            yield {"type": "forklift", "distance_m": round(max(0.0, d), 2)}
    for c in world.active_spawns:
        d = c.distance(r.x, r.y)
        if d < half * 1.2:
            yield {"type": c.kind, "distance_m": round(d, 2)}
