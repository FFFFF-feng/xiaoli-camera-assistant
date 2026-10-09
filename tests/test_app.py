from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_starts_in_demo_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "app.py", default_timeout=10).run()

    assert not app.exception
    assert app.file_uploader[0].label == "上传现场原图"
    assert app.text_area[0].label == "你想拍出什么效果？"
    assert app.selectbox[0].label == "相机型号"
    assert any(button.label == "让小栗帮我配参数" for button in app.button)
