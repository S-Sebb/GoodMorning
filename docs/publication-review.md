# Pre-publication review

Reviewed on 12 October 2026, against commit `4db1236` and the README changes in this checkout.
This is a repository disclosure review, not an application security audit.

## Scan results

- Gitleaks 8.30.1 scanned all 39 commits reachable from local branches and remote-tracking
  refs, plus the working directory and commit metadata, with fully redacted output.
  A read-only remote check found only `main`, matching the reviewed commit, and no tags.
- A second scan of the 232 intended public files, including the new screenshots and
  documentation, found only the five test false positives described below.
- The five history findings are false positives: two avatar filenames and three
  synthetic account passwords in tests. The same five appear in the working tree.
- One real credential was detected in the ignored local `.env`. That file is not
  tracked and has no path in the reachable history. Keep it private; do not publish
  a raw directory archive or force-add ignored files.
- Tracked paths and historical object paths contain no credential files, private
  secretary runtime, or database files. Old `secretary` skill paths contain workflow
  instructions, not personal records.
- Additional text checks found no personal email in tracked file contents, owner-specific
  home/workspace paths, or private-key blocks. Existing raster assets have no EXIF
  entries or embedded metadata. README screenshots use isolated fictional records,
  a synthetic agent, and no external browser requests or model calls.
- Ignore rules now also cover `.env.*` variants and common private-key bundles.
  `.env.example` remains allowed and must contain placeholders only.

**No real secret was found in the scanned tracked source or reachable Git history.**
Automated scans cannot guarantee the absence of every kind of sensitive information.

## Publication decisions and remaining checks

1. **Commit email:** one historical author identity uses a personal email rather than
   GitHub's private `noreply` address. It will be public with the existing history.
   Changing future Git configuration does not remove it from earlier commits.
   The owner approved retaining it. This review did not rewrite commits, alter
   author configuration, or push anything.
2. **Deployment identifiers:** real hostnames, an SSH alias, production paths, and a
   machine-local deploy-helper path appear in the deployment runbook and templates.
   Hostnames also appear in runtime origin allowlists, public browser checks, and
   release notes. They are not authentication secrets, but they reveal infrastructure
   details. The owner approved keeping them public in `docs/server-deployment.md`,
   `deploy/`, `src/goodmorning/security/briefing_runtime.py`, and `tests/browser/`.
   Do not replace security allowlists with
   wildcards as a shortcut; changing runtime hosts requires a separate, verified migration.
3. **License:** the owner selected MIT, with `Copyright (c) 2026 S-Sebb` in the
   root `LICENSE`. Existing third-party license notices remain unchanged.
4. **Publication scope:** publish tracked Git files, not `.env`, `secretary/`, `.cache/`,
   `dist/`, private screenshot collections, runtime records, or local backups.
   Confirm GitHub-side branches, tags, releases, Actions artifacts, and any previous
   exposure separately; this review covers the refs and files available locally.

The existing history and live deployment settings were intentionally left unchanged.
