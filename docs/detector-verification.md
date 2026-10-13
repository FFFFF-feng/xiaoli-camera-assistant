# 检测集成交付验证

日期：2026-10-13（北京时间）。依据项目外的实施提示词和检测选型报告v2实施；第四轮对应 `real_20261012_05`，没有重跑四轮、没有新真实VLM请求。纯检测与联合定位页面已经实际运行，8502健康检查通过，原桌面启动脚本保持原入口。

## 已交付改动

| 文件 | 作用 |
|---|---|
| `src/vision_lab_tool/detector_models.py` | 独立 `detector-1` 实验、候选/选择/语义/参考/错误/评测结构，不扩展旧RunRecord |
| `detector_runner.py`、`detector_queries.py`、`detector_mock.py` | 单次共享VLM、A/B1/B2隔离、冻结词典、显式失败降级、计划阶段、缓存、来源与费用记录、离线故障夹具 |
| `detector_evaluation.py`、`detector_storage.py` | 确认参考评测、一对一IoU/TP/FP/FN、全计划分母、自动/人工条件、总体及来源分组、原子保存、筛选与脱敏导出 |
| `ui_detectors.py` | 纯检测/对照、后台取消、参考与错误动态表格/JSON导入、独立叠框、保存重开、筛选下载 |
| `src/vision_lab_tool/detectors/` | `base.py`、`grounding_dino_hf.py`、`ultralytics_yolo.py`、`client.py`、`worker.py`、`prepare.py`、`__init__.py`；隔离环境、隐藏常驻worker、官方锁定适配器与准备 |
| `scripts/prepare_detectors.ps1`、`detector_smoke.py`、`prepare_detector_pilot.py` | 明确依赖/权重准备、真实离线冒烟及独立十图配置准备 |
| `requirements-detectors.txt`、`.gitignore` | 重型依赖单独锁定、忽略独立环境；原pyproject依赖未修改 |
| `src/vision_lab_tool/ui.py`、`adapters.py` | 增加页面路由、复用密钥配置；请求构造新增可选schema覆盖，旧接口默认行为不变 |
| `README.md`、`docs/vision-lab.md` | 增补入口链接，保留原文与原流程 |
| `tests/test_detector_{runner,runtime,evaluation,storage,ui}.py` | 本轮新增有意义回归 |
| `docs/detector-lab.md`、`detector-runtime.md`、本文件 | 操作、方法/指标、环境/权重/许可、证据及边界 |

原目录已存在大量未提交视觉测试代码和文档，本轮没有覆盖、重置或提交它们。`app.py`、原 `.venv`、`pyproject.toml`、`start_vision_lab.ps1` 和原摄影推荐流程未修改。新实验目录与原v1历史独立。

## 真实本地检测

独立环境：Python 3.13.12，Windows 11，CPU/float32。PyTorch `2.10.0+cpu`、torchvision `0.25.0+cpu`、Transformers `5.19.0`、Ultralytics `8.4.176`。原 `.venv` 检查 `torch/transformers/ultralytics` 均未安装。电脑有RTX4060约8GB，但本次CUDA推理未验证，CPU wheel选择GPU会明确显示不可用。

IDEA官方Tiny权重和Ultralytics官方YOLO26n权重已下载，不可变revision、SHA256、大小及库版本见 [运行环境记录](detector-runtime.md)。Tiny按Apache-2.0模型卡记录；Ultralytics AGPL-3.0和Enterprise为不同条件，没有购买许可。未来公开发布须另核实际用途，隔离环境不改变许可义务。

真实离线冒烟在已有P02图上执行，两检测器解码同一JPEG（1600×1071，发送SHA256 `a54df27e67c1410877ef20d31421eb2d0f0b5bf1ed135c758428bc69a9165064`），通用查询person/bicycle/dog/car。未从真值/检查点生成查询；VLM调用0，worker网络禁用。

| 检测器 | 原始预测 | 合法候选 | 冷/热wall时间 | 状态 |
|---|---:|---:|---|---|
| Grounding DINO Tiny | 900 | 43 | 16.609 / 5.033秒 | success |
| YOLO26n | 300 | 14 | 0.718 / 0.108秒 | partial_coordinates |

YOLO另有2个超过阈值的原始框在官方裁切前越界：保存原框、官方裁切后框及失败诊断，不把裁切后的框冒充原始合法框。两张实际叠框已目视检查方向与坐标对应。上述时间是单图单次冷/热观测，含进程/哈希/IPC开销，不能承诺普遍速度。

冒烟证据：[summary.json](../data/vision_lab/detector_experiments/smoke_cpu_verified/summary.json)，同目录有冷/热完整结果、实际发送JPEG及叠框。

实际8502页面还以共同任务“找出照片中的人物”、词典查询person运行了两检测器，run `dd55adce9e01413b8952af415bf0903f`：DINO 39个合法候选，YOLO 14个合法候选并保留同类越界诊断，VLM调用0，参考未完成。候选数与四查询冒烟不同，查询不同如实保存，没有混称准确率。页面保存、真实历史选择重开及JSON下载已实际操作；没有新增推理。JSON下载为用户Downloads中的 `detector-experiments.json`；本地还保存了该真实run的JSON/CSV导出证据。

真实页面截图：

![真实CPU纯检测页面](../tmp/detector-verification/real-detection-ui.jpg)

## 模拟与回归验证

最终完整项目回归：**292通过，1跳过；Ruff全部通过**。唯一跳过是已有知识库符号链接测试，本机没有授权创建符号链接，与检测模块无关。

命令：

```powershell
$env:TEMP = Join-Path (Get-Location) 'tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --basetemp tmp/pytest-detector-delivery
.\.venv\Scripts\python.exe -m ruff check .
```

受限环境的Streamlit本地回环测试不能连接，使用获准的本地回环环境完成；所有这些VLM请求均为MockTransport或离线夹具。默认Windows临时目录/GBK存在环境问题，因此明确项目内basetemp与UTF-8。中途发现的测试/实际页面失败已经修复，最终日志没有失败；不会把早期失败略去称作全程一次通过。

已验证：

- 纯检测一个检测器、无VLM配置/Key可运行，VLM计数为0；定位对照只调用一次VLM，A/B1/B2共用回答和相同JPEG；历史、标注、人工选择、保存、导出、参数控件变动均不新增调用。
- 合法/空候选、重复ID、非法坐标、多主体歧义、整体/部件重叠、未支持类别、VLM网络/JSON/语义/框失败；A失败保持原状，B本地候选保留，必要时detection_only并弃权。
- 非方图、EXIF旋转、缩放/padding转换、越界不截断、原始候选证据、ID引用唯一/存在；两个语义实例或主目标/辅助目标不能复用一个候选框，更不能后来覆写所选框层级。
- 缓存随图像/任务/模型/词典/参数/权重/运行依赖变化失效；缓存来源明确，重复明确运行新attempt；模拟语义+真实检测的混合来源不能称完整真实联合实验。
- 不读取人工真值生成查询；不执行数学表达式；独立语义提取不修复A；主体状态畸形不能晋升为B选择成功。
- 确认人工参考、不同层级配对拒绝、低IoU仍保留、漏/误检分母、未支持完整目标、人工辅助独立、同类多个独立错误ID、实体unknown几何评测与完整任务门槛区分。
- 计划A/B阶段在调用前已有身份；总体汇总保留pending/缺环境/失败分母，实际权重/版本分组为补充；共享真实VLM费用只计一次，未发送/模拟不计账，本机计算成本未知。
- Windows原子替换有限重试，持续写盘失败保留旧文件与当前会话结果；后台停止/超时保留已完成阶段；Streamlit热重载旧配置实例可重新规范化。
- v1加载、叠框、续评、保存与导出回归；秘密/base64/请求头脱敏和CSV公式转义。

实际浏览器模拟run `9afbc62fc51d4ce895f602387bd4d3a1`展示完整三列叠框、候选、状态和来源，结果为模拟夹具，不代表照片内容。两次开发调试留下的模拟失败/阶段记录保留在新历史中：其中 `10c90c9f...` 为热重载类型故障后未完成阶段，不改写成成功。

![模拟A/B1/B2页面](../tmp/detector-verification/localization-ui.jpg)

## 历史与未验证范围

实际旧v1记录**73条均可加载/导出**；四轮及相关benchmarks目录**314个文件SHA256复核，变化0**。没有自动修复/重新评分/重发四轮失败请求。独立 `detector_pilot10_v2` manifest已准备，3开发/7阈值留出，图片已看过，不称完全盲测；参考仍待人工确认，质量实验未启动。

**尚未验证：** 新定位提示词在真实GLM或其它真实VLM上的返回兼容和质量；真实VLM＋检测器联合准确率；人工真值IoU/召回/主体选对率；十图质量实验；GPU/float16；并发多用户性能、长期生产稳定性、摄影实拍改善。当前B的自动关联采用保守精确类别规则，对属性指代、多实例、实体归属和复杂组合会弃权；检测框不能判断亮点物理身份、速度或器具用途。

无完整人工参考时质量指标保持未评测；模拟数据单独统计；真实冒烟只证明接入与坐标流水线可运行，不构成模型选型准确率排名。本轮真实VLM调用、云检测上传、新增云账户及许可购买均为0。

原始验证文件在受忽略目录 `tmp/detector-verification/`：`pytest-final.txt`、`ruff-final.txt`、`history-before.json`、`history-after.json`、两张UI截图、`real-ui-run.json/csv`。操作和指标定义见 [检测工具说明](detector-lab.md)。
