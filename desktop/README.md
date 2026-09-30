# tft-apps desktop

From the suite root run `python3 scripts/setup.py` once, then:

```sh
cd desktop
npm start
# Or, for ChatTFT frontend hot reload:
npm run dev
```

See [suite setup and lifecycle](../docs/desktop.md) for WSL setup, ports,
process ownership and troubleshooting. Python and React dependencies stay in
`tft-chat/` and `vod-review/`; this directory owns only the Electron shell.
