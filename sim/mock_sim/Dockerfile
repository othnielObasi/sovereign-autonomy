FROM python:3.11-slim
WORKDIR /app

RUN groupadd -r sim && useradd -r -g sim -d /app -s /sbin/nologin sim

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server.py /app/server.py
COPY world.json /app/world.json

USER sim
EXPOSE 8090

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090"]
