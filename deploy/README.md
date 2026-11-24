# Production deploy

Every push to `main` runs `.github/workflows/deploy.yaml`. It connects over SSH
to the EC2 server, fetches the pushed commit, copies **that commit's**
`deploy/deploy.sh` to a private folder and runs it detached (`nohup`), streaming
its log back to the job. If the SSH session drops, the deploy still finishes.

## What `deploy.sh <sha>` does

1. Takes a lock, so only one deploy runs at a time.
2. Preflight: required commands, `uv`, the `.env` files, passwordless sudo, the
   four systemd units, PostgreSQL running, at least 1500 MB free disk.
3. Fetches `origin/main` and checks the commit exists and is on `main`.
4. Checks out the commit, runs `uv sync --locked` for the three Python services,
   and runs `npm ci` / `npm run build` for the frontend only when its lock file
   or source changed.
5. Restarts `registry`, `weather`, `planner`, `frontend` (in that order).
6. Health checks: HTTP 200 from each service (and `GET /v1/farms` for the
   database), then a 10-second soak to catch crash loops.
7. On failure: prints the last journal lines (passwords in URLs masked) and
   rolls back to the last known good commit, running the same steps.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Deployed, all services healthy. |
| 1 | Deploy failed, rolled back; the server is healthy on the last good commit. The job is red on purpose. |
| 2 | Deploy failed and the rollback failed too (or there was nothing to roll back to). Manual action needed. |
| 3 | Refused before any change: bad input, another deploy running, or preflight failed. |

## State on the server: `/home/ubuntu/.agropilot-deploy`

- `last-good-sha`: the last commit that passed all health checks (the rollback target).
- `history.log`: one line per deploy: time, commit, result.
- `logs/`: the full log of each deploy (newest 20 kept).
- `scripts/`: the copy of `deploy.sh` each deploy ran (newest 10 kept).

## Checking the server safely

On the server, from the repo:

```bash
bash deploy/deploy.sh --preflight
```

This only runs the checks and changes nothing. Exit 0 means ready, 3 means a
problem (each one is printed).

## Notes

- **Preflight before the first deploy** (`deploy/` is not on the server yet). From the laptop:
  `ssh -i ~/.ssh/agropilot-key.pem ubuntu@<server> "git -C /home/ubuntu/AgroPilot fetch origin && git -C /home/ubuntu/AgroPilot show origin/cd/deploy-all:deploy/deploy.sh | bash -s -- --preflight"`
  After the first deploy, run `bash /home/ubuntu/AgroPilot/deploy/deploy.sh --preflight`.
- **Frontend rebuild:** it is rebuilt only when `services/frontend` changes in git.
  Server-side variables in `.env.local` are read at runtime and the frontend is
  restarted on every deploy, so they take effect. If a `NEXT_PUBLIC_*` variable is
  ever added, delete `services/frontend/.next/.agropilot-tree` on the server to force a rebuild.

## Known limits

- A few seconds of downtime per deploy while services restart (longer for the
  frontend when it must be rebuilt).
- systemd unit files and `.env` files are not in git; they are set up by hand on
  the server.
- No automatic database migrations.
- No notifications: check the GitHub Actions job.
