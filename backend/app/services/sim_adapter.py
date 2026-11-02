from __future__ import annotations

import httpx
from typing import Any, Dict, Optional
from app.config import settings


class SimAdapter:
    """Minimal HTTP adapter for the mock simulator.

    The simulator exposes:
      - GET  /telemetry  -> current telemetry JSON
      - POST /command    -> execute a command
      - GET  /world      -> static world definition
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.sim_base_url).rstrip("/")
        self._headers: Dict[str, str] = {}
        if getattr(settings, "sim_token", ""):
            self._headers["X-Sim-Token"] = settings.sim_token
        # Shared client with explicit pool limits to prevent saturation
        self._client = httpx.AsyncClient(
            timeout=5.0,
            headers=self._headers,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )



    async def get_world(self) -> Dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/world")
        r.raise_for_status()
        world = r.json()
        from app.policies import site_map
        site_map.use_world(world)          # the gate always checks paths against this site
        return world

    async def get_telemetry(self, robot_id: Optional[str] = None) -> Dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/telemetry", params={"robot_id": robot_id} if robot_id else None)
        r.raise_for_status()
        return r.json()

    async def send_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Send a command. A move the simulator refuses (missing, invalid or reused
        permit; e-stop engaged) comes back as {"ok": False, "rejected": True, ...}:
        a definite "not executed", not an unknown outcome."""
        r = await self._client.post(f"{self.base_url}/command", json=command)
        if r.status_code in (403, 423):
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text
            return {"ok": False, "rejected": True, "reason": detail, "status": r.status_code}
        r.raise_for_status()
        return r.json()

    async def estop(self, *, engaged: bool, reason: str = "", release_token: str = "",
                    robot_id: Optional[str] = None) -> Dict[str, Any]:
        """Engage (anyone may stop a robot) or release (needs a signed release token).
        robot_id=None means every robot."""
        r = await self._client.post(f"{self.base_url}/estop",
                                    json={"engaged": engaged, "reason": reason, "release_token": release_token,
                                          "robot_id": robot_id})
        r.raise_for_status()
        return r.json()

    async def reset_robot(self, robot_id: Optional[str] = None) -> Dict[str, Any]:
        """Reset a robot to its parking spot in the simulator."""
        r = await self._client.post(f"{self.base_url}/reset", params={"robot_id": robot_id} if robot_id else None)
        r.raise_for_status()
        return r.json()

    async def post_scenario(self, scenario: str) -> Dict[str, Any]:
        """Inject a deterministic scenario into the simulator."""
        r = await self._client.post(
            f"{self.base_url}/scenario", json={"scenario": scenario}
        )
        r.raise_for_status()
        return r.json()

    async def get_frame(self, size: int = 512, robot_id: Optional[str] = None) -> bytes:
        """Robot camera frame (PNG). Only the warehouse simulator provides it."""
        params: Dict[str, Any] = {"size": size}
        if robot_id:
            params["robot_id"] = robot_id
        r = await self._client.get(f"{self.base_url}/frame", params=params)
        r.raise_for_status()
        return r.content

    async def load_seed(self, seed: int, mode: str = "benchmark") -> Dict[str, Any]:
        """Load a benchmark scenario (or another live site) by seed. Warehouse simulator only."""
        r = await self._client.post(f"{self.base_url}/seed", json={"seed": seed, "mode": mode})
        r.raise_for_status()
        return r.json()

    async def get_fleet(self) -> Dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/fleet")
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._client.aclose()
