"""Recent evidence windows and collision-safe cleanroom transfers."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes_runs import list_events
from app.db.models import Event
from app.db.session import Base
from app.policies.site_map import _racks_from_world, path_blocked
from app.services.site_router import route_plan
from bench.world import Layout, load_layout
from fastapi.testclient import TestClient
import pytest
from app.main import app


def test_recent_event_window_preserves_display_order_and_legacy_pagination():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i in range(6):
            db.add(Event(id=f'event-{i}', run_id='mission-control-test',
                         ts=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i),
                         type='PLAN', payload_json='{}', hash='0' * 64))
        db.commit()
        def ids(latest=False, offset=0):
            return [r.id for r in list_events('mission-control-test', limit=2,
                                             offset=offset, latest=latest, db=db)]
        assert ids() == ['event-0', 'event-1']
        assert ids(offset=2) == ['event-2', 'event-3']
        assert ids(latest=True) == ['event-4', 'event-5']
        assert ids(latest=True, offset=2) == ['event-2', 'event-3']
    engine.dispose()


def test_cleanroom_destinations_reachable_without_crossing_partitions_or_benches():
    site = load_layout(site='pharma')
    layout = Layout(site)
    racks = _racks_from_world(site)
    assert len(site['bays']) == 6
    assert {p['bay'] for p in site['presets']} <= {b['id'] for b in site['bays']}
    for start in site['parking'].values():
        for bay in site['bays']:
            assert layout.route(tuple(start), (bay['x'], bay['y'])), (start, bay['id'])
            previous = dict(x=start[0], y=start[1])
            if previous == {'x': bay['x'], 'y': bay['y']}:
                continue  # Already at the destination: no transfer is necessary.
            route = route_plan(site, previous, bay, site['zone_speed_limits'])
            assert route, (start, bay['id'])
            assert abs(route[-1]['x'] - bay['x']) < .1
            assert abs(route[-1]['y'] - bay['y']) < .1
            for point in route:
                assert path_blocked(previous['x'], previous['y'], point['x'], point['y'], racks) is None
                previous = point


@pytest.mark.parametrize('site_name', ['warehouse', 'factory', 'pharma'])
def test_world_proxy_preserves_facility_identity_and_room_geometry(monkeypatch, site_name):
    from app.api import routes_sim
    site = load_layout(site=site_name)
    async def world():
        return dict(site, site={'name': site_name, 'title': site.get('title', site_name)},
                    hotspots=[{'x': x, 'y': y} for x, y in site.get('hotspots', [])])
    monkeypatch.setattr(routes_sim.sim, 'get_world', world)
    response = TestClient(app).get('/sim/world')
    assert response.status_code == 200
    payload = response.json()
    assert payload['site']['title'] == site.get('title', site_name)
    assert payload['features'] == site.get('features', [])
    assert payload['racks'] == site['racks']


def test_cleanroom_placement_keeps_workstations_in_rooms_and_destinations_clear():
    site = load_layout(site='pharma')
    rooms = [f for f in site['features'] if f['type'] == 'room']
    benches = [r for r in site['racks'] if r['kind'] == 'bench']
    boundaries = site['geofence']
    counts = {room['id']: 0 for room in rooms}
    for bench in benches:
        containing = [room for room in rooms if
                      room['x']-room['width']/2 <= bench['x1'] < bench['x2'] <= room['x']+room['width']/2 and
                      room['y']-room['depth']/2 <= bench['y'] < bench['y']+bench['depth'] <= room['y']+room['depth']/2]
        assert len(containing) == 1, bench['id']
        counts[containing[0]['id']] += 1
    assert set(counts.values()) == {2}
    for room in rooms:
        assert boundaries['min_x'] <= room['x']-room['width']/2 < room['x']+room['width']/2 <= boundaries['max_x']
        assert boundaries['min_y'] <= room['y']-room['depth']/2 < room['y']+room['depth']/2 <= boundaries['max_y']
    for bay in site['bays']:
        assert path_blocked(bay['x'], bay['y'], bay['x']+.01, bay['y'], _racks_from_world(site)) is None
