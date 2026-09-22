"""Independent Modal VMs behind ./run. Project settings come from that script."""

import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import modal

from runner.image import BOOT, CODEX_VERSION, tools_image

REPO, REF, DIRECTORY = (os.environ[f"RUN_{key}"] for key in ("REPO", "REF", "DIRECTORY"))
PORT = int(os.environ["RUN_PORT"])
NAME = os.environ.get("RUN_NAME", "app")


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class VM:
    def __init__(self, state):
        self.state = state
        self.sandbox = modal.Sandbox.from_id(state["sandbox_id"])
        self.output = Path(state["output"])

    @classmethod
    def create(cls, image):
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        sandbox = modal.Sandbox.create(
            "bash",
            "-c",
            BOOT,
            app=modal.App.lookup("modal-compose-demo", create_if_missing=True),
            image=image,
            env={"COMPOSE_PROJECT_NAME": Path(DIRECTORY).name, "APP_PORT": str(PORT)},
            experimental_options={"vm_runtime": True},
            cpu=2,
            memory=4096,
            timeout=1800,
            encrypted_ports=[PORT],
            secrets=[modal.Secret.from_dict({"GH_TOKEN": token})],
            readiness_probe=modal.Probe.with_exec("docker", "info", interval_ms=500),
        )
        try:
            output = CACHE / datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%f")
            output.mkdir(mode=0o700)
            state = {
                "name": NAME,
                "sandbox_id": sandbox.object_id,
                "output": str(output),
            }
            save(ACTIVE, state)
            return cls(state)
        except BaseException:
            sandbox.terminate(wait=True)
            raise

    def record(self):
        save(ACTIVE, self.state)

    def run(self, command, *, cwd=None, timeout=900, secrets=()):
        print(f"$ {command}", flush=True)
        pidfile = f"/tmp/run-{uuid4().hex}.pid"
        process = self.sandbox.exec(
            "setsid",
            "--wait",
            "bash",
            "-o",
            "pipefail",
            "-c",
            f"echo $$ > {pidfile}; trap 'rm -f {pidfile}' EXIT; exec 2>&1\n{command}",
            workdir=cwd or f"/workspace/repo/{DIRECTORY}",
            timeout=timeout,
            secrets=secrets,
        )
        try:
            output = process.stdout.read()
            process.wait()
        except KeyboardInterrupt:
            self.sandbox.exec("bash", "-c", f"kill -TERM -- -$(cat {pidfile})").wait()
            raise
        with (self.output / "commands.log").open("a") as log:
            log.write(f"\n$ {command}\n{output}\nexit={process.returncode}\n")
        print(output[-12000:], end="", flush=True)
        if process.returncode:
            raise RuntimeError(f"Command exited {process.returncode}: {command}")
        return output

    def checkout(self):
        self.sandbox.wait_until_ready(timeout=180)
        self.run("gh auth setup-git", cwd="/workspace")
        self.run(f"git clone -- https://github.com/{REPO}.git /workspace/repo", cwd="/workspace")
        self.run(
            f"git fetch origin {shlex.quote(REF)} && git checkout --detach FETCH_HEAD",
            cwd="/workspace/repo",
        )
        self.state["baseline"] = self.run("git rev-parse HEAD", cwd="/workspace/repo").strip()
        self.run(
            "git config user.name 'Modal Agent' && "
            "git config user.email 'modal-agent@users.noreply.github.com'",
            cwd="/workspace/repo",
        )
        self.record()

    def collect(self):
        if "baseline" in self.state:
            self.run(
                f"git add -N . && git diff --binary {self.state['baseline']} "
                ">/artifacts/changes.patch",
                cwd="/workspace/repo",
            )
            try:
                self.run("docker compose logs --no-color >/artifacts/compose.log")
            except RuntimeError as error:
                print(f"Could not collect Compose logs: {error}", file=sys.stderr)
        for name in (
            "changes.patch",
            "compose.log",
            "prompt.txt",
            "codex-events.jsonl",
            "agent-summary.txt",
        ):
            try:
                self.sandbox.filesystem.copy_to_local(f"/artifacts/{name}", self.output / name)
            except modal.exception.SandboxFilesystemNotFoundError:
                pass
        print(f"Saved: {self.output}", flush=True)

    def stop(self):
        self.sandbox.terminate(wait=True)
        ACTIVE.unlink(missing_ok=True)
        print("Remote VM stopped.", flush=True)


def current(*, cleanup=True):
    if ACTIVE.exists():
        try:
            vm = VM(json.loads(ACTIVE.read_text()))
            if vm.sandbox.poll() is None:
                return vm
        except (FileNotFoundError, modal.exception.NotFoundError):
            pass
        if cleanup:
            ACTIVE.unlink(missing_ok=True)
    return None


def list_running():
    rows = []
    for path in sorted((CACHE / "sessions").glob("*.json")):
        try:
            state = json.loads(path.read_text())
            if modal.Sandbox.from_id(state["sandbox_id"]).poll() is None:
                rows.append(
                    f"{state['name']}\t{state.get('url', '(starting)')}\t{state['sandbox_id']}"
                )
        except (FileNotFoundError, modal.exception.NotFoundError):
            continue
    print(
        "NAME\tURL\tVM\n" + "\n".join(rows)
        if rows
        else "No running remote environments tracked here."
    )


def prepared_image():
    # Only preparing the shared image is serialized across independent VMs.
    with (CACHE / "image.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return load_or_prepare_image()


def load_or_prepare_image():
    if PREPARED.exists():
        cached = json.loads(PREPARED.read_text())
        if cached["expires_at"] > time.time():
            return modal.Image.from_id(cached["image_id"])
    print("Preparing Docker once for subsequent VMs...", flush=True)
    with modal.enable_output():
        vm = VM.create(tools_image())
    try:
        vm.checkout()
        vm.run("docker compose pull --ignore-buildable && docker compose build")
        vm.run("rm -rf /workspace/repo /root/.config/gh /root/.gitconfig", cwd="/workspace")
        vm.run(
            "kill -TERM $(cat /var/run/docker.pid); "
            "for i in $(seq 1 100); do "
            "if [ ! -e /var/run/docker.pid ]; then sync; exit 0; fi; sleep 0.1; done; exit 1",
            cwd="/workspace",
        )
        image = vm.sandbox.snapshot_filesystem(timeout=180, ttl=7 * 24 * 3600)
        save(PREPARED, {"image_id": image.object_id, "expires_at": time.time() + 7 * 24 * 3600})
        return image
    finally:
        vm.stop()


def up():
    vm = current()
    if vm and "url" not in vm.state:
        vm.stop()
        vm = None
    if vm is None:
        with modal.enable_output():
            vm = VM.create(prepared_image())
        try:
            vm.checkout()
            vm.run("docker compose up --build --wait --wait-timeout 120")
            vm.state["url"] = vm.sandbox.tunnels(timeout=60)[PORT].url
            vm.record()
        except BaseException:
            try:
                vm.collect()
            finally:
                vm.stop()
            raise
    print(f"{NAME}: {vm.state['url']}\nVM: {vm.state['sandbox_id']}", flush=True)
    return vm


def agent(vm, prompt):
    if "agent_branch" not in vm.state:
        branch = f"agent/{NAME}-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        vm.run(f"git switch -c {branch}", cwd="/workspace/repo")
        vm.state["agent_branch"] = branch
        vm.record()
    vm.sandbox.filesystem.write_text(prompt, "/artifacts/prompt.txt")
    try:
        vm.run(
            "rm -f /artifacts/agent-summary.txt /artifacts/codex-events.jsonl; "
            "printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null",
            secrets=[modal.Secret.from_dotenv()],
        )
        vm.run(
            "codex --sandbox danger-full-access --ask-for-approval never exec --json "
            "--output-last-message /artifacts/agent-summary.txt - "
            "</artifacts/prompt.txt >/artifacts/codex-events.jsonl",
            cwd="/workspace/repo",
        )
        print(vm.sandbox.filesystem.read_text("/artifacts/agent-summary.txt"), flush=True)
    finally:
        vm.collect()


def main():
    global CACHE, ACTIVE, PREPARED

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", NAME):
        raise RuntimeError("Name must be 1–64 letters, digits, underscores, or hyphens")
    if sys.argv[1] in ("agent", "job") and not sys.argv[2].strip():
        raise RuntimeError("Supply an agent task")
    workspace = modal.Workspace.from_context()
    environment = modal.Environment.from_context()
    workspace.hydrate()
    environment.hydrate()
    print(f"Modal: {workspace.name}/{environment.name}", flush=True)
    CACHE = (
        Path.home()
        / ".cache/modal-compose"
        / workspace.name
        / environment.name
        / REPO.replace("/", "--")
    )
    ACTIVE = CACHE / "sessions" / f"{NAME}.json"
    PREPARED = CACHE / f"prepared-codex-{CODEX_VERSION}.json"
    ACTIVE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.argv[1] == "list":
        list_running()
        return
    if sys.argv[1] in ("shell", "codex"):
        vm = current(cleanup=False)
        if vm is None:
            raise RuntimeError(f"Start this environment with ./run up remote {NAME} first")
        command = "bash"
        if sys.argv[1] == "codex":
            vm.run(
                "printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null",
                secrets=[modal.Secret.from_dotenv()],
            )
            command = "codex"
            if "--resume" in sys.argv[2:]:
                command += " resume --all --include-non-interactive"
            command += " --dangerously-bypass-approvals-and-sandbox"
        command = f"cd /workspace/repo && exec {command}"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "modal",
                "shell",
                vm.sandbox.object_id,
                "--cmd",
                f"bash -c {shlex.quote(command)}",
            ],
            check=True,
        )
        return
    # Serialize other commands per environment; interactive sessions attach without locking.
    with ACTIVE.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"Waiting for another command on {NAME!r} to finish...", flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
        action = sys.argv[1]
        if action == "up":
            up()
            return
        if action == "job":
            vm = up()
            try:
                agent(vm, sys.argv[2])
            finally:
                vm.stop()
            return
        vm = current()
        if vm is None:
            if action == "down":
                print("Remote is already down.")
                return
            raise RuntimeError(f"Start this environment with ./run up remote {NAME} first")
        if action == "down":
            try:
                vm.collect()
            finally:
                vm.stop()
        elif action == "test":
            vm.run(sys.argv[2])
        elif action == "agent":
            agent(vm, sys.argv[2])
        else:
            raise RuntimeError("Use ./run --help")


if __name__ == "__main__":

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        main()
    except KeyboardInterrupt:
        print("Command interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
