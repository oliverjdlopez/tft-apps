from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from backend import start


def test_main_starts_frontend_and_forwards_backend_arguments() -> None:
    frontend = MagicMock()
    backend = MagicMock()
    frontend.poll.side_effect = [None, 0, 0, 0]
    frontend.returncode = 0
    backend.poll.return_value = None
    backend.returncode = None

    with (
        patch("backend.start.subprocess.Popen", side_effect=[frontend, backend]) as popen,
        patch("backend.start.sys.argv", ["vod-review-start", "--reload", "--port", "9000"]),
        patch("backend.start.time.sleep"),
    ):
        exit_code = start.main()

    assert popen.call_args_list == [
        call(["npm", "run", "dev"], cwd=start.PROJECT_ROOT / "frontend"),
        call(
            [start.sys.executable, "-m", "backend", "--reload", "--port", "9000"],
            cwd=start.PROJECT_ROOT,
        ),
    ]
    assert exit_code == 0
    backend.terminate.assert_called_once_with()
