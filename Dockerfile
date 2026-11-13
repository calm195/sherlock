# 发布说明：
  # 1. 更新 VERSION_TAG，使其与 pyproject.toml 中的版本号一致。
  # 2. 更新 VCS_REF，使其与该发布版本对应的完整提交哈希一致。
  # 3. 构建镜像时同时指定 latest 标签和版本标签。
    # 例如：`docker build -t sherlock/sherlock:0.16.0 -t sherlock/sherlock:latest .`

FROM python:3.12-slim-bullseye AS build
WORKDIR /sherlock

RUN pip3 install --no-cache-dir --upgrade pip

FROM python:3.12-slim-bullseye
WORKDIR /sherlock

ARG VCS_REF= # CHANGE ME ON UPDATE
ARG VCS_URL="https://github.com/sherlock-project/sherlock"
ARG VERSION_TAG= # CHANGE ME ON UPDATE

ENV SHERLOCK_ENV=docker

LABEL org.label-schema.vcs-ref=$VCS_REF \
      org.label-schema.vcs-url=$VCS_URL \
      org.label-schema.name="Sherlock" \
      org.label-schema.version=$VERSION_TAG \
      website="https://sherlockproject.xyz"

RUN pip3 install --no-cache-dir sherlock-project==$VERSION_TAG

WORKDIR /sherlock

ENTRYPOINT ["sherlock"]
