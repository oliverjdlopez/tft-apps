# ChatTFT desktop

Source-launched Electron wrapper for the existing ChatTFT web application.
It starts the checkout's Python backend automatically and stops its services
when the desktop application quits.

See [desktop setup and operation](../docs/apps/desktop.md) for prerequisites,
Windows/macOS instructions, launch options, troubleshooting, and validation.

After installing the documented prerequisites, run from this directory:

```sh
npm start
# Or use frontend hot reload:
npm run dev
```

For an existing WSL checkout, run `npm run setup:wsl` once, then `npm start` or
`npm run dev` from this directory in WSL. Windows needs Node 22 with npm; Python
and frontend dependencies stay in WSL. See the linked guide for setup and
`--windows-node` / `--python` overrides.
