# docker build -t alas:latest -f deploy/docker/Dockerfile .
# docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm alas

FROM python:3.14-slim

WORKDIR /app/AzurLaneAutoScript

COPY requirements-linux.txt /tmp/requirements.txt

# Install system dependencies
RUN apt update \
    && apt install -y git adb libgomp1 openssh-client \
    && git config --global --add safe.directory '*' \
    && pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && rm -r ~/.cache/pip

CMD python gui.py
