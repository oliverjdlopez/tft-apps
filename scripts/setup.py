"""Install locked dependencies into each application's independent environment."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Install suite dependencies from any working directory without starting apps."""
    for command in ("uv", "node", "npm"):
        if not shutil.which(command):
            raise SystemExit(f"Install {command} before running setup")
    version = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
    major, minor, *_ = map(int, version.split("."))
    if major != 22 or minor < 12:
        raise SystemExit("Use Node 22.12 or later within Node 22")
    for app, extras in [("tft-chat", ["evals", "compositions", "transcription"]),
                        ("vod-review", ["transcription"])]:
        args = ["uv", "sync", "--locked", "--link-mode", "copy"]
        for extra in extras:
            args.extend(["--extra", extra])
        subprocess.run(args, cwd=ROOT / app, check=True)
    for directory in ("tft-chat/app/frontend", "vod-review/frontend", "desktop"):
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=ROOT / directory, check=True)
    print("Dependencies ready. Run npm start or npm run dev from desktop/.")


if __name__ == "__main__":
    main()
