FROM python:3.12-slim-bookworm
RUN groupadd --gid 10001 runner && useradd --uid 10001 --gid 10001 --no-create-home runner \
    && mkdir /job && chown 10001:10001 /job
USER 10001:10001
WORKDIR /job
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["true"]
