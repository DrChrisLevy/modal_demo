"""uv run python -m runner --help"""

import argparse
import asyncio
import os
import re
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


def parse_args():
    parser = argparse.ArgumentParser(description="Run a GitHub Compose project in a Modal VM")
    parser.add_argument("--repo", required=True, help="GitHub OWNER/REPO")
    parser.add_argument("--ref", default="main", help="Published branch, tag, or commit")
    parser.add_argument("--directory", default=".", help="Compose directory relative to repo root")
    parser.add_argument("--profile", required=True, help="Local Modal profile to use")
    parser.add_argument("--workspace", required=True, help="Expected server-verified workspace")
    parser.add_argument("--environment", default="main")
    parser.add_argument("--port", type=int, default=8000, help="VM port to expose over HTTPS")
    parser.add_argument("--command", help="Command to run in the Compose directory")
    parser.add_argument("--prompt", type=Path, help="Run Codex with this local prompt file")
    parser.add_argument("--branch", help="New Git branch for the agent")
    parser.add_argument("--secret", default="openai-secret", help="Modal Secret for Codex")
    parser.add_argument("--hold", action="store_true", help="Keep app up until Ctrl+C")
    parser.add_argument("--cpu", type=float, default=2)
    parser.add_argument("--memory", type=int, default=4096, help="VM RAM in MiB")
    parser.add_argument("--timeout", type=int, default=1800, help="Hard VM lifetime in seconds")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be OWNER/REPO")
    directory = PurePosixPath(args.directory)
    if directory.is_absolute() or ".." in directory.parts:
        parser.error("--directory must stay inside the repository")
    args.directory = str(directory)
    if args.prompt and (not args.prompt.is_file() or not args.branch):
        parser.error("--prompt requires an existing file and --branch")
    if not 1 <= args.port <= 65535 or args.timeout < 60 or args.memory < 1024 or args.cpu <= 0:
        parser.error("invalid port, resource, or timeout value")
    return args


def main():
    args = parse_args()
    # Set profile before importing the SDK; never change the user's saved default.
    os.environ.update(
        MODAL_PROFILE=args.profile, MODAL_ENVIRONMENT=args.environment, MODAL_SANDBOX_V2="1"
    )  # SDK 1.5.5 backend compatibility flag.
    from modal.config import Config, _lookup_workspace

    from .session import Session

    config = Config()
    workspace = asyncio.run(
        _lookup_workspace(
            config.get("server_url"), config.get("token_id"), config.get("token_secret")
        )
    ).username
    if workspace != args.workspace:
        raise RuntimeError(f"Workspace {workspace!r} does not match {args.workspace!r}; stopped")
    print(f"Verified Modal workspace: {workspace}, environment: {args.environment}", flush=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%f")
    output = Path("artifacts") / run_id
    output.mkdir(parents=True)
    session = Session(args, output)
    started = time.monotonic()

    # SIGTERM follows the same artifact/cleanup path as Ctrl+C.
    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        session.start()
        if args.prompt:
            session.agent()
        if args.command:
            session.run(args.command, timeout=600)
        session.result["status"] = "passed"
        session.save()
        if args.hold:
            print("App is running. Ctrl+C stops the VM and exports artifacts.", flush=True)
            while session.sandbox.poll() is None:
                time.sleep(2)
    except KeyboardInterrupt:
        session.result["status"] = "stopped"
    except Exception as error:
        session.result.update(status="failed", error=str(error))
        raise
    finally:
        cleanup_errors = []
        if session.sandbox is not None:
            try:
                session.collect()
            except Exception as error:
                cleanup_errors.append(f"Artifact collection: {error}")
            try:
                session.sandbox.terminate(wait=True)
                session.result["terminated"] = True
                print(f"VM stopped: {session.sandbox.object_id}", flush=True)
            except Exception as error:
                cleanup_errors.append(f"VM termination: {error}")
        if cleanup_errors:
            session.result.update(status="failed", cleanup_errors=cleanup_errors)
        session.result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        session.save()
        print(f"Artifacts: {output.resolve()}", flush=True)
        if cleanup_errors and sys.exc_info()[0] is None:
            raise RuntimeError("; ".join(cleanup_errors))


if __name__ == "__main__":
    main()
