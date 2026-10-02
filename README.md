# Modal Compose Demo

A small demo of using [Modal VM Sandboxes](https://modal.com/docs/guide/sandboxes#runtimes)
to run Docker Compose apps, execute
tests, and give coding agents isolated development environments.

The app in [`example/`](example/) is **Fieldwork**, a multimodal workspace with a
browser frontend, FastAPI, PostgreSQL, Redis, and OpenSearch. Analyze text, images,
and audio with seven real CPU models, then browse and search the saved results.
The application and tests are adapted from
[modal-native-test-stack-poc](https://github.com/DrChrisLevy/modal-native-test-stack-poc).
The app and its services run entirely through Docker Compose inside one VM.

Use the demo as a starting point for development, test, and agent workflows around
your own applications. This is a proof of concept, not production software.

## Set up for Modal

Requires `uv`, authenticated GitHub CLI (`gh auth login`),
a [Modal account](https://modal.com/signup), and an OpenAI API key.

VMs use the generally available `runtime="vm"` API in Modal SDK 1.6.0.
Docker runs inside the Modal VM; no local Docker installation is needed.
The Modal sandbox uses your local `gh` token with the same GitHub permissions.

```bash
uv sync --frozen
uv run modal setup  # skip if already authenticated
```

Add your OpenAI API key to a `.env` file in the repo root:

```dotenv
OPENAI_API_KEY=your-openai-api-key-here
```

## Run on Modal

New VMs clone `RUN_REPO` at `RUN_REF`, set at the top of `run`.
Commit and push application changes before starting a new VM to include them.
For a branch, use `RUN_REF=your-branch ./run up remote demo`; the runner resolves it
to a commit so the build and app use the same source.

`demo` below is a name you choose for the remote environment. Replace it with
your own name, such as `feature-a`, and use that name in subsequent commands.

```bash
./run up remote demo      # start a VM and print the app URL
./run list                # list running remote environments tracked on this machine
./run shell demo          # open a shell in the VM; exit to return
./run agent demo "Add asset filtering and tests. Do not push."
./run test remote demo    # run integration tests and lint in that VM
./run down remote demo    # save changes and logs, then destroy the VM
```

Commands with the same name use the same VM. Different names run independently.
Omit the name on `up`, `test`, or `down` to use `app`. Repeating `up` reuses the
running VM; use `down` then `up` to clone updated code.

The remote shell starts in `/workspace/repo`, the same directory as the agent.
Use `cd example && docker compose exec web bash` to enter the app container.
Exiting either shell leaves the app running.

## Interactive Codex

With `demo` running:

```bash
./run codex demo           # connect to demo and start Codex
./run codex demo --resume  # connect to demo and pick a previous session
```

## One-shot agents

```bash
./run agent "Add asset filtering and tests. Open a PR."
./run agent "Change the UI to look like a 90s retro website. Open a PR."
```

Creates a fresh VM, starts the app, runs Codex, saves results, and stops the VM.
Run commands in separate terminals for parallel tasks. Each agent call starts
a new conversation; named VMs retain files between calls.

## Results

- Agent runs and remote `down` save a patch, logs, and agent output under
  `~/.cache/modal-compose/`. The command prints the directory. Changes are not
  automatically applied to your local checkout.
- Remote commands time out after **1 hour**. VMs expire **1 hour after creation**.
  Run `down` before expiry to save remaining work. Remote databases are discarded
  when their VM stops.
- The first remote run builds Docker images and downloads the seven pinned models
  (roughly a few GB). Subsequent VMs reuse the model Volume and Docker snapshot.
  A changed source commit refreshes the snapshot using the previous build cache;
  snapshots expire after seven days.
- Model weights live in the `modal-compose-demo-models` Modal Volume. Preparation
  mounts it writable; app/agent VMs mount it read-only, including inside Docker.
  Terminating the preparation VM commits the downloads before the app VM starts.
  The Volume persists when an environment is stopped. Only weights are shared;
  PostgreSQL, Redis, and OpenSearch remain isolated per VM.
- Defaults are 4 CPUs and 16 GiB RAM. Override with `RUN_CPU`, `RUN_MEMORY` (MiB),
  or choose another model Volume with `RUN_MODEL_VOLUME` when starting a VM.
- Open the printed URL for the frontend, `/docs` for the interactive API, or
  `/health/ready` for service and model readiness.

## Run locally (optional)

Local runs require Docker Compose with enough memory for the ML stack (16 GiB is
recommended). The first startup downloads models into a local Docker volume;
later starts reuse them. With Docker running:

```bash
./run up              # build and print the local URL (first free port from 8000)
./run test            # run integration tests and lint
./run shell           # open a shell in the web container; exit to return
./run down            # stop containers; keep the database
./run down --volumes  # stop containers and delete local databases AND model weights
```

Tests exercise real models and services, the API, and the complete asset pipeline,
and enforce at least 80% Python coverage. Missing integration dependencies fail
the suite. Each test run uses a temporary database, leaving the app’s library
untouched. `./run test` also checks Ruff lint and formatting. The app stores analysis
and metadata; original image/audio uploads are not retained.

With the Codex CLI installed locally:

```bash
./run codex           # start in the current checkout
./run codex --resume  # resume here
```

Use `./run --help` for the command summary.

View the [presentation slides](https://drchrislevy.github.io/modal_demo/slides/#slide-1) in your browser.
