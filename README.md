# Give a coding agent an ordinary development environment

An existing Docker Compose project runs inside a fresh **Modal VM Sandbox**.
The app, database, and tests stay in Docker. Codex works on the checkout using
the same development commands a person would use, then opens a draft PR.

**[Verified runs and replay instructions](VERIFICATION.md)** ·
**[Agent-created draft PR](https://github.com/DrChrisLevy/modal_demo/pull/1)**

```text
Your laptop: uv + Modal SDK
        │ create VM, clone a repo, run commands, collect artifacts
        ▼
Modal VM Sandbox
  Docker daemon ── Compose: web app + PostgreSQL
  Git checkout ─── source bind mount into the web container
  Codex CLI ────── edit → restart → test → push branch → draft PR
```

## The boundary that matters

| Directory | Owns | Knows about Modal? |
| --- | --- | --- |
| `runner/` | VM tools image, checkout, HTTPS tunnel, commands, artifacts, cleanup | Yes |
| `example/` | App, database, Dockerfile, Compose, dependencies, tests | No |
| `demo/` and `demo.sh` | This presentation's project selection, prompt, and checks | Only the wrapper |

There are no imports or dependencies on `modal_dash` or the earlier experiments.
The runner does not know about FastAPI, PostgreSQL, schema creation, task routes,
or test commands. To bring another project, supply another repo, Compose
directory, port, and command. That project still owns its environment definition.

## Prerequisites

- `uv`, the GitHub CLI (`gh auth login`), and a configured Modal profile.
- Access to this private repository and Modal VM Sandboxes (currently beta).
- For the agent: a Modal Secret named `openai-secret` containing `OPENAI_API_KEY`.
  This uses Codex API billing, not this desktop chat's subscription.

The convenience script explicitly defaults to Chris's personal Modal profile
and server workspace `drchrislevy`, environment `main`. It verifies the workspace
before provisioning. It never changes your saved Modal default.

For your own account, set `DEMO_MODAL_PROFILE`, `DEMO_MODAL_WORKSPACE`, and
`DEMO_REPO=OWNER/REPO` to a copy of this repo. The agent creates a branch and draft
PR in that repository. The local `gh` credential is passed to the fresh VM as an
ephemeral Modal Secret; it is not embedded in the image or URL.

## Run the example

```bash
uv sync --frozen
./demo.sh check          # Start the full app, run HTTP integration tests, stop
./demo.sh serve          # Same checks; leave the HTTPS app up until Ctrl+C
./demo.sh agent          # Codex adds filtering, tests it, opens a draft PR, stops
./demo.sh agent --hold   # Leave the changed app up for the presentation
```

Each run prints `APP_URL` and a local `artifacts/<run>/` directory. Source is
cloned from **GitHub**, not your laptop: push a change before trying it remotely.
Use `--ref BRANCH_OR_SHA` to run a published revision. The tools image has no
application source; source changes do not rebuild that image.

`agent` starts a new branch from `main` and performs a real paid Codex task.
Repeated runs create separate draft PRs. Nothing is merged automatically.

To independently exercise the live app from your laptop:

```bash
uv run python demo/verify.py https://YOUR-APP-URL
uv run python demo/verify.py https://YOUR-APP-URL --filters  # after the agent edit
```

The sample app also runs locally, without Modal:

```bash
cd example
docker compose up --build --wait
docker compose exec -T web uv run --frozen pytest -q
# Open http://localhost:8000
docker compose down
```

Both projects use uv and committed lockfiles. The application environment lives
inside the web image at `/opt/venv`, outside the `/app` source bind mount.

## Use the launcher with another project

```bash
uv run --frozen python -m runner \
  --profile YOUR_PROFILE --workspace YOUR_WORKSPACE \
  --repo OWNER/REPO --ref main --directory . --port 8000 \
  --command 'docker compose exec -T web uv run --frozen pytest -q' --hold
```

The directory must contain a Compose file. Compose starts the app with
`up --build --wait`; define healthchecks to make readiness meaningful. The app
must publish its HTTP port on the VM. Relative build contexts and bind mounts
resolve within the cloned repository. Project-specific secrets, host files,
external services, privileged requirements, or special kernel configuration need
explicit setup; this small example does not infer them.

A second, unrelated Compose fixture serves a static page on **8080**, with a
service named `site`. It exercises the same launcher with no Python app or
database setup:

```bash
uv run --frozen python -m runner \
  --profile drchrislevy --workspace drchrislevy \
  --repo DrChrisLevy/modal_demo --directory demo/alternate --port 8080 --hold
```

## What actually runs where

The VM tools image contains Docker, Compose, Git, and `gh`. Agent runs add the
pinned Codex CLI. Application dependencies are installed by **the project's
Dockerfile** using `uv sync --frozen`. PostgreSQL runs in another Docker container.
There is no Python app environment installed on the VM host.

This uses `experimental_options={"vm_runtime": True}`. SDK 1.5.5 also needs the
internal `MODAL_SANDBOX_V2=1` backend opt-in; that flag is independent of choosing
a VM runtime. VM Sandboxes are CPU-only and beta. This example does not use
Sidecars or the OpenAI Agents API.

The HTTPS tunnel is public while the VM is running. This sample has synthetic
tasks and no authentication. PostgreSQL has no published port. The trusted demo
agent has full access within its disposable VM, including Docker and the
credentials supplied for this workflow. Do not treat this as an untrusted
multi-tenant agent host.

Each VM has a fresh Docker daemon and database volume. The tools image is cached;
inner Docker pulls and builds happen again on a fresh VM. Registry/network time
is part of startup. Docker layer caching or snapshots are an optional extension,
not a prerequisite for this demo. Data survives a web-container restart, but is
removed when the VM is terminated. Ctrl+C, normal completion, and failures stop
the VM; a 30-minute hard timeout bounds an abandoned run. No VM stays deployed.

Artifacts include the resolved source SHA, VM/workspace, command log, Compose
log, Codex event stream/summary, PR URL, and a patch relative to the initial
checkout (including committed changes). The artifacts are ignored by Git. The
runner's checks are the commands you supply; the app-specific independent checks
live in `demo/verify.py`.

## A 20-minute walkthrough

1. **0–3 min:** A repo already runs with Compose. Explain the isolation problem
   when several coding tasks need an app and a database at the same time.
2. **3–7 min:** Read the VM creation, Git checkout, and Compose startup. Show that
   no application dependencies or setup are described in the runner.
3. **7–10 min:** Open the HTTPS app, add a task, and run its real integration tests.
4. **10–16 min:** Show Codex changing the app, restarting the web container,
   running tests, and producing a draft PR. Keep a completed run ready as backup.
5. **16–20 min:** Review the diff and explain the sharp edges: fresh Docker cache,
   readiness, credentials, source revisions, and exporting work before teardown.

## References

- [Modal VM Sandboxes](https://modal.com/docs/guide/vm-sandboxes)
- [Modal Sandbox filesystem](https://modal.com/docs/guide/sandbox-files)
- [Modal networking](https://modal.com/docs/guide/sandbox-networking)
- [Modal SDK release notes](https://modal.com/docs/sdk/py/releases)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
