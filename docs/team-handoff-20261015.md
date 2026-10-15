# 当前版本：队友开发交接

仓库主分支：`main`。当前工作包括单栏拍摄网页、Android 客户端、同站 API、构图手稿、设备与镜头联动，以及知识资料和部署文件。

## 先在本机启动网页

需要 Python 3.11+ 和 Node.js 22.12+（或符合 `mobile/package-lock.json` 依赖要求的更新版本）。在仓库根目录执行：

```powershell
git pull --ff-only origin main
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mobile,dev]"
npm --prefix mobile ci
npm --prefix mobile run build
.\.venv\Scripts\python.exe scripts/start_web.py --demo
```

打开 `http://127.0.0.1:8080/`。演示模式无需 API 密钥，用于检查选图、设备设置、规则建议、历史记录和导出；不会生成真实的场景识别与云模型构图。

前端开发运行 `npm --prefix mobile run dev`。完整同站流程以构建后由 `scripts/start_web.py` 提供的网页为准，单独打开 Vite 页面不能自动获得后端会话。

## 当前页面与代码入口

- `mobile/src/App.vue`：照片选择、拖入、设备设置、分析请求、记录与页面切换。取景框和相册入口直接使用原生文件输入，选图后预览；不会自动发送照片。
- `mobile/src/style.css`：单栏布局；桌面导航在顶部，手机导航在底部。
- `mobile/src/components/CompositionView.vue`：方案切换、原图对照与文字步骤。
- `mobile/src/components/CompositionSketch.vue`、`mobile/src/sketch-trace.mjs`：从本次原照片提取轮廓与浅色层，保持比例摆入九宫格，并提供主体画像和机位动作。`SketchGlyph.vue` 不再用于替代真实主体。
- `src/camera_assistant/composition_models.py`、`services/composition.py`：模型输出契约、旁白和构图提示词。新增字段兼容旧记录；示意坐标不等同于真实定位框。
- `src/camera_assistant/web_app.py`、`mobile_api.py`：会话、鉴权、上传限制、设备目录与分析 API。
- `knowledge/`：运行时知识和设备资料；`data/knowledge_drafts/` 与 `knowledge_sources/`：草稿和来源。草稿不会因文件进仓库就自动发布或参与正式检索。

## 真实模型与部署

密钥、体验码、会话签名、SQLite 数据库、私人照片、日志和本机构建结果均不提交。队友需要自行建立私有配置，不能依赖维护者电脑或线上服务器里的配置。不要把线上体验码、模型密钥放进前端、截图或提交历史。

真实模型接入与手机使用见 [真实环境说明](real-environment.md)，网页会话与 Docker 配置见 [部署说明](web-experience-deployment.md)。两个 Dockerfile 固定运行文件可读权限，避免增量发布时文件仅 root 可读而导致网页白屏。默认服务器方案不开放 8080 公网端口。

本机 Android 工程在 `mobile/android/`。首次构建按 [Android 使用说明](mobile-app-v1.md) 准备工具，再执行前端构建和 Capacitor 同步；`local.properties`、SDK、签名文件与 APK 不提交。

## 验证与后续优化

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix mobile test
npm --prefix mobile run build
```

优先在普通浏览器和手机上检查选图、同一文件重选、上传提示、设备切换、分析失败与重新分析。涉及构图修改时，核对图片、主体轮廓、坐标、留白文字和机位动作是否一致；旁白不应虚构画外内容或人物经历。

云模型可能需要数分钟，偶发失败需明确反馈；当前示意是摄影教学草图，不能当作实拍效果、测距或可靠检测结果。旧历史没有新增的旁白或形象字段时，需重新分析才能取得新内容。

## 本轮构图反馈更新

- 模型返回 `framing_plan`：画面诊断、视觉主次、主体摆位、宽高占比、方向留白、边缘保护、背景控制和完成标准。新增教学文字仍经过摄影矛盾和未测量精确距离检查。
- `source_bbox` 是模型估计的原图取材区域，`bbox` 是建议画面中的摆位区域，两者不能混用。`identity_features` 列出该照片需要保留的可见细节。提取时不拉伸、不镜像、不补画看不见的姿态；包含在主体中的道具不重复绘制。
- 线稿在浏览器内由原图边缘提取，浅色取自低透明度原图颜色，可关闭。它不是语义抠图，取材框内仍可能保留背景线条。主体画像可选择“保留更多边缘”，适合模型取材框偏紧时复查。
- 线稿和照片只保留在本次页面内存，不增加额外图片服务调用，不写入历史；点击“保存手稿”才将当前线稿嵌入 SVG 下载。旧记录没有原照片时提示重新分析。
- 验证覆盖等比摆放、完整边缘、主体内道具去重、内部细节线条、透明输入、坏模型数据回退和 SVG 内嵌图层；并核对了公开插画与普通人像照片。区域准确性及新机位透视仍需实拍核对。
