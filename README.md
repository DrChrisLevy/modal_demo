# Modal Compose Demo

A small demo of using [Modal VM Sandboxes](https://modal.com/docs/guide/vm-sandboxes)
to run Docker Compose apps, execute
tests, and give coding agents isolated development environments.

The app in [`example/`](example/) is a toy example. Use the demo as a starting point
for building workflows around your own applications, tools, and pipelines.

## Set up for Modal

Requires `uv`, authenticated GitHub CLI (`gh auth login`),
a [Modal account](https://modal.com/signup), and an OpenAI API key.

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

`demo` below is a name you choose for the remote environment. Replace it with
your own name, such as `feature-a`, and use that name in subsequent commands.

```bash
./run up remote demo      # start a VM and print the app URL
./run list                # list running remote environments tracked on this machine
./run shell demo          # open a shell in the VM; exit to return
./run agent demo "Add task filtering and tests. Do not push."
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
./run agent "Add task filtering and tests. Open a PR."
./run agent "Change the UI to look like a 90s retro website. Open a PR."
```

Creates a fresh VM, starts the app, runs Codex, saves results, and stops the VM.
Run commands in separate terminals for parallel tasks. Each agent call starts
a new conversation; named VMs retain files between calls.

## Results

- Agent runs and remote `down` save a patch, logs, and agent output under
  `~/.cache/modal-compose/`. The command prints the directory. Changes are not
  automatically applied to your local checkout.
- VMs expire after **30 minutes**. Run `down` before expiry to save remaining
  work. Remote databases are discarded when their VM stops.
- The first remote run prepares Docker; subsequent VMs reuse the build cache
  for up to seven days.

## Run locally (optional)

Local runs require Docker Compose. With Docker running:

```bash
./run up              # build and print the local URL (first free port from 8000)
./run test            # run integration tests and lint
./run shell           # open a shell in the web container; exit to return
./run down            # stop containers; keep the database
./run down --volumes  # stop containers and delete the database
```

With the Codex CLI installed locally:

```bash
./run codex           # start in the current checkout
./run codex --resume  # resume here
```

Use `./run --help` for the command summary.
