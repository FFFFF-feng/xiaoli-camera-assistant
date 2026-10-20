"""Build and launch the current local web project, without deploying anything."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".launcher"
HTTP = build_opener(ProxyHandler({}))
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_SEGMENTATION_WEIGHT_LIMIT = 128 * 1024 * 1024


class LaunchError(RuntimeError):
    pass


def check_runtime() -> str:
    if sys.version_info < (3, 11):  # noqa: UP036 - launcher can be invoked by an old Python
        raise LaunchError("需要 Python 3.11 或更新版本。")
    for module in ("uvicorn", "fastapi", "multipart", "httpx", "numpy", "cv2", "PIL", "pydantic", "dotenv", "yaml"):
        try:
            importlib.import_module(module)
        except (ImportError, OSError):
            raise LaunchError(f'缺少依赖 {module}，请执行：python -m pip install -e ".[mobile]"') from None
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not shutil.which("node"):
        raise LaunchError("未找到 Node.js/npm，请安装 Node.js 后重新启动。")
    if not (ROOT / "mobile/node_modules/vite").is_dir():
        raise LaunchError("前端依赖尚未安装，请执行：npm --prefix mobile ci")
    check_image_editor()
    check_segmentation()
    check_observation_coordinates()
    return npm


def check_observation_coordinates() -> None:
    """Pure unit-option check: no model call or access to credential vaults."""
    from dotenv import dotenv_values

    from camera_assistant.config import Settings

    environment = {key: value for key, value in dotenv_values(ROOT / '.env').items() if value is not None}
    environment.update(os.environ)
    try:
        Settings.observation_coordinate_option(environment)
    except (ValueError, TypeError, AttributeError):
        raise LaunchError('识别坐标单位配置无效：请使用 model_default、normalized_0_1 或 normalized_0_1000。') from None


def check_image_editor() -> None:
    from dotenv import dotenv_values

    from camera_assistant.image_edit_config import ImageEditSettings

    environment = {key: value for key, value in dotenv_values(ROOT / ".env").items()
                   if value is not None}
    environment.update(os.environ)
    try:
        ImageEditSettings.from_env(environment)
    except ValueError as error:
        raise LaunchError(f"可选图片编辑配置无效：{error}") from None


def _segmentation_weight_check(path, expected_sha256):
    if path is None:
        return "weights_missing", None
    try:
        before = path.stat()
        if not path.is_file():
            return "weights_missing", None
        if not 0 < before.st_size <= _SEGMENTATION_WEIGHT_LIMIT:
            return "weights_invalid", None
        digest = hashlib.sha256()
        remaining = _SEGMENTATION_WEIGHT_LIMIT
        with path.open("rb") as stream:
            while chunk := stream.read(min(1024 * 1024, remaining + 1)):
                if len(chunk) > remaining:
                    return "weights_invalid", None
                digest.update(chunk)
                remaining -= len(chunk)
        after = path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            return "weights_invalid", None
        actual_sha256 = digest.hexdigest()
        if expected_sha256 and actual_sha256 != expected_sha256:
            return "weights_invalid", actual_sha256
        return None, actual_sha256
    except OSError:
        return "weights_missing", None


def check_segmentation() -> dict:
    """Check configuration/presence only; never import Torch or load a model.

    Avoid Settings.from_env(), which may consult the provider credential vault.
    The demo Settings below validate the exact product segmentation parser.
    """
    from dotenv import dotenv_values

    from camera_assistant.config import Settings

    environment = {key: value for key, value in dotenv_values(ROOT / ".env").items()
                   if value is not None}
    environment.update(os.environ)
    try:
        options = Settings.segmentation_options(environment)
        if options["segmentation_device"] != "cpu":
            raise LaunchError("可选分割配置无效：device_unavailable；目前只验证 CPU。")
        config = Settings(
            demo_mode=True, api_key="", base_url="https://example.invalid", vision_model="",
            text_model="", timeout_seconds=5, max_image_mb=1, knowledge_dir=ROOT / "knowledge",
            **options,
        )
    except (ValueError, TypeError):
        raise LaunchError("可选分割配置无效：segmentation_configuration_invalid。") from None
    report = {"configured_backend": config.segmentation_backend,
              "device": "cpu", "code": "configuration_checked", "weights_sha256": None,
              "fallback_backend": None, "inference_proven": False}
    if config.segmentation_backend == "grabcut":
        return report
    code, digest = _segmentation_weight_check(config.segmentation_weights_path,
                                               config.segmentation_weights_sha256)
    report["weights_sha256"] = digest
    if code is None:
        try:
            if any(importlib.util.find_spec(name) is None
                   for name in ("torch", "torchvision", "timm", "mobile_sam")):
                code = "backend_unavailable"
        except (ImportError, ValueError, OSError):
            code = "backend_unavailable"
    if code is not None:
        report["code"] = code
        if not config.segmentation_fallback:
            raise LaunchError(f"可选分割预检失败：{code}；fallback=disabled。") from None
        report["fallback_backend"] = "grabcut"
        print(f"可选分割预检：requested=mobile_sam code={code} fallback=grabcut；"
              "实际分析仍会记录后端和降级原因。", flush=True)
    else:
        print("可选分割配置预检通过；仅发现依赖并核对本地权重，尚未执行模型推理。", flush=True)
    return report


def local_environment(port: int, demo: bool = False) -> tuple[dict[str, str], str]:
    from dotenv import dotenv_values

    environment = os.environ.copy()
    for key, value in dotenv_values(ROOT / ".env").items():
        if value is not None:
            environment.setdefault(key, value)
    # Reuse the user's existing local cloud configuration; never print or edit it.
    for key, value in dotenv_values(ROOT / ".env.zhipu-deploy").items():
        if key == "CAMERA_AI_API_KEY" and value:
            if (
                (environment.get("CAMERA_AI_PRESET") or "glm-dino").strip().lower() != "glm-dino"
                or urlsplit(environment.get("CAMERA_AI_BASE_URL") or "https://open.bigmodel.cn/")
                .hostname != "open.bigmodel.cn"
            ):
                continue
            environment.setdefault(key, value)
    cloud = bool(environment.get("CAMERA_AI_API_KEY", "").strip()) and not demo
    if environment.get("APP_DEMO_MODE", "").lower() in {"true", "1", "yes"}:
        cloud = False
    environment["APP_DEMO_MODE"] = "false" if cloud else "true"
    environment["WEB_ORIGIN"] = f"http://127.0.0.1:{port}"
    environment["WEB_TRUSTED_PROXY_IP"] = ""
    environment.setdefault("CAMERA_AI_PRESET", "glm-dino" if cloud else "custom")
    # Windows registry proxies are inherited by HTTPX even without *_PROXY env vars.
    # Local Zhipu calls work directly; retain explicit user choices and other providers.
    provider_host = urlsplit(environment.get("CAMERA_AI_BASE_URL") or (
        "https://open.bigmodel.cn" if environment["CAMERA_AI_PRESET"] == "glm-dino" else ""
    )).hostname
    if cloud and provider_host == "open.bigmodel.cn":
        environment.setdefault("CAMERA_AI_TRUST_ENV", "false")
    environment.setdefault("CAMERA_AI_DETECTOR_ENABLED", "false")
    environment.setdefault("CAMERA_AI_COMPOSITION_ENABLED", "true")
    environment.setdefault("CAMERA_AI_MAX_OUTPUT_TOKENS", "8192")
    environment.setdefault("CAMERA_AI_TIMEOUT_SECONDS", "120")
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    RUNTIME.mkdir(exist_ok=True)
    secret_file = RUNTIME / "web-local-session.secret"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="ascii")
        secret_file.chmod(0o600)
    environment["WEB_SESSION_SECRET"] = secret_file.read_text(encoding="ascii").strip()
    return environment, "cloud" if cloud else "demo"


def command_matches(command: str, port: int) -> bool:
    entry = re.escape((ROOT / "scripts/start_web.py").resolve().as_posix().casefold())
    command = command.replace("\\", "/").casefold()
    python = r'(?:"[^"\r\n]*/pythonw?\.exe"|[^\s"]*pythonw?\.exe)'
    return bool(re.match(python + r'\s+(?:-u\s+)?"?' + entry + r'"?(?=\s|$)', command)
                and re.search(r"(?:^|\s)--port\s+" + str(port) + r"(?=\s|$)", command))


def owned_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    script = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
        f"$webOwners=@(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess -Unique);"
        "$webProcesses=@($webOwners | ForEach-Object { Get-CimInstance Win32_Process "
        "-Filter ('ProcessId = '+$_) | Select-Object ProcessId,CommandLine });"
        "ConvertTo-Json -InputObject $webProcesses -Compress"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, encoding="utf-8", errors="replace",
                                timeout=12, creationflags=NO_WINDOW, check=False)
        processes = json.loads(result.stdout) if result.returncode == 0 else []
        if isinstance(processes, dict):
            processes = [processes]
        for process in processes:
            if command_matches(process.get("CommandLine") or "", port):
                return int(process["ProcessId"])
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        pass
    return None


def port_taken(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def select_port(preferred: int) -> tuple[int, int | None]:
    for port in range(preferred, min(preferred + 20, 65536)):
        if not port_taken(port):
            return port, None
        pid = owned_pid(port)
        if pid:
            return port, pid
    raise LaunchError("附近端口均被占用，请用 --port 指定其他端口。")


def build_frontend(npm: str) -> bytes:
    print("正在构建当前项目的最新网页…", flush=True)
    result = subprocess.run([npm, "run", "build"], cwd=ROOT / "mobile", check=False)
    if result.returncode:
        raise LaunchError("前端构建失败，未启动旧构建；请查看上方错误。")
    return (ROOT / "mobile/dist/index.html").read_bytes()


def ready(port: int, index: bytes, mode: str) -> bool:
    try:
        with HTTP.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.load(response)
        with HTTP.open(f"http://127.0.0.1:{port}/", timeout=1) as response:
            current = response.read()
        return (health.get("service") == "xiaoli-mobile-api"
                and health.get("analysis_mode") == mode and current == index)
    except (OSError, ValueError):
        return False


def launch(npm: str, preferred: int, *, demo: bool = False, no_browser: bool = False,
           knowledge_port: int = 8503) -> str:
    # Share the launch lock with the legacy entry point, but never stop legacy/unknown services.
    sys.path.insert(0, str(ROOT / "scripts"))
    from launch_apps import LaunchError as WorkbenchLaunchError
    from launch_apps import ensure_knowledge_workbench, launch_lock

    with launch_lock(RUNTIME):
        index = build_frontend(npm)
        port, previous = select_port(preferred)
        environment, mode = local_environment(port, demo)
        try:
            knowledge_url = ensure_knowledge_workbench(knowledge_port, {port})
        except WorkbenchLaunchError as error:
            raise LaunchError(f"知识库工作台启动失败：{error}") from None
        environment["WEB_KNOWLEDGE_WORKBENCH_URL"] = knowledge_url
        if previous:
            if owned_pid(port) != previous:
                raise LaunchError("端口归属已变化，请重新启动；未关闭其他程序。")
            os.kill(previous, signal.SIGTERM)
            deadline = time.monotonic() + 8
            while port_taken(port) and time.monotonic() < deadline:
                time.sleep(.1)
            if port_taken(port):
                raise LaunchError("本项目旧进程尚未退出，请稍后重试。")
        with (RUNTIME / "web.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts/start_web.py"),
                                        "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        deadline = time.monotonic() + 50
        while not ready(port, index, mode):
            if process.poll() is not None or time.monotonic() > deadline:
                if process.poll() is None:
                    process.terminate()
                raise LaunchError(f"网页启动失败，请查看 {RUNTIME / 'web.log'}")
            time.sleep(.25)
        url = f"http://127.0.0.1:{port}/?v=local-{time.time_ns()}"
        (RUNTIME / "web-service.json").write_text(json.dumps({"pid": process.pid, "port": port,
            "url": url, "project": str(ROOT), "mode": mode, "knowledge_url": knowledge_url},
            ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"当前项目：{ROOT}\n新版网页已启动（{'云模型' if mode == 'cloud' else '规则演示'}）：{url}", flush=True)
    print("本次仅在本机运行，没有上传或更新服务器。日志：.launcher/web.log", flush=True)
    if mode == "cloud":
        print("使用本机已有模型配置，密钥不会显示。", flush=True)
    if not no_browser:
        webbrowser.open(url, new=1)
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建并启动当前版本的小栗网页")
    parser.add_argument("--port", "--main-port", type=int, default=8080)
    parser.add_argument("--knowledge-port", type=int, default=8503, help="知识库导入工作台首选端口")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--demo", action="store_true", help="仅运行规则演示，不调用云模型")
    args = parser.parse_args(argv)
    try:
        if not all(1024 <= port <= 65515 for port in (args.port, args.knowledge_port)):
            raise LaunchError("端口必须在1024到65515之间。")
        npm = check_runtime()
        if args.check:
            print("新版网页运行依赖检查通过。")
            return 0
        launch(npm, args.port, demo=args.demo, no_browser=args.no_browser,
               knowledge_port=args.knowledge_port)
        return 0
    except (LaunchError, OSError, RuntimeError) as error:
        print(f"启动失败：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
