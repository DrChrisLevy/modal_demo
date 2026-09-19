"""The reusable VM tools image contains no project source or app dependencies."""

import modal

COMPOSE_VERSION = "v2.39.4"
COMPOSE_SHA256 = "7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4"
CODEX_VERSION = "0.149.1"
CODEX_SHA256 = "1e8531ae5f6dea3c6e11e53e74cc5ac81bf1ba597f9b296fb112d6ea30fdaf5d"

# Docker runs inside the VM. No host Docker socket or laptop daemon is involved.
BOOT = """
set -eu
mkdir -p /workspace /artifacts
dockerd --host unix:///var/run/docker.sock >/tmp/dockerd.log 2>&1 &
for attempt in $(seq 1 120); do
    if docker info >/dev/null 2>&1; then
        touch /tmp/docker-ready
        exec sleep infinity
    fi
    sleep 1
done
cat /tmp/dockerd.log
exit 1
"""


def tools_image(*, agent=False):
    plugin = "/usr/local/lib/docker/cli-plugins/docker-compose"
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .apt_install("docker.io", "curl", "git", "gh", "ca-certificates", "ripgrep")
        .run_commands(
            "mkdir -p /usr/local/lib/docker/cli-plugins /workspace /artifacts",
            f"curl -fsSL https://github.com/docker/compose/releases/download/"
            f"{COMPOSE_VERSION}/docker-compose-linux-x86_64 -o {plugin}",
            f"echo '{COMPOSE_SHA256}  {plugin}' | sha256sum -c -",
            f"chmod +x {plugin}",
            "docker compose version",
        )
        .env({"GH_PROMPT_DISABLED": "1", "COMPOSE_PARALLEL_LIMIT": "1"})
        .workdir("/workspace")
    )
    if agent:
        image = image.run_commands(
            f"curl -fsSL https://github.com/openai/codex/releases/download/"
            f"rust-v{CODEX_VERSION}/codex-package-x86_64-unknown-linux-musl.tar.gz "
            "-o /tmp/codex.tar.gz",
            f"echo '{CODEX_SHA256}  /tmp/codex.tar.gz' | sha256sum -c -",
            "tar -xzf /tmp/codex.tar.gz -C /usr/local && rm /tmp/codex.tar.gz",
            "codex --version",
        )
    return image
