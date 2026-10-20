"""Printable recording notes remain self-contained and escape source markup."""
import importlib.util
from pathlib import Path


def load_packager():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("android_packager", root / "scripts/package_android_delivery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_printable_demo_script_escapes_markdown_content_and_closes_structure():
    packager = load_packager()
    rendered = packager.render_markdown("# 讲解稿\n\n口播：<script>alert(1)</script>\n\n- 一\n- 二\n\n| 时间 | 操作 |\n| --- | --- |\n| 00:00 | `原图` |")
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert rendered.count("<ul>") == rendered.count("</ul>") == 1
    assert rendered.count("<table>") == rendered.count("</table>") == 1
    assert "<code>原图</code>" in rendered and 'lang="zh-CN"' in rendered


def test_delivery_private_scan_collects_values_without_printing(monkeypatch, tmp_path, capsys):
    packager = load_packager()
    secret = "test-placeholder-not-real-credentials-12345"
    (tmp_path / ".env").write_text("CAMERA_AI_API_KEY="+secret+"\n", encoding="utf-8")
    monkeypatch.setattr(packager, "ROOT", tmp_path)
    assert secret.encode() in packager.private_values()
    assert not capsys.readouterr().out
