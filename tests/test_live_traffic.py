"""Physical live-site traffic regressions, independent of backend API fixtures.

Run: .venv/Scripts/python.exe -m unittest discover -s tests -p test_live_traffic.py -v
"""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sim/warehouse_sim"), str(ROOT / "backend")]
from bench.world import Circle, Layout, RobotState, Walker, World
from traffic import ActorNavigation, TrafficWorld


def room(features=None, racks=None, width=40, height=25):
    return {"geofence": {"min_x": 0, "max_x": width, "min_y": 0, "max_y": height},
            "zones": [], "bays": [], "features": features or [], "racks": racks or [], "obstacles": []}


class LiveTrafficTests(unittest.TestCase):
    def assert_separated(self, actors):
        for i, actor in enumerate(actors):
            for other in actors[i + 1:]:
                self.assertGreaterEqual(math.dist(actor.pos, other.pos), actor.radius + other.radius - 1e-6,
                                        (actor.name, actor.pos, other.name, other.pos))

    def test_route_goes_around_rendered_table_and_charger(self):
        data = room(features=[{"type": "packing_station", "x": 5, "y": 6},
                              {"type": "charging_station", "x": 9, "y": 6}])
        original = copy.deepcopy(data)
        nav = ActorNavigation(data)
        self.assertFalse(nav.walkable((5, 6.55)))
        self.assertFalse(nav.walkable((9, 6.75)))
        path = nav.route((2, 6.5), (12, 6.5))
        self.assertTrue(path)
        self.assertTrue(all(nav.segment_clear(a, b) for a, b in zip(path, path[1:])))
        self.assertGreater(sum(math.dist(a, b) for a, b in zip(path, path[1:])), 10)
        self.assertEqual(data, original, "navigation must not turn furniture into rendered storage racks")

    def test_no_straight_line_fallback_through_a_sealed_wall(self):
        nav = ActorNavigation(room(racks=[{"x1": 5, "x2": 7, "y": 0, "depth": 12}], width=12, height=12))
        self.assertIsNone(nav.route((2, 5), (10, 5)))

    def test_worker_yields_before_forklift_lane_then_resumes(self):
        worker = Walker("Worker", [(10, 10), (10, 17)], 1)
        truck = Walker("Forklift", [(2, 13.5), (30, 13.5)], 2, radius=1, kind="forklift")
        world = TrafficWorld(Layout(room()), RobotState(35, 23), [worker, truck])
        states = set()
        for _ in range(180):
            world.step(0.1)
            states.add(worker.activity)
            self.assert_separated([worker, truck])
        self.assertIn("waiting_for_forklift", states)
        self.assertGreater(worker.pos[1], 16)
        self.assertGreater(truck.pos[0], 20)

    def test_driver_waits_for_worker_already_crossing(self):
        worker = Walker("Worker", [(10, 13), (10, 17)], 1)
        truck = Walker("Forklift", [(7, 13.5), (30, 13.5)], 2, radius=1, kind="forklift")
        world = TrafficWorld(Layout(room()), RobotState(35, 23), [worker, truck])
        states = set()
        for _ in range(100):
            world.step(0.1)
            states.add(truck.activity)
            self.assert_separated([worker, truck])
        self.assertIn("waiting_for_person", states)
        self.assertGreater(worker.pos[1], 16)
        self.assertGreater(truck.pos[0], 12)

    def test_people_pass_each_other_without_body_overlap(self):
        a = Walker("A", [(2, 6), (8, 6)], 0.8)
        b = Walker("B", [(8, 6), (2, 6)], 0.8)
        world = TrafficWorld(Layout(room(width=12, height=12)), RobotState(11, 11), [a, b])
        for _ in range(300):
            world.step(0.1)
            self.assert_separated([a, b])
        self.assertGreater(a.pos[0], 7)
        self.assertLess(b.pos[0], 3)

    def test_new_obstacle_does_not_get_walked_through(self):
        worker = Walker("Worker", [(2, 6), (12, 6)], 1)
        world = TrafficWorld(Layout(room()), RobotState(35, 23), [worker])
        world.step(0.1)
        obstacle = Circle(6, 6, 0.6, "dropped_pallet")
        world.active_spawns.append(obstacle)
        for _ in range(220):
            world.step(0.1)
            self.assertGreaterEqual(obstacle.distance(*worker.pos), worker.radius)
        self.assertGreater(worker.pos[0], 11)

    def test_live_site_uses_safe_routes_and_has_work_stops(self):
        from server import build_live_world
        for seed in (7, 42, 101):
            world = build_live_world(seed)
            self.assertGreaterEqual(len(world.walkers), 4)
            work = set()
            for _ in range(900):
                world.step(0.1)
                present = world.people() + world.vehicles()
                self.assert_separated(present)
                for actor in present:
                    nav = world.pedestrian_nav if actor.kind == "person" else world.vehicle_nav
                    self.assertTrue(nav.walkable(actor.pos), (seed, actor.name, actor.pos))
                    if actor.kind == "person" and actor.activity == "working":
                        work.add(actor.name)
            self.assertTrue(work, f"seed {seed}: workers never reached a work destination")

    def test_benchmark_world_keeps_its_original_actor_motion(self):
        actor = Walker("benchmark", [(2, 6), (12, 6)], 1)
        world = World(Layout(room()), RobotState(35, 23), [actor])
        world.step(0.5)
        self.assertEqual(actor.pos, (2.5, 6.0))
        self.assertFalse(hasattr(actor, "activity"))


if __name__ == "__main__":
    unittest.main()
