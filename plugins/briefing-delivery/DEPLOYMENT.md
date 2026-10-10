# Deploy the briefing cards plugin

No build, npm install, OpenChamber patch or Android APK change is required.
Global installation is recommended for ordinary OpenChamber briefing chats.

## Requirements

- OpenCode V2; tested with SDK 2.0.11 and live OpenCode 2.0.25.
- A `python` command with Pillow and WebP support:
  `python -c "from PIL import features; assert features.check('webp')"`.
- DejaVu Sans, or the preferred installed Inter/TeX Gyre fonts. Chinese text
  requires `~/.local/share/fonts/noto-cjk/NotoSansSC-Regular.ttf`.
- The GoodMorning skill and an already saved briefing in
  `~/.local/share/GoodMorning/secretary/daily/` (or `SECRETARY_DIR`).

## Install for normal OpenChamber chats

Project-only installation does **not** cover OpenChamber's separate chat folders.
To use cards for `/gm` and `/gn` anywhere on this device, copy the package globally:

```sh
mkdir -p ~/.config/opencode/plugins
cp -R plugins/briefing-delivery ~/.config/opencode/plugins/
```

Also update the installed GoodMorning workflow docs. With the tool available,
image delivery is the default; an explicit text-only request overrides it.
Verify the plugin in an ordinary chat directory, not only the checkout.

## Copy to another project

From this checkout, with `PROJECT` set to the destination's absolute path:

```sh
mkdir -p "$PROJECT/.opencode/plugins"
cp -R plugins/briefing-delivery "$PROJECT/.opencode/plugins/"
```

Use a new destination, or inspect and back up an existing installation first.
Copy the entire plugin folder; `index.js` supplies the discovered entry point.
Do not install both global and project copies: OpenCode rejects duplicate plugin
IDs. Keep the global copy for normal chats; remove an old project loader only
after verifying that the global copy is active and existing receipts still work.

## Optional archive

```sh
mkdir -p dist
npm pack ./plugins/briefing-delivery --pack-destination dist
```

This creates `dist/goodmorning-briefing-delivery-0.1.1.tgz` without installing
dependencies or publishing anything. To deploy, extract its `package/` contents
into `.opencode/plugins/briefing-delivery/`. The archive contains only plugin
code and documentation—never briefing images, personal records or credentials.

## Verify and update

Open a session in the destination project. After saving text, call
`briefing_cards` with its profile-local date and `kind: "gm"` or `"gn"`, then put
the returned marker once in the final reply. Check enlarged cards on both clients.
Use `opencode plugin list` against the **same server OpenChamber uses** (pass
`--server URL` when different). The plugin ID is `goodmorning.briefing-delivery`.

Loader/config changes reload automatically. Implementation-only changes may
need a project reload. Keep the plugin and its durable ownership receipts while
image-bearing history exists; disabling it removes model-context filtering.
For transport limits and diagnostic checks, see the
[plugin reference](README.md).
