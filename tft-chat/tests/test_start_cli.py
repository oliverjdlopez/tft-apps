from __future__ import annotations

from unittest.mock import patch

from app.backend.api import __main__ as api_main
from scripts import start


def test_start_parser_accepts_reload_flag() -> None:
    args = start._build_parser().parse_args(["--reload"])

    assert args.reload is True


def test_start_service_passes_reload_argument() -> None:
    service = start.SERVICES[0]

    with patch("scripts.start.subprocess.Popen") as popen_mock, patch(
        "scripts.start.threading.Thread"
    ) as thread_mock:
        start._start_service(service, reload=True)

    command = popen_mock.call_args.args[0]
    assert command[-1] == "--reload"
    thread_mock.assert_called_once()


def test_api_parser_accepts_reload_flag() -> None:
    args = api_main._build_parser().parse_args(["--reload"])

    assert args.reload is True


def test_api_main_passes_reload_to_uvicorn() -> None:
    with patch("sys.argv", ["python", "--reload"]), patch(
        "app.backend.api.__main__.load_config"
    ) as load_config_mock, patch("app.backend.api.__main__.uvicorn.run") as run_mock:
        load_config_mock.return_value.chat.ui_host = "127.0.0.1"
        load_config_mock.return_value.chat.ui_port = 8300

        api_main.main()

    run_mock.assert_called_once_with(
        "api.app:app",
        host="127.0.0.1",
        port=8300,
        reload=True,
    )
