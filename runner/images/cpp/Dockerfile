FROM gcc:14-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 runner && useradd --uid 10001 --gid 10001 --no-create-home runner \
    && mkdir /job && chown 10001:10001 /job
USER 10001:10001
WORKDIR /job
CMD ["true"]
