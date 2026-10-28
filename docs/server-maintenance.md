# Server maintenance

`SebOracle` updates itself every day at 05:00 China time
(`goodmorning-maintenance.timer`), finishing within an hour. The code is
`deploy/maintain.py`; deployments install and enable its units. Change it only
through a PR and a deployment, never by hand on the server.

## What a run does

1. Skips the day if the website is already paused (a deployment or incident)
   or an earlier run left a hold.
2. Pauses the website and waits up to 20 minutes until no account has running
   work or pending input, using the same checks as deployment, then takes the
   work reservation.
3. Installs Ubuntu and Docker updates (`apt-get full-upgrade`, `autoremove`).
   needrestart only reports; the routine decides restarts. It disables
   `apt-daily-upgrade.timer` so unattended-upgrades never restarts services.
4. Upgrades GoodMorning's Python patch version (`uv python upgrade 3.14`).
5. Updates SiYuan only if `b3log/siyuan:latest` has a new image, using
   `/opt/siyuan/update-siyuan.sh` (backup, health check, self-rollback). Keeps
   the last 3 backups and rollback images.
6. Reboots only if Ubuntu asks for one, a newer kernel is installed, a service
   uses replaced libraries, or Python changed. After the boot,
   `goodmorning-maintenance-boot.service` waits for the account sockets and viewers
   (engines start on demand, so it never wakes them),
   releases the reservation, resumes the website and checks the public login page.
   Otherwise the run releases and resumes at once.

If an account is still busy after 20 minutes, the website resumes immediately
and the run still installs packages and SiYuan, but without the Python upgrade
or any reboot (`restartDeferred` in the report). Nobody's work is interrupted;
the next idle morning applies the restart. If the apt step fails, the run never
reboots.

The routine only ever lifts its own pause (`by: daily maintenance`). A
deployment started during a run stops at preflight because the website is
paused: wait until the run finishes.

## Logs

- Report: `sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/deploy/maintain.py status [DAYS]`
  summarizes recent runs (result, minutes, seconds paused, step timings and errors,
  reboot reasons, package count) and the next run time.
- Full report: `/var/log/goodmorning-maintenance/<date>.json` (root only, last 90 days),
  including every upgraded package.
- Step-by-step output, including apt and Docker: `journalctl -u goodmorning-maintenance -u goodmorning-maintenance-boot`.
  apt keeps its own history in `/var/log/apt/history.log`.
- A failed step leaves the unit failed: `systemctl --failed`.

## When something is wrong

- **The website stays paused and `status` shows `unfinishedHold`**: run
  `sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/deploy/maintain.py finish`.
  It waits for the services, releases the hold and resumes. Inspect the journal first if
  it already failed once.
- **Run by hand** (same rules, website paused for the run): `sudo systemctl start goodmorning-maintenance.service`.
  Only with the owner's agreement, since it may reboot the server.
- A rollback to a release older than this routine leaves its units installed but
  failing daily until the next deployment; disable the timer if that matters.

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
- The SoftEther VPN client, nginx and the static sites: apt updates the packages.
- Certificates: certbot's own timer.
