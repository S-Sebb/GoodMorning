# Server maintenance

`SebOracle` updates itself every day at 05:00 China time. That routine lives in
the owner's private `S-Sebb/SebOracle` repository: it installs Ubuntu, snap and
SiYuan updates, checks sing-box and decides on the reboot. It touches
GoodMorning only through the hooks in `deploy/maintain.py`, run as root with
`/opt/goodmorning/python/bin/python -B /opt/goodmorning/current/deploy/maintain.py <hook>`.
Change the hooks only through a PR and a deployment, never by hand on the server.

## Hooks

- `hold`: pauses the website and waits up to 20 minutes until no account has
  running work or pending input, using the same checks as deployment, then takes
  the work reservation and writes `/var/lib/goodmorning-maintenance/hold.json`.
  Exits 0 when held. Exits 75 without a hold if a hold already exists, the
  website is already paused (a deployment or incident), or an account stays
  busy; the website then resumes at once, and the server should update without
  restarting GoodMorning. Any other failure resumes the website and exits 1.
- `python`: only while held (exits 1 otherwise). Upgrades GoodMorning's Python
  patch version (`uv python upgrade 3.14`). Exits 10 if the version changed, so
  the server reboots; 0 if unchanged.
- `finish`: if a hold exists, waits for the gateway, account sockets and viewers
  (engines start on demand, so it never wakes them), releases the reservation,
  resumes the website and checks the public login page. Safe to repeat; does
  nothing without a hold. The server routine runs it unless it reboots; after
  any boot, `goodmorning-maintenance-boot.service` runs it if a hold exists.
  Deployments install and enable that unit.
- `status`: prints the hold, if any.

The hooks only ever lift their own pause (`by: daily maintenance`). A deployment
started while held stops at preflight because the website is paused: wait until
the routine finishes.

## Logs

- Hook output: the server routine's own log and
  `journalctl -u goodmorning-maintenance-boot`.
- A failed boot release leaves the unit failed: `systemctl --failed`.

## When something is wrong

- **The website stays paused and `status` shows a hold**: run
  `sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/deploy/maintain.py finish`.
  It waits for the services, releases the hold and resumes. Inspect the journal first if
  it already failed once.
- A rollback to a release from before these hooks reinstalls its own daily
  `goodmorning-maintenance.timer`, and that release has no hooks. Disable the
  timer until the next deployment removes it.

## Host

The host's configuration (port 443 SNI router, other sites, SiYuan, VPN, firewall,
SSH, zram) is versioned in the private `S-Sebb/SebOracle` repository; its README
describes the layout. What GoodMorning relies on:

- Port 443 belongs to the host's SNI router, so `nginx-goodmorning.conf` listens on
  `127.0.0.1:8443` with the PROXY protocol. Its site name must stay in the router's map.
- Memory: `goodmorning-accounts.slice` has a hard cap, at which the kernel kills only
  its largest process; systemd-oomd runs but is not used for it. Swap is zram only.

## Not covered

- GoodMorning releases and the engine: deployments only (`docs/server-deployment.md`).
- Node.js (`/opt/goodmorning/node`): pinned; upgrade deliberately.
- Ubuntu, snap, SiYuan and sing-box updates and reboots: the `SebOracle` routine.
- Certificates: certbot's own timer.
