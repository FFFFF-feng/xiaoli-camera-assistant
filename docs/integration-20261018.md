# A 顺序集成说明

完整继承 C 三提交、D 四提交、B 三提交、E 五提交。原始 SHA、对应集成 SHA、最终服务身份和验证数字由协调包 `reports/A-集成验收报告.md` 与 `INTEGRATION_READY.json` 记录。这里只说明产品契约和证据边界。

## 摄影事实与前端

`build_photography_facts` 在 scene partial 前只调用一次。未由用户确认的运动/光源添加不确定性，保留视觉标签；同一个 frozen 实例继续通过独立 `copy_context` 进入两个并行建议分支。C 的 ready/汇合幂等复核、连续场景原取景约束均继承。

D 的几何契约、单调计时、固定事件时刻和隔离回放完整继承；没有把页面等待显示改进称为完整分析提速。参数/构图并行、连接复用、NDJSON、完整构图 ready、最终才存历史、轮廓缓存、Worker、浏览器有界缓存和 Canvas 回退保持。

## 可选分割与最终诊断

默认 GrabCut；MobileSAM 仅显式配置，安装与资源说明见 `optional-segmentation.md`。一次 `segment_many` 使用相同最长边1280的归一 RGB，所有合格 bbox 共用编码。连续场景主体走 `scene_structure`，背景走实际开放边界，花簇分部继续明确使用 GrabCut。没有按错误 kind 强制换模型。

模型 mask 后仍校验来源区域、覆盖、有效面积、轮廓简化和自交。模型显著分离分量当前不能在“单外环+孔隙”契约中完整表达时固定失败 `mask_multiple_components`，不静默取最大块；小噪声分量单列数量/像素。孔隙超额或无法简化时失败，不通用填洞或补杯底。原生连续 logits 按官方网络插值后阈值化；已二值化 mask 尺寸恢复严格最近邻。

`ObservedScene.processing` 是可选、最多四行的本地执行信息；观察输入强制清空该字段，观察 Schema 不要求模型生成它。每行包括 object_id、requested_backend、actual_backend、mask_backend、code、fallback_code、model_version、weights_sha256、device、timings、cache_hit 和分量统计。通过 `CompositionDiagnostic.segmentation` 进入最终结果和 ready 的 diagnostics。旧结果缺该字段继续兼容。

实际绘制可为 grabcut/mobile_sam/scene_structure/scene_context/none。模型缺失或不合格若回退，显式记录实际后端和原因；失败与失败后的 GrabCut 回退不进模型成功缓存。缓存包含实际权重内容散列、算法/预处理/处理尺寸/观察元数据；缓存命中标 cache_hit，不作为新的 native 推理证明。

健康接口仅暴露必要配置和最近真实分割调用：configured_backend、device、weights_sha256、last_actual_backend、last_weights_sha256、inference_proven 等。开放结构/环境线不冒充模型推理，也不覆盖最近分割调用。进程重启后 inference_proven=false 是诚实的“尚未在此进程推理”；独立离线运行证明不能替代活服务执行证明。每次最终分析以该请求 diagnostics 为准，健康的最近调用不是逐请求证据。

同步 native 推理运行在线程池，阶段边界超时不能中断在途 native；超时期间槽不提前释放，shutdown 在线程池等待 close。没有承诺10秒硬截止。

## 本地证据与门禁

中间证据默认关闭。开启时仅在忽略目录 `.tmp/segmentation-evidence` 生成真实 mask、源轮廓 SVG/JSON 和关联 manifest，32条/64MiB；默认不持久化照片。GrabCut foreground 仅在证据开关打开时捕获。模型失败后回退，保留原模型 mask 时将 mask_backend=mobile_sam、最终轮廓实际后端=grabcut 分开记录。连续开放结构没有二值分割 mask，不能为凑齐材料制造一个。

源轮廓 SVG 不等于最终目标板。独立离线工具以冻结观察输入调用当前 trace 和真实 solve_layout，另存最终板、旧版本板、原图对照与关联信息；该工具显式复制本地测试照片到忽略证据目录，属于维护者主动的照片回放。不会自动上传，不代表新版本完整云验收或新的观察成功率。

A 接手 E 门禁维护后另行修复：保留具体 HTTP/协议失败码，拒绝空健康/资产清单，要求40位 SHA、带时区冻结时间及当前 index 引用的 JS/CSS。配置一致性和真实执行证据分开核对。门禁 `health` 保存稳定服务字段，动态最近执行信息由专门分割检查核对，避免下一次合法分析使冻结身份失效。源码散列口径复用 E 的 `source_fingerprint`；配置/启动脚本等覆盖外文件还依赖干净提交与交付清单。

门禁就绪只表示可交总控安排 E2 独立验收。没有新的真实云请求，历史5/8、剩3不变；06→07→02仍待总控确认，08同版本未测。没有四图最终验收分母，也没有严格提速百分比。
