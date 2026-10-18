# D 交付报告：前端线绘、兼容与过程反馈

角色与状态：**DONE**

工作树绝对路径：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-line-drawing-frontend`

基线 SHA / 分支：`986fd0594150dce96b3255c8cc77ff54e8174620` / `codex/line-drawing-frontend`

交付提交范围：`986fd0594150dce96b3255c8cc77ff54e8174620..HEAD`

- `7c8f649` fix(frontend): align composition validation with backend contract
- `3320f73` fix(frontend): separate live elapsed time from fixed event timestamps
- `4fd03c0` test(frontend): add isolated line-drawing visual replay harness
- 本报告提交为交付链末端，最终 SHA 在聊天摘要中列明。

## 1. 修改文件

- `mobile/src/target-board.mjs`
- `mobile/src/App.vue`
- `mobile/src/progress-timing.mjs`（新增）
- `mobile/tests/target-board.test.mjs`
- `mobile/tests/completed-composition.test.mjs`
- `mobile/tests/progress-timing.test.mjs`（新增）
- `mobile/tests/visual/target-board.html`（新增，仅测试/回放页面）
- `mobile/tests/visual/target-board.js`（新增，仅测试/回放页面）
- `reports/D-交付报告.md`

未修改后端 schema、几何核心、根依赖、启动器或共享配置。

## 2. 已证实问题与修复

### 2.1 `scene_structure` 前端校验弱于后端

已证实前端原先接受只有一条开放线、双轴覆盖不足或 `mobility=movable` 的连续场景。现与 `TargetLayer.meaningful_outline` 的实际规则对齐：

- `details` 至少 4 条；
- `details` 的 x、y 跨度各至少 0.5；
- `mobility` 必须为 `fixed`；
- `outline`、`contours`、`holes` 必须为空；
- `source_details` 至少 4 条且同样覆盖双轴，确保“原始物体布局”对照不会只剩一条线。

边界用例验证了恰好 0.5 的覆盖有效，`0.499...` 级不足会失败。旧 `legacy` 闭合主体不要求新字段，继续兼容。

### 2.2 `holes` 与 `contours` 同时非空

后端明确拒绝二者并用。前端现在同步拒绝，并在 `silhouetteLayers()` 再做一层防御：即使调用方误传无效组合，也不会把外环与分部拼成填色岛。

- 单外环 + 真实孔：保留为一个复合路径，`evenodd` 透明孔。
- 多个实心分部：每个分部独立路径，不在分部之间连片填色。
- 旧记录缺少 `holes`/`contours`：按空数组兼容。

### 2.3 孔径、多轮廓与连续场景的真实渲染

- 孔隙路径使用 `fill-rule=evenodd`，SVG 与 Canvas 共用同一 `outlinePath()`。
- 开放环境线与 `scene_structure` 不产生闭合外环，不调用填色轮廓；内部细节路径不补 `Z`，明确曲线也不对开放结构做圆角闭合。
- `scene_structure` 禁用背景延伸模式，避免把未知区域伪装成已拍到的背景。
- 原图对照与推荐布局共用同一组几何，仅包围盒不同；场景配色要求所有 main 主体共用同一 sx/sy/tx/ty，发现旧记录独立移动主体时不叠加错误整图配色。

### 2.4 计时语义

新增 `progress-timing.mjs`，把两类时间分开：

- 页面总用时与“当前状态已持续”来自单调时钟，等待期间持续递增；
- 进度记录中的 `elapsed_seconds` 是固定的服务事件时刻，重复渲染不会增长，也不能当作阶段耗时；
- 并行环节仍明确提示不能直接相加。

未增加假精确百分比；现有 0–4 环节进度保持“按环节”而非伪造百分比。

### 2.5 ready/final、历史、Worker/Canvas 回退与旧任务隔离

保留原实现，未改变协议：

- 只有 `completedComposition()` 通过布局完成、`local_v1`、来源图、来源物体和前端可信校验的 `composition_ready` 才提前显示；
- 部分文字事件只进入部分结果，最终 `result` 才写历史；
- `composition_ready` 后若最终分析失败，仍显示失败，不假定已保存历史；
- Worker 配色/背景延伸、Canvas 回退、有界缓存、`createLatestTask` 与预览组件 revision 均保留。

## 3. 契约对齐证据

样例：`tests/fixtures/composition_contract_v1.json`

后端实际校验（本工作树源码）：

```text
C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-line-drawing-frontend\src\camera_assistant\__init__.py
valid {'legacy': True, 'silhouette_hole': True, 'continuous': True}
invalid {'context_main': False, 'outside_hole': False, 'closed_scene': False, 'missing_source': False}
failure_advice False
```

前端 `usableTargetBoard()` 对同一 fixture 的结果与后端一致：3 个有效样例全部接受，4 个无效样例与 `failure_advice` 全部拒绝。该断言已固化在 `mobile/tests/target-board.test.mjs`。

需要 A 接入的接口：无新增后端调用点。A 只需按顺序整合上述提交；前端继续消费既有 `TargetBoard` 字段。

## 4. 验证命令与结果

### 前端完整测试

```powershell
cd C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-line-drawing-frontend\mobile
npm.cmd test
```

结果：**98 tests / 98 pass / 0 fail**。

覆盖重点：

- 契约 fixture 3 有效、4 无效与失败建议；
- 连续场景 4 条下限、双轴 0.5 边界、`fixed`；
- 孔 + 多轮廓拒绝；
- 旧 `legacy` 与缺省新字段兼容；
- ready 与 final 同源、坏 ready 事件忽略；
- Worker/Canvas 回退、缓存去重、有界淘汰、旧 revision 不覆盖新结果；
- 单调总用时、固定事件时刻与当前状态持续时间。

### 生产构建

```powershell
npm.cmd run build
```

结果：`vue-tsc --noEmit` 通过；Vite 构建成功，61 modules transformed，生成 `dist/`。

### 后端定向回归（只读核对，不改后端）

```powershell
python -m pytest -q tests/test_scene_structure.py tests/test_observed_composition.py
```

结果：**35 passed**。

### 隔离浏览器回放

- 预览地址：`http://127.0.0.1:5199/tests/visual/target-board.html`
- 使用本工作树自己的 Vite 进程，未重启共享 8093。
- 1440px 与 390px 两种视口，逐样例检查 `document.scrollWidth - innerWidth`，全部为 **0**。
- 控制台错误：**0**。
- 分析 POST / 预演 POST：**0**；所有 `/api/**` 请求被拦截，真实云完整请求 **0**，内部模型请求 **0**。

真实结果回放：

- 狗：`02/result.json` 经 `completedComposition()` 和 `usableTargetBoard()` 回放，1 个闭合主体轮廓、96 条细节线，场景配色成功。
- 杯子：`06` 失败结果回放，只显示原图与失败说明，SVG 数为 0，无占位主体。

合成契约样例（明确标注，不作为照片效果证据）：

- 孔隙：单外环 + 1 个真实三角孔；
- 多轮廓：2 个独立实心分部；
- 连续场景：4 条开放结构线，双轴覆盖满足契约。

### 像素与 SVG 检查

- 孔隙中心像素 `(245,248,246)` 为底层背景，外环填色为 `(207,219,227)`，证明孔未被填实。
- 多轮廓左/右分部均为 `(207,219,227)`，中间空隙为 `(245,248,246)`，未跨空隙连片。
- 连续场景内部为 `(245,248,246)`，中心仅命中线条颜色 `(83,105,126)`；主结构轮廓填色路径数为 0。
- 狗场景主体填色约占 SVG 画面 15.4%，不是整片画布填色。
- 8 个导出 SVG 全部可被 XML 解析，无 `NaN`/`Infinity`；孔隙 SVG 为 2 个 `M`、2 个 `Z`，连续场景 SVG 为 4 个 `M`、0 个 `Z`。
- Worker 与 Canvas 回退的 390px 狗截图 SHA-256 完全相同：`9EBD025753A58CFC34519179E38FF415E656C6A601CD991ED958380CD1A43D43`。

## 5. 截图与 SVG 证据

证据根目录：

`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-line-drawing-frontend\.tmp\D-line-frontend-20261018`

| 样例 | 桌面截图 | 390px 截图 |
| --- | --- | --- |
| 狗（真实 02 结果） | `screens\dog-desktop.png` | `screens\dog-mobile.png` |
| 孔隙（契约合成） | `screens\holes-desktop.png` | `screens\holes-mobile.png` |
| 多轮廓（契约派生） | `screens\contours-desktop.png` | `screens\contours-mobile.png` |
| 连续场景（契约合成） | `screens\continuous-desktop.png` | `screens\continuous-mobile.png` |
| 杯子失败（真实 06） | `screens\cup-failure-desktop.png` | `screens\cup-failure-mobile.png` |
| Worker 回退 | — | `screens\dog-mobile-fallback.png` |

导出的 SVG 位于 `svg\`：

- `dog-desktop.svg`、`dog-mobile.svg`
- `holes-desktop.svg`、`holes-mobile.svg`
- `contours-desktop.svg`、`contours-mobile.svg`
- `continuous-desktop.svg`、`continuous-mobile.svg`

机器可读检查结果：`.tmp\D-line-frontend-20261018\visual-checks.json`；主 SVG 区域截图：`screens\*-svg-only.png`。

## 6. 真实云请求 / 资源 / 环境

- 真实云完整请求：**0**
- 内部模型请求：**0**
- 仅回放已保存的 `02` 成功结果与 `06` 失败结果，并加载本机原图。
- 未加载模型权重，未使用 GPU，未修改共享依赖或锁文件。
- 为在隔离工作树运行构建，临时复制了现有 `mobile/node_modules`；该目录被忽略且未提交。
- 未重启共享 8093，未修改快捷方式、启动器或私有配置。

## 7. 剩余后端问题与风险

1. 真实连续场景仍未成功验证：`08` 仍是轮廓失败；本次只证明前端能正确消费满足契约的开放结构，不能声称真实拱廊/山湖已出好图。
2. 杯子 `06` 仍无可用主体轮廓；前端按约定不补画杯把、杯底或占位主体。
3. 狗 `02` 是真实结果回放，但耳部、眼睛和口中球的细节仍受后端轮廓质量限制；前端没有改写几何来“修好”截图。
4. B 的学习型分割尚未接入；当前真实产品仍是既有像素轮廓路径。
5. 前端测试与浏览器回放不能替代 E 的集成后真实四图验收，也不能证明端到端提速。

下一步：A 按上述提交顺序整合本分支；E 在 INTEGRATION_READY 后按预算做真实完整请求与最终画面复核。
