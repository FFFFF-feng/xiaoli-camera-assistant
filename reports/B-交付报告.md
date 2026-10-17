# B：分割模型与离线基准交付报告

日期：2026-10-18（Asia/Shanghai）。角色状态：**DONE，限 B 的独立接口、候选验证与离线基准交付**。产品接入和最终线绘尚未验收；杯子边缘质量未全部达标，不能据此宣布 INTEGRATION_READY。

## 交付位置与提交链

- 工作树：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-segmentation-adapter`
- 分支：`codex/segmentation-adapter`
- 唯一基线：`986fd0594150dce96b3255c8cc77ff54e8174620`
- 完整交付范围：`986fd0594150dce96b3255c8cc77ff54e8174620..codex/segmentation-adapter`。包括本报告所在的最终提交，A 应整段核对，不只摘取最后提交。
- 前两项有序提交：`d8ec3edee8c1995c5b3db861243fb1b3c7b74a6c`、`7a71a9ee78faeec5d118c5ceeb9fc5295593c0b3`；最终提交 SHA 在聊天交付及协调包报告末尾列出。可用 `git log --reverse --format=%H 986fd0594150dce96b3255c8cc77ff54e8174620..codex/segmentation-adapter` 获取完整有序链。

仅修改本角色路径：`src/camera_assistant/services/segmentation/{__init__,contracts,runtime,mobile_sam}.py`、三个 `tests/test_segmentation_*.py`、`scripts/segmentation_benchmark/{PLAN.md,README.md,benchmark.py,integration_example.py}`、`reports/B-*`。A 原目录没有由 B 切分支、暂存或修改；pixel_contours、pixel_strokes、schema、pipeline、根依赖、mobile 和启动器均未改。没有 push、合并、部署或重启共享服务。

应用工作树工具在聊天关联仓库无法解析该 SHA；核实实际仓库含该提交后，才在已核实绝对路径用 Git CLI 创建上述工作树。未从 main 开始，也没有复制项目源码代替隔离。

## 已实现接口与资源边界

导出冻结 `segmentation-v1` 的 `SegmentationRegion`、`SegmentationResult`、`SegmentationRuntime.segment_many/close`。构造器另支持显式本地权重、预期散列、设备与 backend protocol 工厂；不改变 A 冻结调用签名。

- 方向已归一 RGB uint8，8×8 至 400 万像素；1–4 个唯一 object1..object6；归一 XYXY，各轴至少4输入像素。空批返回空列表；非法 ID 使用既定 `invalid_bbox`，非字符串 ID 在失败输出中归为空字符串。
- 成功返回同输入尺寸 bool mask；保留孔隙和所有连通分量。返回副本，不填矩形、不补画杯把/杯底、不强制选最大分量。失败 mask=None，使用固定码；异常正文不外泄，没有隐式 GrabCut 降级。
- 一个模型、一个推理槽、一个进程内 embedding，排队最多0.5秒；每批只编码一次。同图/同完整有效提示可复用编码，仍重新解码。内容/尺寸/模型/权重/设备/预处理/提示变化使键失效；失败清理 embedding，不落盘照片或 embedding。
- 在排队前冻结区域参数；在锁内复制并再验证图像，后续只用拥有的快照。close 与推理同锁，幂等释放，reset 异常后拒绝继续使用未知状态。逐区域已确认错误不会被缺权重、关闭或超时等批级错误覆盖。
- `queue/load/encode/decode/postprocess/total` 为单调墙钟秒。load/encode/queue 为同批共享阶段，decode/postprocess 为相应对象；total 为整批墙钟，不可逐对象累加。

**超时边界：本实现是阶段边界超时，不是硬中断。** native load/encode/decode 可能在超时后才返回，期间仍持有槽；随后返回 inference_timeout 且不缓存成功。close 也会等待。A 如需硬服务截止，须在可回收工作进程内使用，不能把本同步实现当硬实时保障。

**需 A 明确的预处理解释：**官方 SamPredictor 在连续 logits 上做双线性重建，再阈值化为原图 bool；B 对二值 mask 的尺寸恢复严格采用最近邻。没有把二值图做平滑/填孔。若冻结契约的“最近邻”还要求改变神经网络连续 logits 的原生重建，本后端不满足该更强字面解释，须 A 澄清后接入。内部编码最长边1024已披露；720/1280 比较输入相同，不能声称1280像素全部以原尺寸进入网络。

## 实际候选、权重与环境

实际运行 **1 个候选：MobileSAM vit_t**，没有训练。官方源码固定 `f706ad9c4eb7f219c00d9050e46328518ffb65d2`；安装为 mobile_sam 1.0。来源与接口核对：[官方仓库](https://github.com/ChaoningZhang/MobileSAM)、[固定权重文件](https://github.com/ChaoningZhang/MobileSAM/blob/f706ad9c4eb7f219c00d9050e46328518ffb65d2/weights/mobile_sam.pt)。仓库声明 Apache-2.0，权重随该仓库分发；没有擅自补充独立权重许可结论。

权重大小 **40,728,226 bytes**，实际 SHA-256：

`6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f`

本机忽略路径：`.tmp/B-segmentation/MobileSAM/weights/mobile_sam.pt`。运行时只加载本地文件，使用 weights_only=True；权重没有进入 Git。候选选择固定为：最多3个有效候选中有限预测 IoU 分数最高者，同分取最小下标；selection_basis 写明 not_accuracy。模型自评分不是实测准确率。

SAM 2.1 Tiny 未安装、未运行、未排名。[SAM 2 官方安装说明](https://github.com/facebookresearch/sam2/blob/main/INSTALL.md) 推荐 Linux，Windows 推荐 WSL；已有可行 MobileSAM 后没有扩大运行栈或下载第二模型，符合最多两候选上限。

硬件：Intel i7-14650HX，24逻辑 CPU，RAM 16,944,848,896 bytes；NVIDIA RTX 4060 Laptop GPU，nvidia-smi 实报8188 MiB，驱动595.97。**所有实际模型基准使用 CPU，GPU 推理没有测试**，不提供 GPU 延迟或显存结论。

独立 Python 3.13.12 venv 位于 `.tmp/B-segmentation/venv`。最终 Torch 2.10.0+cpu、torchvision 0.25.0+cpu、NumPy 2.5.2、Pillow 12.3.0、OpenCV headless 4.14.0.94（cv2 4.14.0）、timm 0.9.12、psutil 7.2.2、pytest 9.1.1；Torch 实际16线程。版本/导入绝对路径/空间见 `reports/B-environment.json`，完整 pip freeze 在忽略目录。pip check：No broken requirements found。

初始 ensurepip 因沙箱 TEMP 无法写入失败，改用任务内 TEMP 后成功。官方 CUDA Torch 包约3.46 GB，CPU 2.8 包约619 MB，网络下载进展不足，均明确停止；还探测并尝试了较小2.6包，最终未采用。随后发现本机已有 CPU Torch，按发行包 RECORD 清单只读复制依赖到新 venv：初始 Torch 闭包535,665,981 bytes、15,942文件、33.19秒；另复制独立 OpenCV/pytest/HF 依赖，再安装 timm 与固定本地 MobileSAM。没有升级共享环境、共享 pth 或将共享 site-packages 加入模型 PYTHONPATH。以上所有失败/中止日志及复制清单均保留；不把安装时间当推理时间。单独包导入探针实测11.61秒，不等于加载模型。

## 对照设计与完整分母

读取了历史报告、manifest/结果/阶段数据及人工冻结区域。旧历史观察框没有保存，狗 `[.18,.25,.81,.78]`、杯 `[.36,.065,.98,1]` 沿用 A 已标记的人工冻结框。山湖/走廊为 B 的人工适用性观察框。**全部均为条件受控的离线比较，不是历史自动观察重放或完整自动流程成功。**没有人工逐像素真值，因此没有 IoU。

同原照片、相同 EXIF 归一 RGB、相同框、相同720/1280尺寸，比较旧提交 `9b9ad3b...` GrabCut、冻结检查点 GrabCut、MobileSAM。GrabCut 从两提交 `_trace_single` 提取生成 foreground 为止的 AST 前缀，保留各自初始化/迭代/随机种子，记录源文件散列；没有执行后续简化/细节校验。因此 mask_prefix_only 成功不能证明旧或新完整线绘成功。

- 初步 GrabCut-only：4图×2尺寸×2版本×2次 = **32**。
- 正式三方比较：4图×2尺寸×3后端×2次 = **48**，其中32 GrabCut、16 MobileSAM。
- 补充真实多对象 API smoke：同一狗图人工框中的狗与蓝球，2批×2对象 = **4** 模型输出。
- 合计 **84 个区域掩码尝试**：64个 GrabCut 前缀、20个 MobileSAM 输出；后者来自18次 API 调用。20个模型输出均通过 mask 基础契约，不能等同20个语义正确或产品可用结果。全前景/空前景等失败另外由合成测试验证，未混入照片分母。

每条件第二次模型请求是**编码缓存命中**，只重新解码，单列。所有实际尝试写盘，PNG生成失败不会抹掉推理分母；manifest 原子替换。真实云网关完整请求 **0**，内部云模型请求 **0**。

## 本机分段耗时与内存

下表为正式运行 CPU 秒，单图单次记录，未经统计外推；后处理为 B 的候选验证/选择，官方 logits 重建包含在 decode。对照脚本的 PNG 绘制/磁盘保存不在推理 total 内。

| 输入/状态 | load | encode | decode | postprocess | total |
| --- | ---: | ---: | ---: | ---: | ---: |
| 狗720，进程内首次模型加载 | 3.13248 | 0.51672 | 0.03326 | 0.00035 | 3.68403 |
| 狗1280，模型已加载，重新编码 | 0 | 0.42315 | 0.03079 | 0.00031 | 0.45820 |
| 杯720，重新编码 | 0 | 0.35639 | 0.02378 | 0.00015 | 0.38226 |
| 杯1280，重新编码 | 0 | 0.37090 | 0.02601 | 0.00047 | 0.40164 |
| 狗1280，同图编码命中 | 0 | 0 | 0.02278 | 0.00026 | 0.02569 |
| 杯1280，同图编码命中 | 0 | 0 | 0.02261 | 0.00061 | 0.02756 |

首次加载包含本地散列、依赖导入、构造、权重反序列化；不是断电后磁盘缓存实验。其他场景重新编码 total 0.38792–0.41592秒。queue 各次实测约0.000003–0.000007秒，完整原值见 JSON。不能把约0.02秒的缓存命中当完整编码速度，也不据此报端到端提速百分比。

同轮1280 GrabCut 前缀，狗旧/检查点首次1.7995/2.1353秒，杯旧/检查点1.3886/1.4485秒。两方都只比较掩码产生阶段，神经网络与 GrabCut 内部算法不同；没有包括 A 下游或云等待。

额外两对象首批：load3.65393、encode0.43987、两个 decode0.03395/0.02503，**整批**4.15648秒；相同两框第二批编码为0，整批0.05301秒。共享 load/encode/total 不能重复求和。此项只证明真实多框编码复用，不证明蓝球独立挪动构图合理。

正式运行采样的最大进程 RSS **904,777,728 bytes**，close 后 **840,384,512 bytes**；为采样驻留值，不是严格进程峰值。CPU 分配器/已导入 Torch 仍可驻留，close 不承诺 RSS 归零；模型和 embedding 生命周期由测试另证。所有推理脚本结束后进程退出。没有 GPU 压测资源占用。

## 人工画面核对与候选选择

| 项目 | 已观察结果与限制 |
| --- | --- |
| 狗细腿/孔隙 | 1280 MobileSAM 保留前腿三角孔，单主体连通，孔轮廓面积800像素²；检查点 GrabCut 对应大孔949像素²，旧版没有恢复该三角。不能把面积差当 IoU 或断言谁是真值。MobileSAM 少了 GrabCut 的草地点状分量，但腿尖/毛缘仍有偏差。 |
| 狗耳/口鼻/眼/球 | mask 能保留大轮廓，不能自动形成内部耳、眼或球辨识线。模型口鼻区域与 GrabCut 孔结构不同，必须原图核对，不能仅依据孔数判优。狗质量目标未宣布全部通过。 |
| 杯可见左下缘 | MobileSAM 相比 GrabCut 左下小平台状误分更贴近杯身；不补画杯把或杯底。 |
| 杯截断与杯沿 | **明确未解决：720/1280下分别漏掉照片底部最后2/3行可见杯身像素**，底行前景为0；检查点 GrabCut 保留底行。1280仍有14个小孔，多位于杯沿附近，不能当真实孔洞。模型 mask 返回成功不等于杯边质量通过。 |
| 山湖 | 掩码把山与倒影/大片场景结合，并产生分离小区；不能修复历史 observation 协议失败，仍需整体结构表达。 |
| 走廊 | 掩码主要分离墙柱/屋顶与地面，无法表达连续拱门递进和消失点。不能取代 scene_structure。 |

选择结论：**交付 MobileSAM 作为 A 可选验证后端；暂不建议直接切换产品默认后端。**依据是狗腿孔保留和杯左缘改善，同时存在可见杯底边损失、杯沿误孔、内部身份细节缺失，以及最终线绘未接入。没有测试 SAM 2，所以不宣称 MobileSAM 胜过它。

掩码好不等于线绘好：A 当前下游还会取 primary、简化至每路径64点、分配 details，以及限制 holes 与 contours 同时表达。原始狗 mask 边界上千点经过这些环节仍会丢细腿、耳尖或分部；本次没有替 A 修改这些模块。A 必须继续做覆盖率、自交、来源、比例与多连通/孔隙检查，E 再验收实际最终线绘。

## 测试、审查、未通过项

1. 接口测试最初25项因模块缺失先失败，再通过；随后清理异常和失败候选分母2项先失败后通过；只读审查后的快照/非法ID/逐区域错误/证据落盘7项先失败后通过。
2. 独立模型环境：`python -m pytest -q tests/test_segmentation_runtime.py tests/test_segmentation_mobile_sam.py tests/test_segmentation_benchmark.py --basetemp .tmp/B-segmentation/model-env-tests` → **43 passed in 4.63s**，24条上游警告（含timm模型注册名称重用），没有隐瞒警告。含实际 corrupt weights、错误设备、缺依赖/权重、空/满/非法mask、微小图、非法框、多个对象、孔隙、多分量、超时、排队、快照污染、失败不缓存、close 等。
3. 三个 B 测试加六组现有像素回归 → **117 passed, 1 skipped in 6.03s**。共享非模型环境的可选 MobileSAM 测试因未安装而跳过；独立模型环境对应测试已实际通过。
4. 全量 Python 初次因沙箱 Windows asyncio socketpair 建立挂住；栈定位后经工具权限机制在沙箱外运行 → **1485 passed, 3 skipped, 1 failed in 122.32s**。唯一失败：`tests/test_launch_apps.py::test_forwarding_cmd_works_from_a_unicode_desktop_folder`，B 独立工作树未安装 mobile/node_modules，启动检查提示“前端依赖尚未安装”。本次不安装前端或改 A 启动器来遮盖该环境失败。
5. 根 `启动项目.cmd --check` 已执行，同样因前端依赖缺失返回1；检查过程没有正常启动/重启共享服务。三个启动入口已只读检查，未改依赖/入口/配置。前端测试与构建属 A/D，不宣称通过。
6. B-owned Ruff 检查、git diff --check 均通过。完整分支经独立只读审查；3项 Important 已修复。证据写盘分母问题从 Minor 提升为 Important 并修复。

保留的轻微限制：benchmark GPU 内存统计使用默认设备，若未来选择非默认 cuda:N，须先修统计并重测；当前CPU报告不受影响。没有拿它冒充显存证据。

## A 最小接入及下一步

可直接阅读 `scripts/segmentation_benchmark/integration_example.py` 与 README。A 在服务生命周期创建一个 Runtime；对同一幅归一 RGB 的所有 eligible silhouette 对象批量调用 segment_many。成功后在现有 `_trace_single` foreground 位置裁取 `result.mask[oy:ey, ox:ex] * 255`；保留原有下游检查。失败记录模型固定原因；是否另跑 GrabCut、如何记录两次尝试，由 A 决定。连续场景继续走 scene_structure。

A 接入前明确 logits/二值最近邻解释、同步超时边界与权重固定方式；保留杯子边缘失败，不以成功 mask code 绕过几何或质量校验。默认后端选择和 optional extra 由 A 决定，最终图形/耗时由 E 验收。B 不接管共享依赖、服务或真实云预算。

## 本机证据绝对路径

证据根：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-segmentation-adapter\.tmp\B-segmentation`

- `model-run1/manifest.json`、`report.html`：正式48次完整分母及四图720/1280三方叠加、原始轮廓对照。
- `model-run1/02-front-leg-gap-focus.png`、`02-ears-muzzle-focus.png`、`06-visible-left-bottom-focus.png`、`06-visible-rim-focus.png`：重点局部对照。
- `grabcut-run1/manifest.json`：前32次实际尝试。
- `real-multi-object/results.json`：2批4个模型输出，完整共享计时。
- `model-env-tests.log`、`targeted-after-review.log`、`full-permitted.log`、`launcher-check.log`：实际测试/启动检查，包括唯一失败。
- `red.log`、`lifecycle-red.log`、`review-red.log`：先失败的测试证据；其余诊断日志及下载中止/依赖复制清单亦保留。
- `freeze.txt`、`local-dependency-copy*.json`：环境复现；权重与照片只在忽略目录，未进 Git。

可提交的脱敏汇总：`reports/B-environment.json`、`reports/B-benchmark-summary.json`。本报告副本放入协调包 `reports/B-交付报告.md`，不修改 BASELINE/INTERFACES 或其他角色报告。
