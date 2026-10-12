# Marked

The unmodified `lib/marked.umd.js` from Marked 18.1.1 is bundled as
`assets/web/marked.js`. Chat uses its lexer only; our renderer builds an allowlisted
DOM rather than inserting Marked's HTML output. No CDN requests are made.

- Source: https://registry.npmjs.org/marked/-/marked-18.1.1.tgz
- Upstream: https://github.com/markedjs/marked
- License: MIT; retained in `LICENSE` alongside the original asset header.
- Package SHA-512 (base64): `zEGgrtUG8crk+TrMacJSVABU4DYDDkS8uqgU3ohrn/2fW9C2AEfUrO3m6IhpIpQpl7YcVpiXXC9cSMWDANT3dg==`
- Asset SHA-256: `b82b9334406d8bdd16b6236c08de1cb65b2a859873ca9503d9cc0b292ca3c12a`
- License SHA-256: `8e3a3f82f59a60958f56ca08f445647c32a4733dc7ca6c2c46f6eb898471ab9c`

Verify hashes, review token contracts, and run the chat browser/security checks
before upgrading.
