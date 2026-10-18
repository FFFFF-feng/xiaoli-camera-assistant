# 可选 MobileSAM 分割后端

默认 `grabcut` 保持普通启动不依赖 Torch、MobileSAM 或权重。MobileSAM 只在显式配置后使用，目前只验证 CPU；连续山湖/建筑主体仍走 `scene_structure`。模型返回 `mask_extracted` 只证明掩码基础契约通过，不是最终轮廓、摄影建议或画面质量验收。

## 环境与安装复现

产品的完整环境先安装 `.[mobile]`，再选择安装本仓库的 CPU 可选依赖文件。以下是供维护者主动执行的复现步骤，本轮集成不执行安装；正常 CMD 启动也不会执行安装或下载。

```powershell
python -m venv .venv
$productPython = (Resolve-Path .venv/Scripts/python.exe).Path
& $productPython -m pip install -e '.[mobile]'
& $productPython -m pip install -r requirements-segmentation-cpu.txt
& $productPython -m pip check
```

固定版本为 Torch **2.10.0+cpu**、torchvision **0.25.0+cpu**、timm **0.9.12**、NumPy **2.5.2**、Pillow **12.3.0**、OpenCV headless **4.14.0.94**。MobileSAM 使用官方源码提交 `f706ad9c4eb7f219c00d9050e46328518ffb65d2`，vit_t 模型，发行包名称 `mobile_sam`，版本1.0。CPU wheel 取自 PyTorch 官方 CPU 索引；MobileSAM 安装需要 Git。首次安装会联网获取依赖，所需空间与下载时间不属于推理耗时。

该文件固定模型的关键直接依赖，不是产品全量传递依赖锁文件。新建完整产品环境仍需 `pip check` 和本地模型/产品回归；未实际安装验证的环境不能写成已经通过。

B 的已验证环境是 Python **3.13.12** 的独立 venv：`xiaoli-segmentation-adapter/.tmp/B-segmentation/venv`，仅包含分割基准需要的依赖，**没有完整产品的 FastAPI/Pydantic**。不能直接把这个 venv 当完整产品环境启动，也不能把其 site-packages 注入产品来冒充可复现安装。默认产品继续使用原有产品 venv；它没有 Torch，也能启动 GrabCut。没有本轮新装依赖或 GPU 验证。

## 本地权重与显式配置

权重从固定 MobileSAM 提交的 `weights/mobile_sam.pt` 获取后放在本机忽略目录；运行时没有下载路径。参考来源为 [MobileSAM 固定提交](https://github.com/ChaoningZhang/MobileSAM/tree/f706ad9c4eb7f219c00d9050e46328518ffb65d2)。仓库声明 Apache-2.0；权重随仓库分发，不额外推断独立权重许可。

B 本机实际权重位于其工作树 `.tmp/B-segmentation/MobileSAM/weights/mobile_sam.pt`，40,728,226字节。产品可使用已经核对的绝对本地路径，或将同一文件放到产品 `.tmp/models/mobile_sam.pt`；本轮不复制或重新下载。真实 SHA-256 为：

```text
6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f
```

在当前 PowerShell 会话显式配置；不需要改私有 `.env`：

```powershell
$env:CAMERA_AI_SEGMENTATION_BACKEND = 'mobile_sam'
$env:CAMERA_AI_SEGMENTATION_WEIGHTS_PATH = (Resolve-Path '.tmp/models/mobile_sam.pt').Path
$env:CAMERA_AI_SEGMENTATION_WEIGHTS_SHA256 = '6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f'
$env:CAMERA_AI_SEGMENTATION_DEVICE = 'cpu'
$env:CAMERA_AI_SEGMENTATION_FALLBACK = 'true'
$env:CAMERA_AI_SEGMENTATION_TIMEOUT_SECONDS = '10'
$env:CAMERA_AI_SEGMENTATION_EVIDENCE = 'false'
.\启动项目.cmd --check
```

`FALLBACK=true` 时缺依赖、缺/坏权重等可用性问题会给出脱敏固定码，并允许启动后按真实情况回退 GrabCut；最终分析记录请求后端、实际后端、权重版本和原因。`FALLBACK=false` 时预检失败会停止启动。非法配置、非CPU设备不被 Settings 接受，始终停止并给固定原因，避免预检通过后产品无法启动。不要把回退计为模型成功。

`--check` 只解析分割配置、发现依赖位置并以有界读取核对本地权重 SHA-256，**不导入 Torch、不加载或反序列化模型、不证明推理可用性**。权重检查上限128MiB，实际加载仍由可选 runtime 做 `weights_only=True` 和严格状态字典检查。启动预检既不读取云凭据库，也不输出配置原始值或权重路径。真实模型版本与设备应结合后续本地运行结果/健康诊断验证；健康中的配置声明不能当作模型执行证据。

## 资源、超时与预处理

每个服务生命周期复用一个 runtime，同一归一 RGB 上一次编码、多个区域解码，排队最多0.5秒。配置/权重改变会等待旧 native 调用结束并关闭旧资源后重建，不按对象重复加载模型。缓存键包含实际权重内容散列、模型/预处理/算法版本、设备、图像和区域元数据；失败不作为成功缓存。关闭资源不承诺 CPU 分配器立即将 RSS 降为零。

`TIMEOUT_SECONDS=10` 是**native 阶段边界超时**。在途 load/encode/decode 可能超过10秒才返回；期间槽不会释放，close 也会等待。当前没有可回收 worker 的硬截止保证，不宣称10秒硬中断。同步推理应通过现有线程池运行，不能直接占用异步事件循环。

官方 SamPredictor 使用 RGB、最长边1024、归一化与补边；网络在**连续 logits**上做原生插值/裁剪，然后阈值化得到原图 bool mask。B 在恢复**已经二值化的 mask**尺寸时使用最近邻。两者不是同一种插值对象；没有修改网络原生重建，也不填孔、补杯底、补画外杯把或强制只留最大分量。

## 本地中间证据与仍未解决的质量问题

证据开关默认关闭。显式开启 `CAMERA_AI_SEGMENTATION_EVIDENCE=true` 后，证据仅写产品自身 `.tmp/segmentation-evidence`，最多32条/64MiB；不保存原照片或 embedding。关联 JSON 记录输入散列、每对象 mask 来源后端、实际轮廓后端、权重版本与固定失败码，另存 mask PNG、轮廓 JSON、source geometry SVG。SVG只是传入源轮廓预览，不能替代最终目标布局的实际线绘验收。导出失败返回明确缺口，不能声称掩码质量已经验收。权重、证据和临时环境都不进入 Git。

已知模型杯底可见末端丢失、杯沿误孔，以及狗耳/眼/球内部辨识线不足仍需原图和最终线绘核对；没有逐像素真值 IoU，不根据孔面积给准确率排名。GrabCut 继续作为默认后端。本阶段不发送真实云请求，不因此消耗 E 的剩余云额度。

同一进程先关闭证据运行、再开启证据重放相同输入时，几何缓存命中不会重新生成掩码。诊断标记 cache_hit；维护者应在新的独立离线进程采集证据，或明确报告 mask 不可用。连续开放结构本身没有二值分割 mask，不为凑齐材料制造掩码。
