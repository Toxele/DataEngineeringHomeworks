FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY hw-5/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hw-3/lab/__init__.py hw-3/lab/domain.py ./lab/
COPY hw-5/batch ./batch/
ENTRYPOINT ["python", "-m", "batch"]
