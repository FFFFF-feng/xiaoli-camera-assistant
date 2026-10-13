# 五图人工确认包（2026-10-13）

最终可编辑派生记录、435项通过的全量测试及实际浏览器核验见 [前置修复交付报告](detector-preacceptance-repair-2026-10-13.md)。本文件的旧来源ID用于溯源；用户编辑请采用最终 `history_registration_final/` 映射，B02初始run_id为 `26eb2769a600470194ffc87b58fb0a13`。

已从上一轮冻结文件离线生成五图确认包。入口默认 B02，先展示原图和编号 AI 草稿，再通过独立链接打开已有模型预测。没有调用 API、运行检测器、下载模型或升级人工确认。原 10 图共 119 项 AI 草稿仍完整保留；本包只提取其中 5 图的 32 项，均为 `annotation_source=ai / confirmed=false / complete=false`。

项目目录为 `C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant`。下列相对链接均位于该项目内。

- [确认入口：B02 开始](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/index.html)
- [32项简明确认表 CSV](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/confirmation_table.csv)
- [具体旧记录映射 JSON](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/source_runs.json) / [CSV](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/source_runs.csv)
- [已有模型预测独立视图](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/predictions.html)
- [输入和输出哈希清单](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/manifest.json)
- [离线完整性核验](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/integrity_check.json)

| 图片 | 待确认项 | 必需草稿项 | 保留的完整任务范围 |
|---|---:|---:|---|
| B02 | 3 | 2 | 杯整体、杯中可见内容区域；杯口内视区域保留为独立可选解释 |
| D03 | 9 | 7 | 器具整体、盒体、上方触边细杆、右伸四根管；开口区域和四管组合保留 |
| D07 | 4 | 4 | 两手分别为部件、泥坯可见整体、陶轮可见区域 |
| C03 | 2 | 1 | 描绘人物候选、广告牌父对象上下文；现场人物遗漏与实体归属待核对 |
| P06 | 14 | 13 | 逐个人物、不确定人物簇、疑似蓝色片段、尺度岩台上下文；未指定唯一主角 |

必需项合计 27，其中 P06 的 2 项仍是 `ignore=true / judgeable=false` 草稿范围。它们保留在确认表和 JSON，不把未知人数从任务中删除，也不把 32 项当成完整人物数量或已确认评分分母。C03 广告牌、P06 岩台仍保留 `out_of_scope=true` 上下文，未经用户回复不调整原范围字段。

每图目录包含原始照片字节 `original.jpg`、方向修正图 `corrected.png`、实际发送 JPEG `sent.jpg`、原图/发送图编号草稿 `reference_original.png / reference_sent.png`、各对象局部放大 `focus_01.png` 等、简明中文确认表和 `manifest.json`。局部放大仅由 Pillow 裁切、缩放、画框；没有生成或修改照片事实。

## 导入与确认

可直接粘贴到当前“参考框 JSON”的文件是各图的 `reference.json`：

- [B02参考](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/B02/reference.json)
- [D03参考](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/D03/reference.json)
- [D07参考](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/D07/reference.json)
- [C03参考](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/C03/reference.json)
- [P06参考](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/P06/reference.json)

这些文件是 `DetectorReference` 根对象，逐项语义、坐标、层级、父 ID、required、实体、ignore、out_of_scope 与冻结草稿内 `reference` 一致。外层 `ai-reference-draft-v1`、本包 `manifest.json` 和确认表不能当作 UI 参考 JSON 导入。

在 [8502测试工具](http://127.0.0.1:8502/) 的“检测与联合定位”中，优先打开本次建立的可编辑派生记录；旧 run 映射仅供识别来源。展开“人工参考框（不进入推理）→批量导入 / 编辑参考 JSON”，粘贴对应文件，点“应用参考 JSON”。按编号逐项核对并保存到新参考版本和确认日志，保留 AI 原始来源。不要在旧原始实验 run 上覆盖保存。

每项只需判断：是否存在/是哪一个；可见边界是否完整或怎样改；整体、部件、实例、区域或组合；是否主目标/必需/辅助/背景；实体归属或无法判定。对未回复字段与对象保持待定。例：“B02-1存在，整体边界确认，主目标且必需，现场实体；B02-2边界需改……”。只确认 B02-1 不代表确认 B02 完整任务，更不代表确认全部 119 项。只选择小目标诊断时必须另外保存 `evaluation_scope` 和参考版本，不能替代原完整任务成绩。

## 可重开的旧来源

下表为建议首先定位的 v1 paired 源记录。每条含 A、B1、B2 三方法，正式提示版本为 `localization-prompt-v2`。所有旧 v0/v1/v2 和纯检测来源均在映射文件中，合计 14 个 run、40 个方法行。

| 图片 | experiment_version | run_id |
|---|---|---|
| B02 | iteration_20261013_01:v1:B02:paired | e4310f590574470b96746ce6d4ceff0c |
| D03 | iteration_20261013_01:v1:D03:paired | 6c8b294b9b974d3bbc466ce377ec6cb1 |
| D07 | iteration_20261013_01:v1:D07:paired | 3fa3b4683469412ca9b14ce15db9b2e7 |
| C03 | iteration_20261013_01:v1:C03:paired | d2496f114fc74766993635993fe14942 |
| P06 | iteration_20261013_01:v1:P06:paired | aa666dd231ab4adc961eb201b1c7d675 |

`source_runs.json.rows` 每方法记录完整 `run_id / result_id / version / condition / method / detector / experiment_version`、只读来源 run 路径及哈希、历史 store 路径、可重开照片路径、原图/发送图路径、可导入参考路径和候选叠框路径。`recommended_initial=true` 表示该图 v1 paired 来源，B02 排首位；具体派生历史及确认日志由独立的保存流程管理。

## 已验证边界

当前 `DetectorReference / GroundTruth` 为 strict schema，没有图像哈希、参考版本、字段级确认文字/时间、`evaluation_scope` 或未决人数区间字段。因此这些信息保留在独立 manifest sidecar；不能追加到参考根对象。当前正式评价必须 `reference.complete=true` 且所有对象逐项 confirmed，部分确认的质量字段继续未评测。没有通过删除未知项、改 `complete` 或强制配对绕开限制。

原始和发送 JPEG 哈希使用文件字节 SHA256。当前 `images.prepare_image` 的 `corrected_sha256` 使用 `SHA256(str(RGB.size).encode() + RGB.tobytes())`，不是 PNG 文件哈希；本包分别核对该像素摘要和 `corrected_png_file_sha256`，保留原字段含义。编号框坐标基于方向修正图的归一化 xyxy，原图叠框先应用 EXIF 方向，发送图沿用同一归一化坐标。

离线核验通过 5 份参考 schema 校验和与原草稿的逐字段一致检查，核对 84 个来源文件摘要、82 个包文件摘要、166 个本地链接和 60 个 HTML 图像资源，全部存在且来源摘要未变。每个映射的旧历史 JSON 和照片路径均存在。已目视检查五张原图编号叠框；P06 提供逐对象局部放大以辨认拥挤编号。静态完整性与图片检查不等同于 HTML 浏览器渲染验收，也不是人工照片确认。

## 重新生成与离线测试

```powershell
$env:TEMP = Join-Path $PWD '.tmp/confirmation-agent'
$env:TMP = $env:TEMP
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
.venv/Scripts/python.exe scripts/prepare_detector_confirmation.py
.venv/Scripts/python.exe -m pytest tests/test_detector_confirmation.py --basetemp=.tmp/confirmation-agent/pytest-confirmation -q
.venv/Scripts/python.exe -m ruff check scripts/prepare_detector_confirmation.py tests/test_detector_confirmation.py
```

已有文件字节完全一致时生成器复用它；任何不同内容旧输出导致整批预写检查拒绝，不覆盖也不删除。需要修订包时用 `--output` 指向一个新的独立子目录并保留旧版本。导出器只读来源，不导入 runner、模型 client 或 worker。

8 个离线测试覆盖：完整参考/未知/ignore/父关系及未决人数保留、EXIF方向、不同PNG文件摘要与像素摘要、重复生成字节稳定、冲突旧输出预写拒绝且不留半包、图哈希冲突、共同任务冲突、禁止重置已确认字段。测试已先观察失败再实现；测试模拟证据不计真实质量。全项目检查结果由本次前置修复主报告统一记录。
