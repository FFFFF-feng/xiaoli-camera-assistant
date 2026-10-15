"""双击CMD入口的后台启动器；不安装依赖、不改.env、不执行知识导入。"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".launcher"
DEPENDENCIES = ("streamlit", "httpx", "numpy", "PIL", "pydantic", "dotenv", "yaml")
HTTP = build_opener(ProxyHandler({}))  # 本地健康检查不经过用户代理。


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    filename: str
    port: int
    log_name: str


def check_runtime() -> None:
    # 启动器本身可能由用户机器上的旧Python调用，需要显式给出升级提示。
    if sys.version_info < (3, 11):  # noqa: UP036
        raise LaunchError("需要 Python 3.11 或更新版本，请检查虚拟环境。")
    for module in DEPENDENCIES:
        try:
            importlib.import_module(module)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise LaunchError(
                f"依赖 {module} 无法加载（{type(error).__name__}）。\n"
                f'请使用当前 Python 安装："{sys.executable}" -m pip install -e .'
            ) from None
    for filename in ("app.py", "knowledge_app.py"):
        if not (ROOT / filename).is_file():
            raise LaunchError(f"项目入口 {filename} 不存在，请保留完整项目目录。")


@contextmanager
def launch_lock(runtime: Path):
    """只锁住启动阶段，避免同时双击产生重复进程；崩溃后系统释放锁。"""
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "startup.lock").open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LaunchError("另一个启动器正在启动服务，请稍等后再试。") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def healthy(port: int) -> bool:
    try:
        with HTTP.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read(32).strip() == b"ok"
    except (OSError, URLError):
        return False


def command_matches(command: str, script: Path) -> bool:
    """只复用含本项目绝对入口路径的Streamlit，不猜测相对路径的工作目录。"""
    normalized = command.replace("\\", "/").casefold()
    entry = re.escape(script.resolve().as_posix().casefold())
    return bool(
        re.search(r'\bstreamlit(?:\.exe)?"?\s+run\s+', normalized)
        and re.search(r'(?<!\S)"?' + entry + r'"?(?=\s|$)', normalized)
    )


def owned_service(port: int, script: Path) -> bool:
    if os.name != "nt":
        return False
    # 仅查询这个监听端口的拥有进程；不打印命令行，不终止未知进程。
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        f"$owners = @(Get-NetTCPConnection -State Listen -LocalPort {int(port)} "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)\n"
        "$lines = @($owners | ForEach-Object { "
        "(Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $_)).CommandLine })\n"
        "ConvertTo-Json -InputObject $lines -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        lines = json.loads(result.stdout) if result.returncode == 0 else []
        if isinstance(lines, str):
            lines = [lines]
        return isinstance(lines, list) and any(
            isinstance(line, str) and command_matches(line, script) for line in lines
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def select_port(service: Service, reserved: set[int]) -> tuple[int, bool]:
    script = ROOT / service.filename
    for port in range(service.port, service.port + 20):
        if port in reserved:
            continue
        if not port_taken(port):
            return port, False
        if owned_service(port, script) and healthy(port):
            return port, True
    raise LaunchError(f"{service.name}没有找到空闲端口，请检查本地服务。")


def start_service(service: Service, port: int, runtime: Path) -> subprocess.Popen:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    with (runtime / service.log_name).open("ab") as log:
        return subprocess.Popen(
            [
                sys.executable, "-u", "-m", "streamlit", "run", str(ROOT / service.filename),
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless=true", "--browser.gatherUsageStats=false",
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )


def wait_ready(process: subprocess.Popen, port: int, log: Path, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LaunchError(f"服务启动后退出，请查看日志：{log}")
        if healthy(port):
            return
        time.sleep(0.25)
    raise LaunchError(f"服务启动超时，请查看日志：{log}")


def launch(services: tuple[Service, ...], *, no_browser: bool = False) -> list[str]:
    created: list[subprocess.Popen] = []
    urls: list[str] = []
    with launch_lock(RUNTIME):
        preferred = {service.port for service in services}
        assigned: set[int] = set()
        try:
            for service in services:
                reserved = assigned | (preferred - {service.port})
                port, reused = select_port(service, reserved)
                assigned.add(port)
                if reused:
                    print(f"复用已运行的{service.name}。", flush=True)
                else:
                    print(f"正在启动{service.name}（端口 {port}）…", flush=True)
                    process = start_service(service, port, RUNTIME)
                    created.append(process)
                    wait_ready(process, port, RUNTIME / service.log_name)
                    print(f"后台服务就绪，进程PID：{process.pid}", flush=True)
                url = f"http://localhost:{port}/"
                urls.append(url)
                print(f"{service.name}：{url}", flush=True)
        except BaseException:
            # 只清理本轮新建的进程；不会关闭复用服务或其他占用端口的程序。
            for process in created:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            raise
    if not no_browser:
        for url in urls:
            try:
                opened = webbrowser.open(url, new=1)
            except webbrowser.Error:
                opened = False
            if not opened:
                print(f"未能自动打开浏览器，请手动访问：{url}", flush=True)
    return urls


def valid_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65515:
        raise argparse.ArgumentTypeError("端口必须在1024到65515之间。")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动摄影助手与知识库导入页面")
    parser.add_argument("--no-browser", action="store_true", help="仅启动服务，不打开浏览器")
    parser.add_argument("--check", action="store_true", help="仅检查依赖，不启动服务")
    parser.add_argument("--main-port", type=valid_port, default=8501)
    parser.add_argument("--knowledge-port", type=valid_port, default=8502)
    args = parser.parse_args(argv)
    try:
        if args.main_port == args.knowledge_port:
            raise LaunchError("两个页面不能使用同一个首选端口。")
        print(f"当前Python：{sys.executable}", flush=True)
        check_runtime()
        if args.check:
            print("依赖检查通过，可以双击启动项目.cmd。", flush=True)
            return 0
        launch(
            (
                Service("拍摄助手", "app.py", args.main_port, "assistant.log"),
                Service("知识库导入工作台", "knowledge_app.py", args.knowledge_port, "knowledge.log"),
            ),
            no_browser=args.no_browser,
        )
        print("两个页面已就绪。关闭浏览器不会停止后台服务，再次启动会尝试复用。", flush=True)
        return 0
    except (LaunchError, OSError) as error:
        print(f"启动失败：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
