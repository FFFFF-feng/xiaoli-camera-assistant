"""Create private deployment settings without writing secrets to console."""
from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="Domain only, without https:// or a path")
    args = parser.parse_args()
    domain = args.domain.strip().lower()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        parser.error("请填写真实域名，例如 photo.example.com；不要包含路径或协议。")
    path = ROOT / "deploy/.env"
    if path.exists():
        parser.error("deploy/.env 已存在；请手工编辑已有配置，不会覆盖密钥。")
    content = (ROOT / "deploy/production.env.example").read_text(encoding="utf-8")
    content = content.replace("photo.example.com", domain)
    content = content.replace("replace-with-at-least-32-random-characters", secrets.token_urlsafe(48))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    path.chmod(0o600)
    print("已生成 deploy/.env 和随机会话签名密钥；请在本机配置模型密钥，不要提交 Git。")


if __name__ == "__main__":
    main()
