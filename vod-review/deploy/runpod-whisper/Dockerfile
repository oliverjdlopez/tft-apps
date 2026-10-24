FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04@sha256:fa44193567d1908f7ca1f3abf8623ce9c63bc8cba7bcfdb32702eb04d326f7a8

# Dependencies only: Runpod stages the selected Hugging Face repository on the
# host before starting a worker. No model acquisition occurs during this build.
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /worker/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /worker/requirements.txt
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
WORKDIR /worker
COPY cached_model.py handler.py /worker/
COPY mounted_audio.py /worker/mounted_audio.py

CMD ["python3", "-u", "/worker/handler.py"]
