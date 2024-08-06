FROM alpine:latest AS base

WORKDIR /app

FROM base AS scheduler

COPY bin/scheduler scheduler

ENTRYPOINT ["/bin/sh","-c"]