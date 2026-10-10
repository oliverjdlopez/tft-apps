# tft-apps

One desktop entry point for ChatTFT, Compositions, Rolldown, Flowchart, VOD Review,
Media, Langfuse and CloudBeaver. The two applications retain separate Docker images, Python processes, dependency locks, tests and frontend layouts.
Electron stays native; media, saved state and model caches remain local mounts.

```sh
cd ~/tft-apps
node scripts/setup.mjs
cd desktop
npm start
# Frontend hot reload inside Docker:
npm run dev
```

Prerequisites: Node 22.12+ within Node 22, Docker Engine and Compose.
GPU VOD processing also needs NVIDIA container access; set `TFT_DOCKER_GPU=0`
for CPU operation. Python application environments are installed in images. WSL uses native Windows Node and Electron; after dependency setup,
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
the suite root with `node desktop/docker.mjs langfuse-up`.
Backend CLI commands remain available within each application for troubleshooting
and tests. See [container lifecycle and rebuilds](docs/docker-desktop.md).
