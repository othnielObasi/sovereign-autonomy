# Build from the repository root:  docker build -f sim/warehouse_sim/Dockerfile .
FROM python:3.11-slim
WORKDIR /app

RUN groupadd -r sim && useradd -r -g sim -d /app -s /sbin/nologin sim

COPY sim/warehouse_sim/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# The engine is shared with the safety benchmark
COPY backend/bench/__init__.py backend/bench/world.py backend/bench/scenarios.py backend/bench/layout.json /app/bench/
COPY sim/warehouse_sim/server.py sim/warehouse_sim/camera.py sim/warehouse_sim/traffic.py /app/

USER sim
EXPOSE 8090
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090"]
