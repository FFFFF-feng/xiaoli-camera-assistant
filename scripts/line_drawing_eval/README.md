# E：独立离线验收工具

默认操作是离线索引、计时重建和静态回放，**正常执行不会发送模型请求**。
E2 发送器只有在同时满足 `--live`、A 的 `INTEGRATION_READY` 门禁和账本余额时
才会启用；总控确认预算与优先级前不要使用 `--live`。

## 运行

```powershell
$taskRepo = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-eval-e'
$env:PYTHONPATH = "$taskRepo;$taskRepo\scripts"
$env:PYTHONUTF8 = '1'
$python = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant\.venv\Scripts\python.exe'
$evidence = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant-latest\.tmp\line-drawing-repair-20261017'
$out = "$taskRepo\.tmp\line-drawing-eval-E-20261018"

& $python -m line_drawing_eval index --evidence $evidence --out $out
& $python -m line_drawing_eval timing --evidence $evidence --out $out
& $python -m line_drawing_eval gallery --evidence $evidence --out $out
& $python -m line_drawing_eval acceptance --ledger '..\并行修复协调包-20261017\reports\E-cloud-ledger.json' --out $out
```

回放服务器与浏览器检查：

```powershell
& $python -m line_drawing_eval.serve "$out\gallery" --port 8123
node "$taskRepo\scripts\line_drawing_eval\browser_replay.cjs" `
  --url http://127.0.0.1:8123/gallery.html --out "$out\browser"
```

`serve` 只响应 GET/HEAD，任何 POST/PUT/PATCH 返回 403 并写入 `access.jsonl`。
`browser_replay.cjs` 在浏览器层再拦截一次：所有非本机请求和非 GET 请求都被
abort，并向 `/api/analyze` 与 `/api/composition/preview` 各发一次故意探针，
用 `blocked_posts == 2` 且 `actual_analysis_posts == 0` 证明拦截生效。

## 存档 manifest 兼容

`index` 和 `gallery` 通过共享读取层同时支持旧 `samples/photos` 与新
`cases/photo`。`photo` 与 `photos` 同时出现时必须指向同一绝对本地路径；
重复 case ID、不同路径、照片数量不为 1、URL 或相对路径都保留为诊断并拒绝选中。

源码身份只读取 summary 和 manifest 中已记录的 `git_sha`、
`source_tree_sha256`、`tracked_diff_sha256` 及对应
`source_fingerprint` 嵌套字段。不同来源冲突时字段置为 unknown 并列出诊断，
不会用当前仓库 HEAD、默认模型或现配置补值；未记录 dirty 状态保持
`unrecorded_by_run_manifest`。gallery 只有在 manifest SHA-256 与实际文件一致时
才展示原图，缺失文件、散列不符和 manifest 冲突分别显示不同原因。

## 账本

`E-cloud-ledger.json` 由 E 独占维护，创建时继承 A 的交接：
8 次总预算、已用 5 次、剩 3 次，内部 `request_started` 22 次、观察协议修复
2 次、外层自动重试 0 次。`Ledger.reserve()` 在发请求前扣减，失败不退还。
`require_live_allowed()` 同时要求显式 `--live` 与 A 的集成门禁文件。

## E2 门禁与试运行

A 在集成完成后写 `INTEGRATION_READY.json`（E 不写、不改服务）：

```json
{
  "status": "INTEGRATION_READY",
  "commit": "<40位SHA>",
  "branch": "<分支>",
  "source_root": "<服务实际使用的源码绝对路径>",
  "source_tree_sha256": "<src/mobile-src/mobile-tests/tests 源码树散列>",
  "dirty_files": ["<按 git status --porcelain 排序后的路径>"],
  "port": 8093,
  "pid": 12345,
  "built_assets": {
    "mobile/dist/index.html": "<sha256>",
    "mobile/dist/assets/<当前index引用的JS文件名>.js": "<sha256>",
    "mobile/dist/assets/<当前index引用的CSS文件名>.css": "<sha256>"
  },
  "health": {"service": "xiaoli-mobile-api", "analysis_mode": "cloud"},
  "segmentation": {"backend": "grabcut", "device": "cpu"},
  "frozen_at": "<ISO时间>"
}
```

`commit` 必须是完整 40 位十六进制 SHA，`frozen_at` 必须是带时区的 ISO 时间。
`health` 至少声明实际 `service` 和 `analysis_mode`。`built_assets` 必须列出当前
`index.html` 以及其中引用的全部本地 JS/MJS/CSS（包括 modulepreload）；空表、缺文件、
漏列引用或散列变化均拒绝。示例中的资产名须替换为本次实际构建名。

源码散列直接复用 `line_drawing_eval.preflight.source_fingerprint(Path(source_root))`。
它覆盖 `src`、`mobile/src`、`mobile/tests`、`tests` 下的 `.py/.mjs/.ts/.vue/.css`；
返回的 `tracked_diff_sha256` 是额外诊断值，当前门禁比较 `source_tree_sha256` 与 dirty
清单。A 应在最终干净提交后冻结，不能把此散列当整个仓库所有配置与脚本的内容证明。

`segmentation.backend` 仅接受 `grabcut` 或 `mobile_sam`，本轮 `device` 仅接受 `cpu`。
GrabCut 的权重字段省略或为 null；显式启用 MobileSAM 时，另填绝对本地 `weights_path`
和真实 `weights_sha256`，预检会重新计算本地文件散列。默认普通启动仍是 GrabCut。

`/health` 必须提供实际运行进程的 `segmentation` 诊断，例如尚未分割时：

```json
{
  "configured_backend": "grabcut",
  "device": "cpu",
  "weights_sha256": null,
  "last_actual_backend": null,
  "last_weights_sha256": null,
  "inference_proven": false
}
```

预检单独核对前三项与门禁配置身份；后三项是最近执行证据，必须如实保留。
`inference_proven: false` 与两个 null 允许配置检查通过，但表示尚无实际分割证明。
MobileSAM 配置下最近实际执行 GrabCut 可以记录为 `last_actual_backend: "grabcut"`、
`last_weights_sha256: null`；这只证明实际 GrabCut 分割，不能称模型成功。实际 MobileSAM
执行须记录相同权重散列。预检将这些字段原样列入 `segmentation` 报告，不发起推理来填证据。

`preflight.verify()` 只读取 Git、netstat、进程命令行、构建散列和 `/health`，
逐项核对提交、分支、dirty 清单、源码散列、端口→PID、构建产物、分割配置与本地权重；
任何一项不符就拒绝开批。E2 发送器：

```powershell
$env:PYTHONPATH = "$taskRepo\scripts"
$python = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant\.venv\Scripts\python.exe'
$args = @(
  '--gate', '..\并行修复协调包-20261017\INTEGRATION_READY.json',
  '--ledger', '..\并行修复协调包-20261017\reports\E-cloud-ledger.json',
  '--manifest', 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant-latest\.tmp\line-drawing-eval-20261017\run_manifest.json',
  '--out', "$taskRepo\.tmp\e2", '--run-name', 'e2-run-1', '--cases', '06,07,02'
)
& $python -m line_drawing_eval.live @args            # 只读预检，不发请求
& $python -m line_drawing_eval.live @args --live     # 显式真实上传
```

不带 `--live` 时只做预检并打印计划；带 `--live` 时先通过门禁和账本检查，
再逐图串行上传。每张图发送前扣减一次网关预算，失败仍计数；传输重试为 0，
不会有外层自动重试。运行目录已存在时拒绝覆盖。
默认预检会执行一次本机 `GET /health`，报告 `health_get_requests: 1`、
`generated_model_requests: 0`；它不修改账本、不创建运行目录，也不 POST。
真实发送器保留 HTTP 非 200、内容类型错误、服务 error 事件各自的固定失败码，
不会被“无 final”通用码覆盖。

## 计时口径

`timing.py` 使用后端的单调时钟阶段时长，并用 `max(参数, 构图)` 合并并行分支：

```
image_preprocessing + vision + max(parameters, composition)
```

流事件的 `request_started → 首段 content` 是云端首字等待，`content` 之间的
跨度是可见生成时间；两者只用于解释阶段耗时，不重复计入总时长。
