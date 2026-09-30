# Suite desktop entry point

The desktop is now at [`../../../desktop/`](../../../desktop/), alongside both
applications. Use [suite setup and lifecycle](../../../docs/desktop.md) for install,
WSL setup, launch modes, ports, ownership, recovery and shutdown.

From the suite root run `python3 scripts/setup.py`; then from `desktop/` run
`npm start` or `npm run dev`. ChatTFT's backend and frontend stay within this
application. VOD Review and Wisps share one suite-local VOD runtime. Langfuse uses
port 15510 and CloudBeaver port 8979 with independent volumes and credentials.

## Database workspace (CloudBeaver)

From the suite root explicitly run
`docker compose -f desktop/cloudbeaver/compose.yaml up -d`. Open
`http://localhost:8979` or the desktop Database tab and configure authorized RDS
connections using the application's existing external settings. The workspace
starts fresh; original CloudBeaver connections and sessions are not copied.
