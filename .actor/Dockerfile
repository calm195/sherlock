FROM sherlock/sherlock as sherlock

# 安装 Node.js。
RUN apt-get update; apt-get install curl gpg -y
RUN mkdir -p /etc/apt/keyrings
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
RUN echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list
RUN apt-get update && apt-get install -y curl bash git jq jo xz-utils nodejs

# 为 Actor 运行环境安装基于 Node.js 的 Apify CLI。
RUN npm -g install apify-cli

# 安装 Actor Shell 脚本所需的依赖。
RUN apt-get update && apt-get install -y bash jq jo xz-utils nodejs

# 复制包含 Actor 启动脚本的 .actor 目录。
COPY .actor/ .actor

ENTRYPOINT [".actor/actor.sh"]
