# B：分割接口与离线比较

只实现 `segmentation-v1` 独立模块。没有接入产品，也不运行云服务。

## 依赖与安装

模块导入只需要项目已有 NumPy。MobileSAM 按需导入；没有权重或依赖时返回固定失败，不自动安装、下载或降级。不要升级根依赖。B 的独立环境在 `.tmp/B-segmentation/venv`，pip 临时目录也在 `.tmp/B-segmentation/temp`，避免 Windows 沙箱 TEMP 写入失败。

官方来源：[MobileSAM](https://github.com/ChaoningZhang/MobileSAM)，本次源码固定 `f706ad9c4eb7f219c00d9050e46328518ffb65d2`。仓库声明 Apache-2.0，`weights/mobile_sam.pt` 随仓库提供；本次不另行推断权重有额外许可。只使用 vit_t，绝不加载 large。SAM 2 未实施，官方 [安装说明](https://github.com/facebookresearch/sam2/blob/main/INSTALL.md) 推荐 Linux/Windows WSL；没有比较结果就不排名。

重现环境准备（从本工作树执行；最终实际版本见 B 报告）：

```powershell
New-Item -ItemType Directory -Force .tmp/B-segmentation/temp | Out-Null
$env:TEMP=(Resolve-Path .tmp/B-segmentation/temp).Path
$env:TMP=$env:TEMP
$env:PYTHONUTF8='1'
python -m venv .tmp/B-segmentation/venv
$bPython=(Resolve-Path .tmp/B-segmentation/venv/Scripts/python.exe).Path
& $bPython -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
& $bPython -m pip install numpy==2.5.4 Pillow==12.3.0 opencv-python-headless==4.14.0.94 timm==0.9.12 psutil==7.2.2 pytest==9.1.1 setuptools
git clone --depth 1 --filter=blob:none --sparse https://github.com/ChaoningZhang/MobileSAM.git .tmp/B-segmentation/MobileSAM
git -C .tmp/B-segmentation/MobileSAM fetch --depth 1 origin f706ad9c4eb7f219c00d9050e46328518ffb65d2
git -C .tmp/B-segmentation/MobileSAM checkout --detach f706ad9c4eb7f219c00d9050e46328518ffb65d2
git -C .tmp/B-segmentation/MobileSAM sparse-checkout set mobile_sam weights
& $bPython -m pip install --no-deps --no-build-isolation .tmp/B-segmentation/MobileSAM
```

以上安装显式联网获取开源依赖/权重，与真实云推理请求不同。正常 `segment_many` 无网络路径。不要把共享 `.launcher` 加入模型环境的 PYTHONPATH；只加本工作树 `src`。

## 输入、输出、资源与超时

冻结签名见 `docs/line-drawing-contract-v1.md`；最小接入代码见 `integration_example.py`。构造器可指定本地 `weights_path`、`device`、预期 `expected_sha256`；`backend_factory` 是实现同一 backend protocol 的显式插件入口。所有模型创建与推理都在锁内，最多一个模型实例，一个推理槽，一个内容键控的 embedding。排队最多 0.5 秒。多框共用一次编码，按输入顺序返回，部分非法框不影响同批合法框。空批返回空列表；非法 object_id 使用 `invalid_bbox`（冻结协议没有单独 id 错误码）。

没有结果缓存；相同图内容/尺寸/完整有效框与参数/权重/模型/预处理版本才复用一次 embedding，仍重新解码。框变化保守地使 embedding 失效。任何分割失败会清理 embedding；返回 mask 是独立副本。跨请求照片/embedding 不写磁盘；`close()` 幂等，等待当前推理结束再释放。reset 异常使运行时停止接收后续推理，防止使用未知状态。

**超时是阶段边界检查，不是硬取消。** Native load/encode/decode 不可中断，可能超过 timeout_seconds 后才返回 `inference_timeout`；期间一直持有槽。close 同样可能等待。若 A 的 HTTP 服务要求硬截止，需要 A 在可回收独立进程内运行，不能把本接口当硬实时保障。total 为整批墙钟秒；queue/load/encode 同批共享，decode/postprocess 为对应对象，不能把每个结果的共享阶段相加。

模型预处理使用官方 SamPredictor：RGB、最长边 1024、像素归一化、补边。官方模型在**连续 logits** 层做自己的插值与裁剪，再阈值化为原图尺寸 bool；B 不改神经网络的 logits 重建。B 层若需要恢复**二值 mask** 尺寸，严格用最近邻；不填孔、不强制取最大连通分量，不补造画外区域。此解释需 A 接入时知悉：若冻结契约要求连 logits 也只能最近邻，则当前官方预处理不满足该更强解释，应由 A 决定契约澄清，不能隐瞒。

默认请求 3 个模型候选，剔除空/全图/非法分数，选有限预测 IoU 分数最高者，同分按最小下标。`selection_basis` 明示 `not_accuracy`，模型分数不是实际 IoU。失败也记录实际候选数。

## 离线基准

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
& $bPython scripts/segmentation_benchmark/benchmark.py --photos '../知识库测试图片-20261014/images' --weights '.tmp/B-segmentation/MobileSAM/weights/mobile_sam.pt' --device cpu --output '.tmp/B-segmentation/model-run1'
& $bPython -m pytest -q tests/test_segmentation_*.py --basetemp .tmp/B-segmentation/pytest
```

输出目录必须不存在，禁止覆盖旧失败。每次尝试立即写 manifest；四图各 720/1280、旧 GrabCut/检查点 GrabCut/单个候选、每条件两次。没有真值，因此无 IoU。狗/杯框来自 A 保存的人工冻结区域；山湖/走廊为 B 人工适用性观察框。两次模型调用中第二次是编码缓存命中，应单列，不能称完整热编码速度。

GrabCut 对照从两个固定提交提取 `_trace_single` 中生成 foreground 为止的 AST 前缀，完全保留对应初始化/迭代参数。记录源文件散列；不执行后续简化/细节阶段。这是 mask 条件比较，不是旧线上失败重放。纯轮廓预览是原始像素边界，不是最终线绘/新构图。A 的下游当前仍选择 primary、简化为 64 点、对 holes/contours 有联合限制，因此好 mask 的细腿/孔隙仍可能丢失。
