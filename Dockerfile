ARG GROOVEDESK_RUNTIME_IMAGE=python:3.12-slim
FROM ${GROOVEDESK_RUNTIME_IMAGE}
USER root
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 GROOVEDESK_DATA=/var/lib/groovedesk
WORKDIR /opt/groovedesk
COPY requirements.txt scripts/check_dependencies.py ./
RUN (python check_dependencies.py || python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt) \
    && python check_dependencies.py && python -m pip check
COPY groovedesk ./groovedesk
COPY image_lab ./image_lab
COPY static ./static
COPY templates ./templates
RUN useradd -U -u 11541 groovedesk && install -d -o groovedesk -g groovedesk /var/lib/groovedesk
USER groovedesk
EXPOSE 8000
CMD ["python", "-m", "groovedesk"]
