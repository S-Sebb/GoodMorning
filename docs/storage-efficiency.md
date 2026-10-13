# Storage efficiency without history deletion

Chat display bytes, model tokens and disk storage are separate measurements.
Native tool image results contain inline base64, which is about one third larger
than the image bytes. A large image-heavy session is not the same as that many
bytes of prose. History polling is a local read and does not itself make a model
call. Native estimated usage cost is not necessarily the provider's invoice.

## Read-only inventory

```sh
python scripts/goodmorning.py sessions --secretary-dir RUNTIME --storage
```

Use `--cache-dir CACHE` for a separate local cache. Hosted account layouts also
report engine data, OpenChamber state and private temporary files. Counts are
disjoint: uploads and avatar previews are not counted again as records. Repeated
samples reveal growth; nothing is initialized, archived or deleted. The command
uses file metadata only, omits filenames and never contacts an engine or model.
Symlinks are not followed. A bounded, changing or unreadable inventory reports `complete: false`.
Filesystem allocation is not a bill; encrypted-filesystem overhead and backing
volume accounting may differ. Native `.so`/`.node` files can be a fixed startup
cost rather than growing conversation data. Do not delete them to make a report
look smaller.

## Compact avatar inspection

Avatar reference images and repeated visual checks need not embed full-size PNGs
in every new native tool record. Create a private inspection copy:

```sh
python scripts/goodmorning.py avatar-preview --secretary-dir RUNTIME \
  --source assets/web/desk-secretary.png --source PRIVATE_AVATAR.png
```

Read the returned `preview` paths with the normal image read tool. Only select
references needed for the requested avatar task. The hosted Python environment
is `/opt/goodmorning/python/bin/python`; local use needs Pillow.

- Original files, current avatar settings and existing histories stay unchanged.
- The preview fits within 512 × 512 pixels, keeps aspect ratio and alpha, and is
  encoded as lossless WebP. Lossless describes the encoding, not the resizing:
  this is an inspection thumbnail, not a pixel-identical full-resolution copy.
- Full-quality originals remain the source for publishing and precise detail.
  Do not use this helper for document OCR, scientific images or arbitrary uploads.
- Previews live under the selected existing runtime in `avatar-previews/`, with
  private permissions. Content-identical inputs reuse a file; different revisions
  keep separate previews. Neither unexpected files nor earlier previews are replaced.
- Total storage includes both the preview file and the engine's inline image.
  Smaller inspection images reduce future payload growth, not old stored records.

## Retention boundary

There is no automatic deletion, archival, spend cap, model change or context-policy
change in these optimizations. Profiles, tasks, calendar records, saved briefings,
uploaded originals and full old engine histories remain protected. Existing
maintenance commands require their own owner authorization; do not run pruning
or archival merely because the size report is large.

Native context compaction can shorten future model input while retaining original
messages on disk. Moving chats out of the browser's active registry also does not
delete their engine history. Genuine history retention needs a separate policy
and verified encrypted export/restoration before any live-data removal.
