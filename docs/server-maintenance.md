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

## Host settings

Set by hand when the services moved to `SebOracle` on 2026-10-28; keep them unless
the owner agrees.

- Memory: zram swap only (`/etc/systemd/zram-generator.conf`: zstd, half of RAM,
  priority 100; no swap file) with `/etc/sysctl.d/90-goodmorning-zram.conf`
  (swappiness 100, page-cluster 0).
  `goodmorning-accounts.slice` has a hard cap, at which the kernel kills only its largest
  process; systemd-oomd runs but is not used for it. SiYuan's compose file caps it at 512 MB with no swap.
- SSH: key login only (`/etc/ssh/sshd_config.d/10-hardening.conf`: no passwords or
  keyboard-interactive, no root login, 3 tries). fail2ban bans repeated failures
  (`/etc/fail2ban/jail.d/goodmorning-sshd.local`).
- Firewall: `/etc/iptables/rules.v4` and `rules.v6` accept only TCP 22, 80 and 443,
  matching the Oracle Cloud security list. Restoring them by hand drops Docker's
  chains; restart Docker afterwards. Docker (`/etc/docker/daemon.json`) uses the
  `local` log driver, live restore and no-new-privileges; containers publish only
  on loopback.

## Host layout

- Port 443: `/etc/nginx/stream.d/sni-router.conf` routes by TLS server name. The
  website names go to nginx's HTTPS servers on `127.0.0.1:8443` with the PROXY
  protocol; everything else goes to the owner's sing-box proxy on `127.0.0.1:8444`
  (through `127.0.0.1:8445`, which strips the PROXY header). Every HTTPS site
  includes `snippets/sni-backend.conf` or the same lines; a new site name must
  also be added to the router's map. Unknown names on port 80 get no answer.
- Sites: love765.me (`/var/www/love765.me`, `/api/` to the Taiko server over the
  VPN), dou.love765.me (NekoBeads, deployed from its own repository to
  `/home/ubuntu/Repos/NekoBeads`), and SiYuan at seb.love765.me and yuka.love765.me.
  Shared headers: `snippets/security-headers.conf`.
- SiYuan: `/opt/siyuan` Compose project, data in `/srv/siyuan` owned by the
  `siyuan` system user, access codes in root-only `siyuan-*.env` files.
- VPN: Ubuntu's `softether-vpnclient` package (config in `/var/lib/softether`);
  a drop-in gives `vpn_myvpn` the address 169.254.222.11/16.
- Certificates: certbot's webroot renewals, `/var/www/html` for this host's names
  and `/var/www/nyandou-acme` for dou.love765.me.

## Not covered

- GoodMorning releases and the engine: deployments only (`docs/server-deployment.md`).
- Node.js (`/opt/goodmorning/node`): pinned; upgrade deliberately.
- Ubuntu, snap, SiYuan and sing-box updates and reboots: the `SebOracle` routine.
- Certificates: certbot's own timer.
