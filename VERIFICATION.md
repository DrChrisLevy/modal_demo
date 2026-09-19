# Verified on personal Modal — September 19, 2026

All remote runs used server-verified workspace **drchrislevy**, environment
**main**, 2 CPUs and 4 GiB RAM. The repository is private. All five VM Sandboxes
were terminated and their stopped state was checked through the Modal API.

| Check | Result |
| --- | --- |
| Full app built from its Dockerfile and started by Compose | Passed |
| Web app and PostgreSQL both healthy | Passed |
| Baseline real HTTP/PostgreSQL integration tests | 7 passed; Ruff passed |
| Browser: add task, complete it, reload | Passed; completion persisted |
| Restart only the web container | All 3 existing tasks preserved in PostgreSQL |
| App dependencies isolated from VM tools | FastAPI absent on VM host, installed in web container |
| Different Compose project, service `site`, port 8080 | Public HTTPS returned its expected page with the same runner |
| Authenticated Codex task in a fresh VM | Completed, 9 tool commands; committed and pushed its branch |
| Agent feature tests | 10 passed; Ruff passed |
| Independent HTTPS filtering checks | Passed against both agent VM and fresh replay VM |
| Browser filtering on replay VM | Open stays selected when adding; completed task disappears from Open and appears in Done |
| Published PR branch cloned into a fresh VM | 10 passed; Ruff passed |
| Exported patch includes agent's committed changes | Passed `git apply --check` on local main |
| Interrupt a running 120-second command | Controller exited in 1.16 seconds, exported artifacts and terminated VM |

## The actual agent PR

[Draft PR #1: Add task status filtering](https://github.com/DrChrisLevy/modal_demo/pull/1)

- Branch: `demo/task-filters-20260919-203312`
- Commit: `bfcd6266ccd2eb5038617875584ab34c8b8de688`
- Only `example/app.py`, `example/static/index.html`, `example/tests/test_app.py`,
  and `example/README.md` changed. No launcher changes were needed for the feature.
- Codex ran inside the VM, used its actual Docker daemon and app/database, and
  created the draft PR itself with `gh`. The PR remains unmerged.

Replay the existing result without another agent/API call or another PR:

```bash
./demo.sh serve --ref demo/task-filters-20260919-203312
```

For a new live agent demonstration from the baseline:

```bash
./demo.sh agent --hold
```

## Evidence

[Run metadata](demo/verified-runs.json) records the workspace, VM IDs, source
commits, cleanup state, and actual Codex usage. Detailed local logs are under
`artifacts/<run-id>/`; they are intentionally excluded from the Git repository.

- Baseline: `20260919T203055-251616`
- Alternate project: `20260919T203210-216436`
- Agent and PR: `20260919T203312-910278`
- Fresh replay: `20260919T203713-095655`
- Command interruption: `20260919T203746-307531`

The early interactive runs record `status: stopped` after their successful checks
and intentional shutdown. A Sandbox exit code of 137 is the terminated idle VM
entrypoint, not a pytest failure. Elapsed times include browser checks and time
left open for inspection; they are not startup benchmarks.

## Practical limits

This validates the included projects on Linux VMs. The launcher expects a repo
whose Compose setup can start there; it does not infer missing secrets, external
services, host-specific mounts, or kernel settings. The pinned Debian Docker
package uses the legacy builder when Buildx is absent; Dockerfiles requiring
BuildKit-only features would need Buildx added to the tools image.

The example uses development credentials and synthetic tasks. Its HTTPS URL is
public while the VM runs, and data is ephemeral when the VM is destroyed. VM
Sandboxes are currently beta. The agent is trusted code with access to the
credentials supplied for its private-repository workflow.
