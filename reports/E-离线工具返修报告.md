# E 离线证据工具返修报告

角色与状态：**E DONE（离线工具小修）**。本轮未重新开始 E2，未发送照片，未调用模型，
未修改 live 上传、preflight 门禁、产品源码、构建、账本、门禁或当前 8093 服务。

工作树：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-eval-offline-compat`

基线：`12bcccc18e42d47210245b5d195830c7ae5029c0`

分支：`codex/line-drawing-offline-compat`

有序提交：

1. `da6833cb76746f045bc164d0b4f388af2d2cd11d`
   `fix(eval): read stored runs from both manifest schemas`
2. 本报告的文档提交（最终 SHA 由聊天交付摘要给出）。

## 1. 修改文件

- `scripts/line_drawing_eval/manifest.py`（新增共享 manifest/source/原图读取层）
- `scripts/line_drawing_eval/evidence.py`
- `scripts/line_drawing_eval/gallery.py`
- `scripts/line_drawing_eval/README.md`
- `tests/test_line_drawing_eval.py`
- `reports/E-离线工具返修报告.md`

没有修改 `live.py`、`preflight.py`、`ledger.py`、E2 原 `result/events/summary/manifest`、
 `E-cloud-ledger.json`、`INTEGRATION_READY.json` 或产品主工作树。

## 2. 修复内容

### 2.1 manifest 双 schema

`index` 与 `gallery` 现在共用 `normalize_manifest()`：

- 旧格式 `samples[*].photos[]` 与新格式 `cases[*].photo` 均可读取；
- 单个案例必须恰有一张照片；`photo` 和 `photos` 同时出现时必须解析为同一绝对本地路径；
- URL、相对路径、布尔值/非字符串或不能唯一确定案例条目的照片均不选入原图；
- 同 ID 在多段落或段内重复时不做“取一个方便值”的静默选择，案例字段和原图明确 unknown；
- 所有冲突和不可用原因保留在 manifest/case diagnostics 中。

### 2.2 原图验证

共享 `verify_original()` 只在 manifest 记录 SHA-256 和实际文件都一致时返回
`status="verified"`、`usable=true`：

- 文件不存在：`missing_file`；
- 存在但散列不同：`hash_mismatch`；
- 未记录或格式非法：`hash_unrecorded` / `hash_format_invalid`；
- manifest/字段冲突：`manifest_ambiguous`。

只有 `verified` 原图会复制到新 gallery。缺失、散列不符和冲突在页面中分别显示，
不会用同名任意文件补位。

### 2.3 source 身份与说明

`normalize_source()` 只读取保存的 summary/manifest 候选：

- 顶层 `git_sha`、`source_tree_sha256`、`tracked_diff_sha256`；
- summary/manifest 的嵌套 `source_fingerprint.*`。

同一字段来源冲突时置为 unknown，并在 `source.diagnostics` 保留来源值。
未记录 dirty 继续标为 `unrecorded_by_run_manifest`；没有从当前仓库 HEAD、默认模型、
现配置或服务反推历史版本。

`index/gallery` 不再硬编码“所有结果早于 986fd05”。gallery 顶部改为中性说明，
每条卡片显示实际保存的 git/tree/dirty 身份或 unknown。

## 3. 定向验证

```powershell
& $python -B -m pytest -q tests/test_line_drawing_eval.py `
  --basetemp=.tmp\offline-compat-tests -p no:cacheprovider
```

结果：**23 passed，0 failed**。覆盖旧 schema、新 schema、`photo/photos` 一致与冲突、
照片数量歧义、重复 ID、缺失原图、散列不符、字段缺失 unknown、嵌套 source 指纹、
source 冲突和 gallery 中性说明。

```powershell
& $python -B -m ruff check `
  scripts/line_drawing_eval/manifest.py `
  scripts/line_drawing_eval/evidence.py `
  scripts/line_drawing_eval/gallery.py `
  tests/test_line_drawing_eval.py
```

结果：**All checks passed**。

`git diff --check`：通过。没有用完整产品测试代替离线工具定向验证。

## 4. 真实 E2 存档只读重建

输入为 E2 原始存档：
`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-eval-e\.tmp\e2-12bcccc-20261018`

新输出（没有覆盖 E 当时显式修补的 `replay-final`）：

- [gallery](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-eval-e/.tmp/e2-12bcccc-20261018/offline-compat-verified-20261018/gallery.html)
- [gallery receipt](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-eval-e/.tmp/e2-12bcccc-20261018/offline-compat-verified-20261018/gallery-receipt.json)
- [index](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-eval-e/.tmp/e2-12bcccc-20261018/offline-compat-index-20261018/index.json)

结果：

- 3 个运行、3 条存档网关 POST 被索引，新增网关请求 **0**；
- 02、06、07 三张原图均为 `verified`，复制后的资产 SHA-256 与原 manifest 一致；
- gallery 含 3 个经过核对的原图 `<img>`，无“原图缺失”或“散列不符”提示；
- 三份 source 均显示
  `12bcccc18e42d47210245b5d195830c7ae5029c0` 与 tree
  `f707fe1d911376917b9cf5a38de1cecfc63088cbac9f7c5767f28f43de566e1e`；
- dirty 如实为 `unrecorded_by_run_manifest`；
- 页面不含 `986fd059` 或“历史早于检查点”的硬编码断言；
- 每份 index 的 `generated_model_requests` 为 0。

## 5. 新增调用与边界

- 新增真实云网关请求：**0**
- 新增内部模型请求：**0**
- 新增观察协议修复：**0**
- 新增外层重试：**0**
- 未启动回放 HTTP server，未访问 8093，未改 E 账本或 A 门禁

剩余限制：provider model id、raw mask 等未记录事实仍保持 unknown；旧证据没有 dirty
状态时不会推测；该工具修复不改变任何 E2 人工画面结论。

## 6. 交接 A

A 按上述顺序集成两个提交即可。若只集成代码提交而不集成报告，不影响运行；报告提交仅记录
兼容策略和验证证据。该分支未 push、未合 main、未部署。
