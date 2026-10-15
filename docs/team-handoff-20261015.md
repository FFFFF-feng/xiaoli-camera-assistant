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
- `mobile/src/components/TargetComposition.vue`、`mobile/src/target-board.mjs`：根据模型设计的目标布局与主体结构点重绘推荐分镜。`SceneSurvey.vue` 展示逐图证据和同场景比较。原图提线的旧 `CompositionSketch.vue` 已退出主要反馈流程。
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

## 多图场景与推荐构图：开发顺序

1. **场景输入**：相册和拖入入口支持批量选图，同一场景最多6张；主图位于第一张，支持补充、删除和换主图。每张JPEG/PNG沿用服务上限，整组最多30MB。任一文件错误则整批拒绝，保留已选照片；修改照片后重新确认上传。选图不会自动发送。
2. **综合识别**：`/api/v1/analyze-scene` 接收主图 `file` 与参考 `reference_files`，主图为 `photo1`。保留单图 `/api/v1/analyze` 兼容。场景模型接收全部照片，`scene_survey` 逐图说明证据、关联状态、推荐起点、主体候选、已有前景与相对距离。不同场景不强行融合。无标定多图不能推导米/厘米、真实轨迹或精确三维关系。
3. **构图决策**：先诊断原图真实问题，决定目标主次、布局、相对距离与层次。`storyboard` 中每项 `changes` 解释“原图问题—推荐调整—预期改善”。主体可居中，不强制套三分法；动作要写取景器内可检查的变化，不能搬动建筑树木或编造道具。
4. **目标画面重绘**：`TargetBoard.layers[].bbox` 是目标画面的对象位置，`outline/details` 是对象盒内0..1局部坐标。`services/target_drawing.py` 用同一提供商额外一次请求精化所有方案，锁定布局，只细化可见外形及结构。建筑连廊/立柱、动物耳尾、人物姿势等要由轮廓与内部线条表达。不是把原照片变线稿，也不把原图裁片拼在目标画面中。渲染只接受有限数值，不能执行模型返回的SVG/HTML。
5. **阅读与核对**：单栏显示多图场景摘要、推荐分镜、浅色开关、九宫格、主体特征、目标宽高占比、改进理由及实际拍摄步骤。原图对照可以切换本组照片；检测框和裁切坐标只用于主图。无法通过格式/引用/绘图检查时保留文字，不用占位图冒充成功。旧记录需重新分析才能获得新版目标图。

模型推断的外形、透视和遮挡仍是近似，需要现场复核；格式校验不代表已经证明摄影效果。增加绘图精化会增加时间和模型用量。公开场景照片用于云模型冒烟测试；私人照片测试不新增服务提供商或留存。

## 本地验证与隐私边界

- 默认双击根目录 `启动项目.cmd`，会构建最新网页并重启本项目的后端。端口被占用时顺延，以启动窗口为准；当前维护者本机使用8081。仅本机运行，发布需另行操作。
- 照片和预览URL只在页面内存中，不进入历史；历史保留结构化分析及目标图数据。多图仅在请求中传给已配置的提供商，不保存到网关。参考照片的内部数据URL不返回前端响应。
- 单元测试覆盖多图鉴权、限流路由、张数/大小/类型、坏参考图整组拒绝、逐图证据、多场景不拼接、目标坐标、缺层、坏结构和绘图失败保留文字。UI需验证换主图排序、补删、同意框重置、原图切换、SVG导出，以及窄屏排版。
- 新机位的透视与遮挡不做实拍保证，无法从这些照片测出精确距离；后续若需真实三维重建，另行设计有标定的采集流程。
