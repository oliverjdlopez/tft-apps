# tft-apps

One desktop entry point for ChatTFT, Compositions, Rolldown, Flowchart, VOD Review,
Wisps, Langfuse and CloudBeaver. The two applications retain their own Python
processes, dependency locks, tests and frontend layouts.

```sh
cd ~/tft-apps
python3 scripts/setup.py
cd desktop
npm start
# ChatTFT frontend hot reload:
npm run dev
```

Prerequisites: Python 3.13+, uv, Node 22.12+ within Node 22, Docker Compose for
Langfuse. WSL uses native Windows Node and Electron; after dependency setup,
run `npm run setup:wsl` once from `desktop/`.

[Desktop setup and lifecycle](docs/desktop.md) ·
[Migration and audit](docs/migration.md) ·
[ChatTFT documentation](tft-chat/docs/README.md) ·
[VOD application guide](vod-review/README.md)

CloudBeaver starts explicitly:

```sh
docker compose -f desktop/cloudbeaver/compose.yaml up -d
```

Langfuse starts through the desktop launcher or, for troubleshooting, from
`tft-chat/` with `uv run --locked --extra evals python -m evals up --no-browser`.
Backend CLI commands remain available within each application for troubleshooting
and tests. This repository has fresh history on `dev`; nothing is pushed.
