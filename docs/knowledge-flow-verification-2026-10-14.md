# GitHub 知识库本地接入与完整流程验证

日期：2026-10-14（Asia/Shanghai）。代码与资料来源为 GitHub `FFFFF-feng/xiaoli-camera-assistant`，本地与远程均为提交 `293d2d6311dc223cf112f899395b06f712bbff57`，没有待拉取提交。

**结论：导入、数据库、受管检索和真实模型读取知识的工程链路可运行；当前资料不能原样全部启用为正式构图知识库。** 主要阻碍是草稿/检索许可状态、知识条件与运行流程不匹配，以及模型 JSON 和建议内容的稳定性。文件格式通过不等于知识内容正确。

## 已落地到本地

- `data/knowledge_drafts/photography-20261013/upload_cards/`：121 条单记录 JSON，全部 SHA256 与 GitHub 随附 manifest 一致。
- `data/knowledge_drafts/starter-v1/`：17 条单记录 Markdown。
- `data/knowledge.db`：按原字段导入 138 条草稿；导入前已备份。重复导入分别报告 121 和 17 条 unchanged，没有重复记录或额外版本。
- 所有原始资料及其 `retrieval_allowed` 值保持不变；正式本机数据库的 published 数量仍为 0。
- 本机知识工作台入口：`http://127.0.0.1:8503/`。本轮没有更新 GitHub、修改生产模型默认设置或自动发布资料。

| 知识库 | 条数 |
| --- | ---: |
| 场景 | 20 |
| 构图 | 22 |
| 风格 | 15 |
| 拍摄技术 | 53 |
| 器材 | 19 |
| 参考案例 | 9 |
| 合计 | 138 |

## 真实模型全链路试验

为了验证资料真正进入模型请求，将本机数据库复制到独立的 `data/history/knowledge-flow-20261014-003013/isolated-trial.db`。只对原文件已经 `retrieval_allowed=true` 的 5 张 Wikibooks 技术卡执行**模拟发布**，审核记录明确署名 `isolated-software-test-only`，不冒充正式人工审核。其余 133 张保持草稿且未解除检索限制。正式本机数据库的发布状态未改变。

使用已核实来源的公开瀑布照片：Nikon Z50、24mm、最大 f/5.6、三脚架、无 ND 镜，需求为水流拉丝并保留树林层次。GLM-4.6V 与 DINO 均使用现有配置。

| 阶段 | 本轮结果 | 耗时 |
| --- | --- | ---: |
| GLM 场景/对象分析 | success，waterfall_long_exposure | 54.54 秒 |
| DINO 本机定位 | success，3 个候选框；主体关联 ambiguous | 13.42 秒 |
| 构图模型，生产默认 prompt JSON | 非法 JSON，被独立记录为 unavailable | 18.24 秒 |
| 技术资料检索与 GLM 参数建议 | 检索 4 条已许可技术卡，生成参数 | 14.70 秒 |
| 主流程整体 | 返回完整结果，保留有效参数并显示构图失败 | 100.99 秒 |

参数阶段命中并发送：

- `technique/technique-shutter-motion-001@v1`
- `technique/technique-exposure-clipping-001@v1`
- `technique/technique-blur-diagnosis-001@v1`
- `technique/technique-white-balance-001@v1`

在实际发送边界记录了提示词哈希及布尔证据：上述四条的标题、完整检索正文均在参数请求内。不是仅显示检索结果而没有送给模型。请求证据不保存 Authorization 或 API Key。

此次仅有 technique 资料被模拟发布，故 composition/style/case 检索结果为空，不能据本次参数 RAG 成功声称正式构图知识已接通。参数采用 f/8–f/11、1–5 秒、ISO 100–400；虽然包含试拍与高光检查，仍有曝光因果解释不准确，不能作为已验证的实拍方案。

## JSON 格式对照

1. 对失败构图阶段原样重试一次，复用真实场景和 DINO，39.67 秒后再次被严格解析拒绝。保存的最终文本末尾多出一个 `}`；没有放宽生产解析器或把非法响应算成功。
2. 保持模型、图片、提示词和场景相同，只在隔离请求增加 `response_format={"type":"json_object"}`。45.88 秒后得到合法结构，1 个方案；无构图知识，服务重新判定为 unverified。

这证明该账号本次请求接受 JSON 输出约束，并提供了改善格式的方向；单次对照不能证明长期可靠性。生产默认设置仍为原来的 prompt JSON，未自动切换。默认失败两次与对照成功均保留在报告中。

本轮共 5 次新 GLM 请求（完整流程 3 次＋两次构图对照）与 1 次本机 DINO 推理。构图知识缺失和格式失败是不同问题，不能用其中一个解释另一个。

## 资料与流程的兼容缺口

1. **当前没有已发布构图资料。** 121 张合集卡全部 `retrieval_allowed=false`；starter 也只有 5 张 technique 卡为 true，22 张 composition 卡均没有可检索的已发布版本。正常流程严格返回空结果，而不是绕过状态。
2. **52/121 张合集卡无法匹配当前条件。** 43 张要求未注册的场景 ID，如 pet_portrait、portrait、motion、architecture。9 张声明流程没有提供的条件键；两组互不重叠。未提供字段包括 camera_model、app、os_major、capture_mode、lighting、shutter_type、drive_mode、focus_mode。即使有检索许可并发布，仍会被条件过滤。
3. **部分器材卡条件过宽。** 11 张只限定 device_type 或完全无条件，不能保证只给指定机型使用。不要仅靠关键词相关度把设备事实套到其他型号。
4. **建议仍需内容验证。** JSON 合法、引用存在和知识正文进入提示词分别是工程条件，都不能独自证明摄影解释正确。上轮已发现的自然语言主体关联、中文快门解析与几何/曝光解释问题仍存在。

优先修复顺序：统一场景和条件字段；补齐器材型号适用范围；完成相关构图卡的来源与独立审核后发布；验证并接入更稳定的 JSON 输出约束；最后用多张实拍对照检查建议内容。

## 页面与软件检查

- 本机知识工作台 AppTest：74/74 项通过。验证实际 138 条草稿、六库数量、状态筛选、模板、starter 下载、真实集合条目上传/粘贴预览、输入变更撤销预览及非法 JSON 阻断。数据库以只读连接运行，前后哈希、逻辑内容、大小和 mtime 一致；没有额外云请求。
- 相关回归：126 passed、1 skipped（3.84 秒），范围为 importer、managed retriever、real pipeline、composition advisor。
- 原始照片来源为 [Hepoköngäs waterfall](https://commons.wikimedia.org/wiki/File:Hepok%C3%B6ng%C3%A4s_waterfall_long_eposure_2009-10-03.JPG)，作者 MattiPaavola，许可 [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)。本轮发送方向修正后的缩放副本。

## 本地证据

`data/history/knowledge-flow-20261014-003013/` 保存导入前数据库备份、隔离试验数据库、`summary.json`、`compatibility.json`、`real-result.json`、两次构图对照结果及最终回答。页面证据为 `.tmp/knowledge_flow_ui_probe.json`。这些运行数据由 Git 忽略，报告不包含密钥。
