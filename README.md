# Modal Compose Runner

Run a Docker Compose app locally or in a Modal VM, then let Codex work on it.

## Setup

Requires `uv`, Docker Compose (local runs only), authenticated GitHub CLI (`gh auth login`),
and a Modal account with VM Sandbox access.

The Modal sandbox uses your local `gh` token with the same GitHub permissions.

```bash
uv sync --frozen
uv run modal setup  # skip if already authenticated
```

For agents, set your key in the repo-root `.env` (gitignored):

```dotenv
OPENAI_API_KEY=your-openai-api-key-here
```

## Local

Start Docker, then run:

```bash
./run up              # build and print the local URL (first free port from 8000)
./run test            # run integration tests and lint
./run shell           # open a shell in the web container; exit to return
./run down            # stop containers; keep the database
./run down --volumes  # stop containers and delete the database
```

## Remote

Remote runs clone the GitHub repository/ref configured at the top of `run`.
Set `RUN_REPO` or `RUN_REF` to override those defaults.
Push changes before starting a new VM.

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

## CI

[The GitHub Actions workflow](.github/workflows/ci.yml) runs on pull requests to
`main`. Add `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` as repository Actions secrets
for a Modal workspace with VM Sandbox access.

GitHub starts a Modal VM with the PR's merge commit, runs the same
`./run test remote ci` integration tests and Ruff checks, and stops the VM even
if startup or tests fail. The job uses GitHub's read-only token to clone the repo.
Fork and Dependabot PRs are skipped because they cannot use these Actions secrets.

## Interactive Codex

```bash
./run codex                # start in the current checkout
./run codex --resume       # resume here
./run codex demo           # connect to demo and start Codex
./run codex demo --resume  # connect to demo and pick a previous session
```

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
