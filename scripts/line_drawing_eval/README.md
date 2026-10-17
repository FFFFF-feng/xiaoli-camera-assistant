# E：独立离线验收工具

本目录只读取已经保存的分析结果，**不包含任何发送模型请求的代码路径**。
默认操作是离线索引、计时重建和静态回放；真实云上传属于 E2，必须等 A 发布
`INTEGRATION_READY`、总控确认预算与优先级后另行实现并受账本门禁约束。

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

## 计时口径

`timing.py` 使用后端的单调时钟阶段时长，并用 `max(参数, 构图)` 合并并行分支：

```
image_preprocessing + vision + max(parameters, composition)
```

流事件的 `request_started → 首段 content` 是云端首字等待，`content` 之间的
跨度是可见生成时间；两者只用于解释阶段耗时，不重复计入总时长。
