# 观察证据与离线诊断

`composition.observations` 是读者摘要，不是识别输入。当前摘要由已校验的结构化对象、实际提取状态和缺失对象生成，在 ready/final 之前绑定；它不证明对象名称或摄影质量正确。未可靠绘出的物体会明确出现在图例说明中。

类别一致性只处理明确的日常物体名称与宽泛类别冲突，并保留 `category_adaptation.original_kind / normalized_kind / reason`。建筑造型、背景角色和多义名称不会被一律改成物体。原始识别提示及本地规范化是两层事实。

默认不保存观察记录。显式设置 `CAMERA_AI_COMPOSITION_REPLAY=1` 时，复用本地 `.tmp/composition-replay`，版本 `composition-replay-v3` 以最终构图的 `trace_id`、模型图像SHA-256关联：接收时的有界枚举/bbox投影、规范化metadata、提取结果及固定失败码。不保存照片、请求正文、密钥或原始思考。仅保留32份、每份512KiB、总16MiB；几何过大时保留metadata并标记extracted_omitted，诊断IO失败不改变业务或重试策略。

旧记录没有trace关联时不能仅因图像SHA相同就当作某次新请求输入。E2未留存的识别bbox或mask不能由提取后的source_bbox补造；离线重建须标reconstructed并列出缺失字段。

小道具只在首次GrabCut为空/不足时增加至多一个真实颜色对比种子候选，限制ROI面积、160像素patch边长、2次native迭代，并在native阶段边界检查350ms预算；不承诺可中断在途OpenCV。主体识别框周围最多2个工作像素保持不确定，不扩大整片ROI吞入邻近主体。诊断保留原失败码、local_attempts和耗时，发生重试的结果不进入成功缓存。

宠物二值mask的内部空腔只有得到与外部背景像素一致的第二线索才作为透明孔；其他空腔保留边界细节，不生成眼点或模板部件。颜色相似并不能完全消除歧义，仍需人工查看；MobileSAM保持原显式可选契约。
