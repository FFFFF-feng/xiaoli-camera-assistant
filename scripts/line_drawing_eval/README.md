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
  "built_assets": {"mobile/dist/index.html": "<sha256>"},
  "health": {"service": "xiaoli-mobile-api", "analysis_mode": "cloud"},
  "segmentation": {"backend": "grabcut", "device": "cpu"},
  "frozen_at": "<ISO时间>"
}
```

`preflight.verify()` 只读取 Git、netstat、进程命令行、构建散列和 `/health`，
逐项核对提交、分支、dirty 清单、源码散列、端口→PID、构建产物和分割权重；
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

## 计时口径

`timing.py` 使用后端的单调时钟阶段时长，并用 `max(参数, 构图)` 合并并行分支：

```
image_preprocessing + vision + max(parameters, composition)
```

流事件的 `request_started → 首段 content` 是云端首字等待，`content` 之间的
跨度是可见生成时间；两者只用于解释阶段耗时，不重复计入总时长。
