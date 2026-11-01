from __future__ import annotations

import secrets
from typing import Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def generate_secret() -> str:
    """Generate a secure random token."""
    return secrets.token_hex(32)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ------------------------------------------------------------
    # Server
    # ------------------------------------------------------------
    backend_host: str = "0.0.0.0"
    backend_port: int = 8080
    environment: str = "development"  # development | staging | production (FORCED for demo)

    # ------------------------------------------------------------
    # Database
    # ------------------------------------------------------------
    database_url: str = "sqlite:///./data/app.db"

    # ------------------------------------------------------------
    # Authentication (JWT)
    # ------------------------------------------------------------
    # In production, MUST be set via env var JWT_SECRET
    jwt_secret: str = Field(default_factory=generate_secret)
    jwt_issuer: str = "sovereign-autonomy"
    jwt_audience: str = "sovereign-autonomy-ui"
    access_token_expire_minutes: int = 720
    jwt_algorithm: str = "HS256"
    auth_required: Optional[bool] = None  # Defaults to True in production, False elsewhere
    allow_dev_tokens: Optional[bool] = None  # Defaults to False in production, True elsewhere

    # ------------------------------------------------------------
    # Simulator Connection
    # ------------------------------------------------------------
    # IMPORTANT:
    # - If sim runs in same machine: http://127.0.0.1:8090
    # - If sim runs on separate Fly machine: set SIM_BASE_URL to a Fly internal address
    sim_base_url: str = "http://127.0.0.1:8090"

    # In production, SHOULD be set via env var SIM_TOKEN
    sim_token: str = Field(default_factory=generate_secret)

    # ------------------------------------------------------------
    # Execution authority (app/autonomy)
    # ------------------------------------------------------------
    # Shared with the simulator, which checks every move's permit with it.
    # Unset = no permits can be issued, so the robot cannot move (fails closed).
    permit_secret: str = ""
    permit_ttl_s: float = 5.0
    robot_id: str = "robot-1"
    authority_db_path: str = "data/authority.db"
    world_max_age_s: float = 2.0       # telemetry older than this cannot back a permit
    max_actions_per_run: int = 5000
    dispatch_watchdog_s: float = 30.0  # no loop heartbeat for this long blocks dispatch

    # Gazebo
    gazebo_master_uri: str = "http://localhost:11311"

    # Isaac Sim
    isaac_sim_host: str = "localhost"
    isaac_sim_port: int = 8211

    # ------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------
    # Comma-separated origins, e.g.:
    # "http://localhost:3000,https://sovereign-autonomy.example.com"
    cors_origins: str = "http://localhost:3000"

    # ------------------------------------------------------------
    # HTTP Security
    # ------------------------------------------------------------
    security_headers_enabled: bool = True
    rate_limit_enabled: Optional[bool] = None  # Defaults to True in production, False elsewhere
    rate_limit_requests_per_minute: int = 300
    api_docs_enabled: Optional[bool] = None  # Defaults to False in production, True elsewhere
    hsts_max_age_seconds: int = 31536000
    run_migrations_on_start: Optional[bool] = None  # Defaults to True in production, False elsewhere

    # ------------------------------------------------------------
    # Gemini Robotics 1.5 API
    # ------------------------------------------------------------
    gemini_api_key: Optional[str] = None
    gemini_project_id: Optional[str] = None
    gemini_model: str = "gemini-robotics-er-1.5-preview"
    gemini_timeout_s: float = 10.0
    gemini_enabled: bool = False

    # ------------------------------------------------------------
    # Meta Model API (preferred planner, perception and voice)
    # ------------------------------------------------------------
    # MODEL_API_KEY is the name Meta's own docs use. When set, Muse Spark plans
    # every mission (seeing the robot camera as well as the map), SAM 3.1 reads
    # the camera, and Muse Voice Transcribe turns a spoken "stop" into a kill switch.
    model_api_key: Optional[str] = None
    meta_base_url: str = "https://api.meta.ai/v1"
    muse_enabled: bool = True
    muse_reasoning_model: str = "muse-spark-1.3"       # mission planning and replanning
    muse_fast_model: str = "muse-spark-1.3"            # per-step proposals when Muse Spark Open is not set up
    muse_reasoning_effort: str = "high"
    muse_fast_effort: str = "low"
    muse_reasoning_timeout_s: float = 40.0
    muse_fast_timeout_s: float = 12.0
    muse_plan_with_camera: bool = True                 # attach the robot camera frame to mission planning
    sam_enabled: bool = True
    sam_model: str = "sam-3.1"
    sam_timeout_s: float = 15.0
    # What SAM is asked to find for each object type the gate cares about
    sam_concepts: str = "person=orange circle,forklift=yellow rectangle,spill=light blue blotch,pallet=brown square"
    voice_model: str = "muse-voice-transcribe-1.0"

    # Muse Spark Open (Meta open weights) served by Baseten, OpenAI-compatible.
    # When set, it proposes each step; Muse Spark keeps mission planning.
    baseten_api_key: Optional[str] = None
    baseten_base_url: str = "https://inference.baseten.co/v1"
    muse_open_model: str = "meta-models/muse-spark-open-1026"

    # ------------------------------------------------------------
    # NVIDIA Nemotron on Nebius Token Factory (OpenAI-compatible)
    # ------------------------------------------------------------
    # When configured, Nemotron replaces Gemini as the planner everywhere.
    # Tiered routing: fast models handle per-step proposals and analysis;
    # the reasoning model handles mission planning and replanning after a
    # governance denial. Model IDs are configurable because Token Factory's
    # catalogue changes — run scripts/check_token_factory.py to list yours.
    nebius_api_key: Optional[str] = None

    # Tavily: live site intelligence, always treated as untrusted input
    tavily_api_key: Optional[str] = None
    tavily_search_depth: str = "advanced"
    tavily_timeout_s: float = 12.0
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nemotron_enabled: bool = True
    nemotron_fast_models: str = "nvidia/Nemotron-3_5-Lightning,nvidia/nemotron-3-super-120b-a12b"
    nemotron_reasoning_model: str = "nvidia/Nemotron-3-Ultra-550b-a55b"
    nemotron_fast_timeout_s: float = 10.0  # fast models reason too; 2048-token cap
    nemotron_reasoning_timeout_s: float = 30.0  # Ultra may think ~8k tokens (~20 s)

    # Vision: an NVIDIA vision-language model reads the robot camera. Its output is
    # cross-checked against the simulator and can only add caution, never remove it.
    vision_enabled: bool = True
    vision_model: str = "nvidia/Nemotron-3.5-Super-VL"
    vision_interval_s: float = 5.0      # one check per run every N seconds
    vision_timeout_s: float = 15.0
    vision_match_m: float = 1.2         # a sighting within this distance of a real object counts as a match
    vision_caution_ttl_s: float = 8.0   # how long an unconfirmed sighting slows the robot

    @property
    def vision_configured(self) -> bool:
        return self.vision_enabled and (self.sam_configured or bool(self.nebius_api_key))

    @property
    def sam_configured(self) -> bool:
        return bool(self.model_api_key and self.sam_enabled)

    @property
    def vision_provider(self) -> str:
        return "sam" if self.sam_configured else "nemotron-vl"

    # Public demo guardrails (see app/demo_guard.py). Off by default.
    public_demo: bool = False
    demo_max_run_s: float = 240.0             # missions stop automatically after this
    demo_missions_per_hour: int = 20
    demo_model_calls_per_hour: int = 30       # direct /llm/* calls
    demo_vision_checks_per_hour: int = 60     # on-demand checks (run-loop checks are paced separately)
    demo_site_intel_per_hour: int = 20        # Tavily lookups and bulletins

    # ------------------------------------------------------------
    # LLM / Agent Configuration
    # ------------------------------------------------------------
    llm_enabled: bool = False
    llm_provider: str = "muse"  # muse | nemotron | gemini | agentic | mock (muse/nemotron/gemini all use the best configured model)
    # If true, starting a run will fail unless an LLM multi-waypoint plan is produced
    require_llm_plan_at_start: bool = True

    # ------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------
    otel_exporter_endpoint: Optional[str] = None
    otel_service_name: str = "sovereign-autonomy"
    sentry_dsn: Optional[str] = None

    # ------------------------------------------------------------
    # Notifications (Optional)
    # ------------------------------------------------------------
    slack_webhook_url: Optional[str] = None
    alert_email: Optional[str] = None

    # ------------------------------------------------------------
    # Governance Settings
    # ------------------------------------------------------------
    risk_threshold: float = 0.70
    audit_chain_enabled: bool = True
    human_safe_distance_m: float = 1.5
    max_speed_near_human: float = 0.3

    @property
    def cors_origins_list(self) -> List[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def require_auth(self) -> bool:
        if self.auth_required is not None:
            return self.auth_required
        return self.is_production

    @property
    def dev_tokens_enabled(self) -> bool:
        if self.allow_dev_tokens is not None:
            return self.allow_dev_tokens
        return not self.is_production

    @property
    def rate_limit_active(self) -> bool:
        if self.rate_limit_enabled is not None:
            return self.rate_limit_enabled
        return self.is_production

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production

    @property
    def migrate_on_start(self) -> bool:
        if self.run_migrations_on_start is not None:
            return self.run_migrations_on_start
        return self.is_production

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_enabled)

    @property
    def muse_configured(self) -> bool:
        return bool(self.model_api_key and self.muse_enabled)

    @property
    def muse_open_configured(self) -> bool:
        return bool(self.baseten_api_key)

    @property
    def voice_configured(self) -> bool:
        return bool(self.model_api_key)

    @property
    def sam_concept_map(self) -> Dict[str, str]:
        out = {}
        for part in self.sam_concepts.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and v.strip():
                    out[k.strip()] = v.strip()
        return out

    @property
    def nemotron_configured(self) -> bool:
        return bool(self.nebius_api_key and self.nemotron_enabled)

    @property
    def planner_configured(self) -> bool:
        """True when any LLM planner backend (Meta Muse preferred) is available."""
        return self.muse_configured or self.muse_open_configured or self.nemotron_configured or self.gemini_configured

    @property
    def planner_provider(self) -> str:
        if self.muse_configured or self.muse_open_configured:
            return "muse"
        if self.nemotron_configured:
            return "nemotron"
        if self.gemini_configured:
            return "gemini"
        return "fallback"

    @property
    def nemotron_fast_models_list(self) -> List[str]:
        return [m.strip() for m in self.nemotron_fast_models.split(",") if m.strip()]

    def validate_runtime(self) -> None:
        """Fail fast on missing critical config in production."""
        import os
        if self.is_production:
            missing = []
            # Require explicitly-set secrets in production (not auto-generated)
            if not os.environ.get("JWT_SECRET"):
                missing.append("JWT_SECRET")
            if not os.environ.get("SIM_TOKEN"):
                missing.append("SIM_TOKEN")
            if len(self.permit_secret) < 32:
                missing.append("PERMIT_SECRET (32+ characters)")
            if missing:
                raise RuntimeError(
                    f"Missing required environment variables in production: {', '.join(missing)}"
                )



settings = Settings()
print(f"[DEBUG] Sovereign Autonomy ENVIRONMENT: {settings.environment}")
settings.validate_runtime()
