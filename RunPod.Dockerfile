FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# RunPod 및 임베딩 필수 라이브러리 설치
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir runpod sentence-transformers transformers accelerate

# 빌드 시점에 모델 미리 다운로드 (Cold Start 방지)
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large-instruct')"

# 핸들러 코드 복사 및 실행
COPY handler.py /app/handler.py
CMD ["python3", "-u", "/app/handler.py"]
