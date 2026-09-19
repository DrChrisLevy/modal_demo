"""A VM, a checkout, and ordinary Compose commands. No app-specific setup."""

import json
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import modal

from .image import BOOT, tools_image


class Session:
    def __init__(self, args, output):
        self.args, self.output = args, output
        self.sandbox = None
        self.directory = "/workspace/repo/" + args.directory
        self.baseline = None
        self.result = {"status": "running", "repo": args.repo, "ref": args.ref}

    def run(self, command, *, cwd=None, timeout=600, quiet=False):
        """Keep command logs locally and drain both pipes to avoid deadlocks."""
        print(f"$ {command}", flush=True)
        process = self.sandbox.exec(
            "bash",
            "-o",
            "pipefail",
            "-c",
            command,
            workdir=cwd or self.directory,
            timeout=timeout,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            stdout = pool.submit(process.stdout.read)
            stderr = pool.submit(process.stderr.read)
            process.wait()
            out, err = stdout.result(), stderr.result()
        with (self.output / "commands.log").open("a") as log:
            log.write(f"\n$ {command}\n{out}{err}\nexit={process.returncode}\n")
        if not quiet:
            print((out + err)[-12000:], end="", flush=True)
        if process.returncode != 0:
            raise RuntimeError(f"Command failed ({process.returncode}): {command}\n{err[-2000:]}")
        return out

    def start(self):
        args = self.args
        # The token is held in memory and supplied as an ephemeral Modal Secret.
        # It is never embedded in the cached image, clone URL, or local artifacts.
        token = subprocess.run(
            ["gh", "auth", "token"], check=True, capture_output=True, text=True
        ).stdout.strip()
        secret_list = [modal.Secret.from_dict({"GH_TOKEN": token})]
        if args.prompt:
            secret_list.append(
                modal.Secret.from_name(args.secret, required_keys=["OPENAI_API_KEY"])
            )
        app = modal.App.lookup("modal-compose-demo", create_if_missing=True)
        with modal.enable_output():
            image = tools_image(agent=bool(args.prompt)).build(app)
            self.sandbox = modal.Sandbox.create(
                "bash",
                "-c",
                BOOT,
                image=image,
                app=app,
                experimental_options={"vm_runtime": True},
                cpu=args.cpu,
                memory=args.memory,
                timeout=args.timeout,
                secrets=secret_list,
                encrypted_ports=[args.port],
                readiness_probe=modal.Probe.with_exec(
                    "test", "-f", "/tmp/docker-ready", interval_ms=500
                ),
            )
        self.result.update(
            sandbox_id=self.sandbox.object_id,
            workspace=args.workspace,
            environment=args.environment,
        )
        self.save()
        print(f"VM: {self.sandbox.object_id}", flush=True)
        self.sandbox.wait_until_ready(timeout=180)
        self.run("gh auth setup-git", cwd="/workspace")
        self.run(
            f"git clone -- https://github.com/{args.repo}.git /workspace/repo", cwd="/workspace"
        )
        self.run(f"git fetch origin {shlex.quote(args.ref)}", cwd="/workspace/repo")
        self.run("git checkout --detach FETCH_HEAD", cwd="/workspace/repo")
        self.baseline = self.run("git rev-parse HEAD", cwd="/workspace/repo").strip()
        self.result["source_sha"] = self.baseline
        self.run(
            "git config user.name 'Modal Demo Agent' && "
            "git config user.email 'modal-demo-agent@users.noreply.github.com'",
            cwd="/workspace/repo",
        )
        if args.prompt:
            self.run(f"git switch -c {shlex.quote(args.branch)}", cwd="/workspace/repo")
        self.run("docker version --format '{{.Server.Version}}' && docker compose version")
        self.run("docker compose config --quiet")
        # Fresh VMs have empty Docker caches. Retry only registry rate limiting.
        for attempt in range(4):
            try:
                self.run("docker compose up --build --wait --wait-timeout 120", timeout=900)
                break
            except RuntimeError as error:
                if attempt == 3 or not any(
                    marker in str(error).lower()
                    for marker in ("toomanyrequests", "rate exceeded", "429 too many")
                ):
                    raise
                time.sleep(5 * 2**attempt)
        self.result["url"] = self.sandbox.tunnels(timeout=60)[args.port].url
        self.save()
        print(f"\nAPP_URL={self.result['url']}\n", flush=True)

    def agent(self):
        self.sandbox.filesystem.write_text(self.args.prompt.read_text(), "/artifacts/prompt.md")
        self.run("printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null", quiet=True)
        command = (
            "codex --sandbox danger-full-access --ask-for-approval never exec --json "
            "--output-last-message /artifacts/agent-summary.md - "
            "</artifacts/prompt.md >/artifacts/codex-events.jsonl"
        )
        self.run(command, cwd="/workspace/repo", timeout=900)
        events = self.sandbox.filesystem.read_text("/artifacts/codex-events.jsonl")
        parsed = [json.loads(line) for line in events.splitlines() if line.startswith("{")]
        completed = [event for event in parsed if event.get("type") == "turn.completed"]
        commands = [
            event
            for event in parsed
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "command_execution"
        ]
        if not completed or not commands:
            raise RuntimeError("Codex did not finish a turn with executed commands")
        self.result.update(agent_commands=len(commands), agent_usage=completed[-1].get("usage"))
        print(self.sandbox.filesystem.read_text("/artifacts/agent-summary.md"), flush=True)

    def collect(self):
        """Export changes even when the agent committed them or a later check fails."""
        if self.baseline:
            self.run(
                f"git add -N . && git diff --binary {self.baseline} >/artifacts/changes.patch",
                cwd="/workspace/repo",
            )
            self.run("docker compose logs --no-color >/artifacts/compose.log", quiet=True)
        for name in [
            "changes.patch",
            "compose.log",
            "prompt.md",
            "codex-events.jsonl",
            "agent-summary.md",
            "pr-url.txt",
        ]:
            try:
                self.sandbox.filesystem.copy_to_local(f"/artifacts/{name}", self.output / name)
            except modal.exception.SandboxFilesystemNotFoundError:
                pass

    def save(self):
        (self.output / "result.json").write_text(json.dumps(self.result, indent=2) + "\n")
