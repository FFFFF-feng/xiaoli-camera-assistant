"""启动器的路径、端口、后台启动、重复复用与失败清理测试，不打开真实浏览器。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("project_launch_apps", ROOT / "scripts/launch_apps.py")
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


@pytest.fixture
def services() -> tuple:
    return (
        launcher.Service("拍摄助手", "app.py", 8501, "assistant.log"),
        launcher.Service("知识工作台", "knowledge_app.py", 8502, "knowledge.log"),
    )


def test_cmd_entry_resolves_its_own_directory_and_preserves_environment() -> None:
    text = (ROOT / "启动项目.cmd").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in text
    assert "setlocal" in text and "PYTHONUTF8=1" in text
    assert text.index(".venv\\Scripts\\python.exe") < text.index("where python")
    assert '"%~dp0scripts\\launch_apps.py"' in text
    assert "pause" in text
    assert ".env" not in text and "pip install" not in text
    assert 'if not exist "%~dp0scripts\\launch_apps.py"' in text
    assert "instead of copying it alone" in text
    data = (ROOT / "启动项目.cmd").read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert "*.cmd text eol=crlf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_service_identity_requires_exact_absolute_project_entry(tmp_path: Path) -> None:
    script = tmp_path / "project with spaces 中文" / "app.py"
    prefix = '"D:\\Python\\python.exe" -m streamlit run '
    assert launcher.command_matches(prefix + f'"{script}" --server.port 8501', script)
    assert launcher.command_matches(prefix + f'"{str(script).upper()}"', script)
    assert not launcher.command_matches(prefix + "app.py", script)
    assert not launcher.command_matches(prefix + f'"{script}.bak"', script)
    assert not launcher.command_matches(f'python "{script}"', script)
    assert not launcher.command_matches(prefix + f'"{tmp_path / "other" / "app.py"}"', script)


def test_busy_foreign_port_is_skipped_without_stealing_other_app_port(
    services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "port_taken", lambda port: port == 8501)
    monkeypatch.setattr(launcher, "owned_service", lambda port, script: False)
    assert launcher.select_port(services[0], {8502}) == (8503, False)


def test_existing_healthy_project_service_is_reused(
    services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "port_taken", lambda port: True)
    monkeypatch.setattr(launcher, "owned_service", lambda port, script: True)
    monkeypatch.setattr(launcher, "healthy", lambda port: True)
    assert launcher.select_port(services[0], {8502}) == (8501, True)


def test_unhealthy_existing_process_is_not_reused(
    services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "port_taken", lambda port: port == 8501)
    monkeypatch.setattr(launcher, "owned_service", lambda port, script: True)
    monkeypatch.setattr(launcher, "healthy", lambda port: False)
    assert launcher.select_port(services[0], {8502}) == (8503, False)


def test_background_child_uses_absolute_paths_localhost_and_existing_configuration(
    tmp_path: Path, services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Mock(pid=1234)
    popen = Mock(return_value=process)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setenv("PYTHONPATH", "existing-python-path")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "managed")
    assert launcher.start_service(services[0], 8501, tmp_path) is process
    args, options = popen.call_args
    command = args[0]
    assert command[0] == sys.executable
    assert str(ROOT / "app.py") in command
    assert command[command.index("--server.address") + 1] == "127.0.0.1"
    assert "--server.headless=true" in command
    assert options["cwd"] == ROOT
    assert options["env"]["PYTHONPATH"].startswith(str(ROOT / "src"))
    assert options["env"]["KNOWLEDGE_RETRIEVAL_MODE"] == "managed"
    assert options["stdin"] == subprocess.DEVNULL
    if launcher.os.name == "nt":
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_success_opens_both_pages_only_after_services_are_ready(
    tmp_path: Path, services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = []
    processes = [Mock(pid=1001), Mock(pid=1002)]
    monkeypatch.setattr(launcher, "RUNTIME", tmp_path)
    monkeypatch.setattr(launcher, "select_port", lambda service, reserved: (service.port, False))
    monkeypatch.setattr(launcher, "start_service", lambda *args: processes.pop(0))
    monkeypatch.setattr(launcher, "wait_ready", lambda process, port, log: events.append(port))

    def open_browser(url: str, new: int) -> bool:
        assert events[:2] == [8501, 8502]
        assert new == 1
        events.append(url)
        return True

    monkeypatch.setattr(launcher.webbrowser, "open", open_browser)
    assert launcher.launch(services) == ["http://localhost:8501/", "http://localhost:8502/"]
    assert len(events) == 4


def test_repeated_launch_does_not_create_more_processes(
    tmp_path: Path, services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "RUNTIME", tmp_path)
    monkeypatch.setattr(launcher, "select_port", lambda service, reserved: (service.port, True))
    start = Mock()
    browser = Mock()
    monkeypatch.setattr(launcher, "start_service", start)
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    assert len(launcher.launch(services, no_browser=True)) == 2
    start.assert_not_called()
    browser.assert_not_called()


def test_partial_failure_only_cleans_up_new_processes(
    tmp_path: Path, services: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Mock(pid=2222)
    process.poll.return_value = None
    monkeypatch.setattr(launcher, "RUNTIME", tmp_path)
    monkeypatch.setattr(
        launcher, "select_port", lambda service, reserved: (service.port, service.port == 8501)
    )
    monkeypatch.setattr(launcher, "start_service", lambda *args: process)
    monkeypatch.setattr(
        launcher, "wait_ready", Mock(side_effect=launcher.LaunchError("测试启动失败"))
    )
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(services)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)
    browser.assert_not_called()


def test_windows_owner_query_checks_the_command_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if launcher.os.name != "nt":
        pytest.skip("Windows进程归属检查")
    script = tmp_path / "相机 项目" / "app.py"
    result = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps([f'python -m streamlit run "{script}"'], ensure_ascii=False), stderr="",
    )
    run = Mock(return_value=result)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.owned_service(8501, script)
    assert "8501" in run.call_args.args[0][-1]
    assert "OutputEncoding" in run.call_args.args[0][-1]
    assert run.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_dependency_failure_is_actionable_and_does_not_echo_internal_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launcher.importlib, "import_module", Mock(side_effect=ImportError("private-data"))
    )
    with pytest.raises(launcher.LaunchError) as error:
        launcher.check_runtime()
    assert "pip install -e ." in str(error.value)
    assert "private-data" not in str(error.value)


def test_check_mode_never_launches_services(monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock()
    monkeypatch.setattr(launcher, "check_runtime", lambda: None)
    monkeypatch.setattr(launcher, "launch", launch)
    assert launcher.main(["--check"]) == 0
    launch.assert_not_called()


def test_invalid_or_duplicate_ports_fail_before_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock()
    monkeypatch.setattr(launcher, "launch", launch)
    assert launcher.main(["--main-port", "8502", "--knowledge-port", "8502"]) == 1
    with pytest.raises(launcher.argparse.ArgumentTypeError):
        launcher.valid_port("65535")
    launch.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CMD与桌面快捷方式")
def test_forwarding_cmd_works_from_a_unicode_desktop_folder(tmp_path: Path) -> None:
    desktop = tmp_path / "桌面 有空格"
    desktop.mkdir()
    entry = desktop / "摄影启动项目.cmd"
    # CMD中的UTF-8中文路径必须搭配CRLF；LF曾使cmd.exe错误解析后续命令。
    content = (
        "@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n"
        f'call "{ROOT / "启动项目.cmd"}" %*\r\n'
        "exit /b %errorlevel%\r\n"
    )
    entry.write_bytes(content.encode("utf-8"))
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(entry), "--check"],
        cwd=desktop, capture_output=True, encoding="utf-8", errors="replace",
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "依赖检查通过" in result.stdout
    assert "can't open file" not in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CMD与桌面快捷方式")
def test_shortcut_points_to_original_and_does_not_overwrite_custom_settings(tmp_path: Path) -> None:
    create_script = ROOT / "scripts/create_desktop_shortcut.ps1"
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(create_script), "-DestinationDirectory", str(tmp_path),
    ]
    created = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert created.returncode == 0
    shortcuts = list(tmp_path.glob("*.lnk"))
    assert len(shortcuts) == 1
    original = shortcuts[0].read_bytes()
    repeated = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert repeated.returncode == 0 and shortcuts[0].read_bytes() == original

    # 临时目录中的快捷方式由本测试创建，不改动用户真实桌面。
    escaped_path = str(shortcuts[0]).replace("'", "''")
    inspect_script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut('{escaped_path}'); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "@{ Target=$link.TargetPath; Directory=$link.WorkingDirectory; "
        "Arguments=$link.Arguments } | ConvertTo-Json -Compress"
    )
    inspected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", inspect_script],
        capture_output=True, encoding="utf-8", timeout=15, check=False,
    )
    assert inspected.returncode == 0
    properties = json.loads(inspected.stdout)
    assert Path(properties["Target"]) == ROOT / "启动项目.cmd"
    assert Path(properties["Directory"]) == ROOT
    assert properties["Arguments"] == ""
    customize_script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut('{escaped_path}'); "
        "$link.Arguments = '--check'; $link.Save()"
    )
    customized = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", customize_script],
        capture_output=True, timeout=15, check=False,
    )
    assert customized.returncode == 0
    custom_bytes = shortcuts[0].read_bytes()
    rejected = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert rejected.returncode != 0 and shortcuts[0].read_bytes() == custom_bytes
