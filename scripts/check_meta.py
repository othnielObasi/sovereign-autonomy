"""Live check of the Meta models this project uses. Needs real keys.

    cd backend && python ../scripts/check_meta.py            # uses backend/.env
    python ../scripts/check_meta.py --frame path/to/frame.png  # SAM on a saved camera frame

Calls Muse Spark (with and without an image), Muse Spark Open on Baseten, and
SAM 3.1, and prints latency and a short sample of each answer. Never prints keys.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import settings  # noqa: E402
from app.services import meta_models  # noqa: E402


async def main(frame_path: str | None) -> int:
    ok = bool(settings.model_api_key)
    print(f"Meta Model API key: {'set' if settings.model_api_key else 'MISSING (MODEL_API_KEY)'}")
    print(f"Baseten key:        {'set' if settings.baseten_api_key else 'missing (BASETEN_API_KEY), optional'}")

    png = None
    if frame_path:
        png = open(frame_path, "rb").read()
    else:
        try:
            from app.services.sim_adapter import SimAdapter
            sim = SimAdapter()
            png = await sim.get_frame(size=512)
            await sim.close()
            print("Camera frame: from the running simulator")
        except Exception as exc:
            print(f"Camera frame: none ({type(exc).__name__}); start the simulator or pass --frame")

    if settings.model_api_key:
        t = time.monotonic()
        text = await meta_models.chat(settings.muse_reasoning_model, "Answer in JSON only.",
                                      'Return {"ok": true, "model": "<your name>"}', reasoning_effort="low",
                                      timeout_s=30)
        print(f"\nMuse Spark ({settings.muse_reasoning_model}): {round((time.monotonic() - t) * 1000)} ms -> {(text or 'NO ANSWER')[:120]}")
        ok &= bool(text)
        if png:
            t = time.monotonic()
            text = await meta_models.chat(settings.muse_reasoning_model, "Be brief.",
                                          "What do you see in this top-down warehouse camera image?",
                                          image_png=png, reasoning_effort="low", timeout_s=40)
            print(f"Muse Spark + image: {round((time.monotonic() - t) * 1000)} ms -> {(text or 'NO ANSWER')[:160]}")
            ok &= bool(text)
            for kind, concept in settings.sam_concept_map.items():
                boxes, call = await meta_models.sam_segment(png, concept)
                print(f"SAM 3.1 '{concept}' ({kind}): {call.get('latency_ms')} ms -> "
                      f"{'ERROR ' + str(call.get('status') or call.get('error')) if boxes is None else f'{len(boxes)} box(es) {boxes[:2]}'}")
                ok &= boxes is not None

    if settings.baseten_api_key:
        t = time.monotonic()
        text = await meta_models.chat(settings.muse_open_model, "Answer in JSON only.", 'Return {"ok": true}', timeout_s=30)
        print(f"\nMuse Spark Open ({settings.muse_open_model}): {round((time.monotonic() - t) * 1000)} ms -> {(text or 'NO ANSWER')[:120]}")
        ok &= bool(text)

    print("\nRESULT:", "all calls answered" if ok else "some calls failed (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame")
    sys.exit(asyncio.run(main(ap.parse_args().frame)))
