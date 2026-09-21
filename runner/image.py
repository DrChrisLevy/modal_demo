"""The reusable VM tools image contains no project source or app dependencies."""

import modal

COMPOSE_VERSION = "v2.39.4"
COMPOSE_SHA256 = "7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4"
CODEX_VERSION = "0.155.1"
CODEX_SHA256 = "a65b895c6ac1a73629bbe4b864640c86133e94a43b4d67b3103044e1a306d5a2"

# The Modal VM runs its own Docker engine.
BOOT = """
# Start Docker, wait for it to be ready, then keep the VM alive.
set -eu
mkdir -p /workspace /artifacts
dockerd --host unix:///var/run/docker.sock >/tmp/dockerd.log 2>&1 &
for attempt in $(seq 1 120); do
    if docker info >/dev/null 2>&1; then
        exec sleep infinity
    fi
    sleep 1
done
cat /tmp/dockerd.log
exit 1
"""


def tools_image():
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
    return image.run_commands(
        f"curl -fsSL https://github.com/openai/codex/releases/download/"
        f"rust-v{CODEX_VERSION}/codex-package-x86_64-unknown-linux-musl.tar.gz "
        "-o /tmp/codex.tar.gz",
        f"echo '{CODEX_SHA256}  /tmp/codex.tar.gz' | sha256sum -c -",
        "tar -xzf /tmp/codex.tar.gz -C /usr/local && rm /tmp/codex.tar.gz",
        "codex --version",
    )
