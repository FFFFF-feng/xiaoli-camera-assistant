# 检测环境、权重与真实冒烟

本模块只处理本地目标检测。现有 Streamlit `.venv` 不安装 PyTorch、Transformers 或 Ultralytics；检测在项目 `.venv-detectors` 的独立隐藏子进程中运行。没有环境/权重时，旧页仍可启动，检测页显示准备状态。图片只通过项目内临时文件传给本地进程；推理进程禁止网络连接，无隐式权重下载。

## 明确准备

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepare_detectors.ps1
```

默认采用现有 `.venv` 的兼容 Python 创建新环境，存在 uv 时优先使用 uv。可用 `-Python E:\Miniconda\python.exe` 显式指定；不删除/重建旧 `.venv`。本机 `py -3.13` 指向 Python 3.13.0，其 ensurepip 创建过程失败，已改用现有 Miniconda Python 3.13.12 与 uv，独立安装成功。准备脚本使用 CPU 官方 PyTorch wheel 源；首次下载大约需要模型本体 695 MB，加上依赖与缓存。下载需要联网，推理不需要联网。

`-Detector grounding_dino` 或 `-Detector yolo26` 只准备对应权重。`-Revision <HF commit>` 可冻结特定 DINO revision；默认 main 先解析不可变 commit，再按 commit 下载。`-ProbeOnly` 跳过权重下载但仍准备依赖。只重新探测已安装环境：

```powershell
$env:PYTHONPATH = "src"
.\.venv-detectors\Scripts\python.exe -m vision_lab_tool.detectors.prepare --probe-only
```

权重和准备清单位于受 Git 忽略目录：

| 项目 | 路径 |
| --- | --- |
| Grounding DINO Tiny | `data/vision_lab/model_cache/grounding-dino-tiny/` |
| DINO 清单 | 同目录 `detector-manifest.json` |
| YOLO26n | `data/vision_lab/model_cache/yolo26n.pt` |
| YOLO 清单 | `data/vision_lab/model_cache/yolo26n.manifest.json` |
| 环境探测 | `data/vision_lab/model_cache/runtime.json` |
| 当前全部依赖版本 | `data/vision_lab/model_cache/requirements-lock.txt` |

每次真实结果包含实际库版本、权重 SHA256/大小、revision、设备、精度、输入张量尺寸及阈值。权重与清单哈希不一致明确失败；改变权重、revision、设备或精度会重新加载模型。准备清单缺失的手动权重会标为 `local-unversioned`，不能当作官方已冻结版本。

## 启动、停止与设备

继续使用现有 `start_vision_lab.ps1`，默认入口保持 8502。只有页面明确运行动作才启动检测。常驻 worker 最多缓存两套模型；点击停止会终止当前 worker，正在等待的检测记录 `cancelled`。超过配置超时则记录 `timeout` 并停止进程；下次明确运行重新冷启动，不自动重试。退出 Streamlit 时有进程清理。

默认 `cpu` / `float32`。本机虽有 NVIDIA RTX 4060 8 GB，已准备环境为 `torch 2.10.0+cpu`，因此 `cuda:0` 明确显示不可用。GPU 安装/推理及 float16 尚未验证。以后按 [PyTorch 官方选择器](https://pytorch.org/get-started/locally/) 核对驱动与 wheel，显式用相应官方索引和 `-ReinstallTorch` 替换独立环境中的 torch/torchvision，再执行探测。例如官方对应 wheel 确认可用后，可指定 `-TorchIndex https://download.pytorch.org/whl/cu128 -ReinstallTorch`；该示例不代表本机 CUDA 已验证。

CPU 不接受 float16；未知设备不自动回退。检测页 readiness 仅读本地准备状态，不加载模型、不联网。若用户后来删除包导致准备记录失效，运行时错误仍单独记录，重新准备/探测可更新状态。

## 实际锁定接口

2026-10-13 核验 [Transformers Grounding DINO 官方文档](https://huggingface.co/docs/transformers/main/en/model_doc/grounding-dino)、[IDEA Tiny 官方模型卡](https://huggingface.co/IDEA-Research/grounding-dino-tiny)、[Ultralytics YOLO26 官方文档](https://docs.ultralytics.com/models/yolo26)、[Results API](https://docs.ultralytics.com/reference/engine/results/) 并检查安装版本源代码。

- Transformers 5.19.0 使用 `AutoProcessor` / `AutoModelForZeroShotObjectDetection`，`local_files_only=True`、`trust_remote_code=False`。后处理参数为 `threshold`、`text_threshold`，`target_sizes=[(发送JPEG高, 发送JPEG宽)]`。使用 `text_labels`，不把整数 token 索引当类别。查询为英文短语，用句点分隔；长于模型 token 上限明确拒绝。原始 900 个 query 的归一化 cxcywh 和官方后处理像素 xyxy 均保存，再按配置框阈值过滤。分数是最大 sigmoid 文字关联值，不是准确率。
- Ultralytics 8.4.176 仅允许 `yolo26n.pt` / detect，`batch=1`、`imgsz=640` 默认、`rect=True`、`nms=False`。按固定 80 类运行，不用文字查询过滤模型输出。保存 conf=0 的全部 Results 和 native end2end head 原始预测，之后独立应用 confidence 阈值。`Results.boxes.xyxy` 已还原至发送 JPEG 像素，不二次去 letterbox。
- 锁定 Ultralytics `ops.scale_boxes` 会在还原后裁到图像范围，因此额外保存裁切前坐标、原始内部框、实际 resize/padding 与 `official_clipped`。越界/倒序/零面积的原始框不会因官方裁切变成原始合法候选；原始证据保留，并标 `coordinate_error` 或 `partial_coordinates`。
- 两检测器都解码同一份 `prepare_image.sent_bytes`，最终按发送图 W/H 归一化，叠框乘 EXIF 修正原图 W/H。DINO 和 YOLO 内部尺寸不同，结果如实记录。可选去重只作用于同标签/层级，保留所有原候选及移除依据；默认不去重，避免近邻实例被合并。

## 许可

IDEA Tiny 官方模型卡标 Apache-2.0。Ultralytics 的代码和模型采用 AGPL-3.0 或另行购买的 Enterprise 许可，二者不是相同条件；本轮仅安装公开包/权重，没有购买许可。发布或嵌入产品前应按实际用途审查 [Ultralytics 官方许可说明](https://www.ultralytics.com/license)。此模块隔离依赖不等于改变许可义务。

## 已执行证据

北京时间 2026-10-13，Python 3.13.12 / Windows 11 / CPU / float32，安装 `torch 2.10.0+cpu`、`torchvision 0.25.0+cpu`、`transformers 5.19.0`、`ultralytics 8.4.176`。原 `.venv` 查询 torch 和 ultralytics 均为未安装。

| 权重 | 实际 revision | 文件字节 | SHA256 |
| --- | --- | ---: | --- |
| DINO `model.safetensors` | `a2bb814dd30d776dcf7e30523b00659f4f141c71` | 689359096 | `1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3` |
| YOLO26n | `assets-v8.4.0` | 5544453 | `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` |

执行 `\.venv\Scripts\python.exe scripts\detector_smoke.py --output data\vision_lab\detector_experiments\smoke_cpu_verified`，使用现有 P02 照片、固定通用查询 person/bicycle/dog/car，不读取 manifest/人工真值产生查询，不调用 VLM。DINO 冷/热运行均产生 900 个原始 query、43 个合法候选，内部张量 `1×3×800×1195`。YOLO 冷/热运行均保存 300 个原始候选、14 个合法候选，内部张量 `1×3×448×640`；有 2 个超过 confidence 阈值的原始框在官方裁切前越界，明确保留失败证据，状态 `partial_coordinates`。已查看两张实际叠框图，图像方向与坐标对应正常。

完整 JSON、冷/热耗时、实际发送 JPEG 和叠框位于 `data/vision_lab/detector_experiments/smoke_cpu_verified/`。`wall_total` 包括解释器/库初始化、哈希与 IPC；`load` 是模型/适配器初始化；`worker_and_ipc_overhead` 保留二者差额。CPU 冒烟单图、单次冷/热观测不能作为速度保证或准确率评测。没有人工真值，IoU、召回、主体选择正确率仍为未评测；GPU、真实 VLM 联合质量和十图质量实验尚未执行。

运行 `pytest tests/test_detector_runtime.py` 可验证坐标、保留原始失败、去重证据、哈希变化、环境缺失、超时、取消、设备精度和隐藏 worker。受限 Windows 沙箱若系统 TEMP 不可写，可使用项目内 `--basetemp tmp/detector-runtime-tests`；这只是测试临时目录。检测结果缓存由实验 runner 按配置/权重与图片等管理，worker 模型缓存仅避免重复模型加载，不冒充结果缓存。

## 常见故障

- `environment_missing`：独立环境或导入探测未完成；执行明确准备操作。原页面可继续使用。
- `model_missing`：本地目录/文件缺失或误选其他任务权重；按清单准备指定模型。
- `device_unavailable` / `precision_unsupported`：CPU wheel 不能运行 CUDA，CPU 首版用 float32。
- `query_missing` / 查询 token 超限：提供简洁英文类别短语，来源需明确；不把中文质量当作已确认。
- `coordinate_error` / `partial_coordinates`：检查原始框与后处理坐标、官方裁切标记；不静默修复为成功。
- `timeout` / `cancelled`：该 attempt 保留；下一次需要点击明确运行按钮。
- `runtime_error`：展开诊断；进程提前退出可检查受忽略目录 `data/vision_lab/detector_experiments/worker/worker.log`，不向日志加入密钥、请求头或完整图片 base64。

依赖/权重下载失败可重试明确准备步骤，推理页面不自动联网修复。阈值只是工程起点，真实质量实验须完成并确认人工参考、冻结开发设置后由用户明确启动。
