# Modal Compose Runner

Run a Docker Compose app locally or in a Modal VM, then let Codex work on it.

## Setup

Requires `uv`, Docker Compose, authenticated GitHub CLI (`gh auth login`),
and a Modal account with VM Sandbox access.

```bash
uv sync --frozen
uv run modal setup  # skip if already authenticated
```

For agents, create a Modal Secret named `openai-secret` containing `OPENAI_API_KEY`.

## Local

Start Docker, then run:

```bash
./run up    # build and serve at http://localhost:8000
./run test  # run integration tests and lint
./run shell # open a shell in the web container; exit to return
./run down  # stop containers; keep the database
```

## Remote

Remote runs clone the GitHub repository/ref configured at the top of `run`.
Push changes before starting a new VM.

```bash
./run up remote demo      # start a VM and print the app URL
./run list                # list running remote environments tracked on this machine
./run shell remote demo   # open a shell in the VM; exit to return
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

To resume a previous agent session from the remote VM shell with sandboxing and approval prompts disabled, run `codex resume --all --include-non-interactive --dangerously-bypass-approvals-and-sandbox`.

## One-shot agents

```bash
./run agent "Add task filtering and tests. Do not push."
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

Use `./run --help` for the command summary.
