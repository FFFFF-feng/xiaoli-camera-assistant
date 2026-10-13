# 首批摄影规则与手机器材资料

整理日期：2026-10-10。此次新增的是**17条待审核规则／事实卡、11个来源条目、3款手机能力目录与未知型号兜底**，不是已验证准确率或已发布的正式知识库。

## 1. 资料放在哪里

| 位置 | 内容 | 使用边界 |
| --- | --- | --- |
| [规则草稿目录](../data/knowledge_drafts/starter-v1/) | 一文件一条的Markdown标准记录，共17条 | 在旧版`knowledge/`目录外，避免未经审核自动参与演示检索 |
| [来源目录](../knowledge_sources/sources.yaml) | 11个原始出处、发布者、核对日期和下载策略 | 开放许可不代表内容正确；厂商资料不等于可再分发 |
| `data/source_cache/starter-v1/` | 两个Wikibooks教材HTML快照与下载报告／SHA-256 | 已下载，不提交Git；未下载图片、脚本或厂商全文 |
| [手机能力目录](../knowledge/devices/phone_profiles.yaml) | iPhone 15、Galaxy S24 Ultra、小米14及未知型号 | 确定性型号匹配，不是模型相似检索；未做真机测试 |
| [下载脚本](../scripts/fetch_knowledge_sources.py) | 只下载本轮明确允许的两个教材页面 | 已有快照不会覆盖；失败不绕过登录或关闭证书验证 |

可重新执行 `python scripts/fetch_knowledge_sources.py`；报告中的`downloaded_at`是UTC。文本缓存成功保存不代表全篇适合RAG，必须以规则卡和人工复核为单位使用。

## 2. 首批规则范围

| 库 | 数量 | 主题 |
| --- | --- | --- |
| 构图库 | 4 | 三分法、地平线／倒影、朝向留白、iPhone网格与水平 |
| 技术库 | 10 | 运动与曝光、模糊排查、高光、白平衡、裁切、物理景深；iPhone操作和夜间；Samsung／小米Pro边界 |
| 器材库 | 3 | 三款手机的型号、后置镜头事实与未确认项 |
| 场景／风格／案例库 | 0 | 本轮不编造场景标签、风格结论或实拍案例；案例图片需另核验许可 |

每条包含来源URL、章节、规则正文、适用条件、限制和`payload.verification`。几何提示只是数据，不会自动成为构图算法；不存在已训练的移动机位模型或通用曝光公式执行器。

### 为什么没有直接搬运平台文章

来源覆盖Wikibooks、Nikon、Canon、Apple、Samsung、Xiaomi。社交平台笔记和视频可作为后续线索，但本轮不下载未经授权的作品、不把单个作者的参数样例当作普遍规则。

Wikibooks文本提供开放许可；此次规则是中文短摘要改写，署名原贡献者并保留来源与同许可要求，原图不包含在内。[Wikibooks许可政策](https://en.wikibooks.org/wiki/Wikibooks:Copyrights) / [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

厂商材料只记录必要事实与原创短摘要；没有证据就不自动把`retrieval_allowed`改为true。发现OpenStax当前页面注明AI使用需要书面许可，因此**没有下载或纳入本批RAG语料**；不能看到“开放教材”就忽略附加使用说明。[OpenStax页面使用说明](https://openstax.org/books/university-physics-volume-3/pages/2-6-the-camera)

另一个质量风险是老教材的历史描述：Wikibooks页面包含旧ISO经验值、固定动态范围等内容，本次没有采用这些数值。后续整理者应逐条核验，不能把原文整体切块就当作已审核依据。

## 3. 怎样导入和审核

当前未自动向真实数据库写入17条资料，也未发布任何条目。

1. 在8503工作台下载本批草稿ZIP，解压后选中17个`.md`文件上传（不直接上传ZIP）。
2. 点击「校验并预览」，逐条检查正文、适用条件、来源和许可，再确认导入为草稿。
3. 由非作者核验内容和实机边界；有问题则退回，通过后再发布。
4. 使用`managed`检索；没有许可或未发布的条目仍不会被召回。

也可使用命令行，首次使用先初始化自己的数据库：

```powershell
python -m camera_assistant.knowledge init
python -m camera_assistant.knowledge import data/knowledge_drafts/starter-v1 --dry-run
python -m camera_assistant.knowledge import data/knowledge_drafts/starter-v1
```

Wikibooks来源的5条摘要记录开放文本检索许可，但状态仍为草稿，不能直接参与检索；厂商来源的12条保持许可待核验。许可确认需要增加版本重新导入，不修改旧正文。审核人不能假填成原厂或自动脚本；详细步骤见[工程说明](knowledge-development.md)。

## 4. 手机怎样接入拍摄助手

在8501选择「拍摄设备 → 手机」，搜索并选定型号、当前原生模式和后置镜头，再上传JPG／PNG现场图获取指导。

- 首版区分照片、人像、夜间和Pro；可选项受已收录型号限制。
- 未知型号只提供照片模式的保守操作，不把iPhone 15 Pro或小米14 Ultra识别成基础型号。
- 固定镜头光圈按规格说明，不建议当作可调项；人像景深控制不等于物理光圈调整。
- 专业模式需用户确认当前镜头确实显示ISO、S/SPEED、WB、F控制项；未核验的ISO／快门范围不输出数值。
- 手机分支可使用现有多模态服务分析场景，但建议采用本地受控指导，不调用文本生成模型推导曝光。检索条目可供阅读，**目前没有逐条用正文推算手机曝光参数**。
- 手机不检索旧相机Markdown库。`managed`模式会传入设备／型号／模式／镜头等条件，只查询符合发布边界的资料。
- HEIC／RAW解码、前置相机、第三方App、手机远程控制、自动EXIF选型和所有手机型号暂不支持。

新增条件键：`device_type`取`camera`／`phone`；`phone_profile_id`、`phone_capture_mode`、`phone_lens_id`与能力目录一致；`phone_pro_controls_confirmed`为布尔值。已有相机请求字段与流程保留。

```python
from pathlib import Path
from camera_assistant.services.phone_knowledge import PhoneKnowledgeBase

phones = PhoneKnowledgeBase(Path("knowledge/devices/phone_profiles.yaml"))
matches = phones.search("小米14")       # 供用户选择的候选
phone = phones.resolve("Xiaomi 14")  # 完整型号／已登记别名的确定性匹配
unknown = phones.resolve("Xiaomi 14 Ultra")  # 未收录，返回generic_phone，不冒充小米14
```

机型目录不是可检索知识审核的替代品：它是独立的运行时能力配置，只保存官网核对字段，未知字段为空／缺失，并在界面标记未真机验证。正式知识事实卡仍走草稿→审核→许可核验→发布流程。

## 5. 队友接下来怎么做

- 整理队员：先复核17条规则；补充来源许可与系统／地区适用范围，不导入平台全文作为默认知识。
- 视觉／构图队员：定义主体位置、朝向、地平线等几何观察契约；朝向不明时不输出确定移动方向。
- 知识库队员：核对条件键、发布状态与版本；维持准确的空结果提示，再按[RAG路线](rag-roadmap.md)做评测。
- 真机补充：优先挑队员已有的两三款手机，记录型号完整后缀、系统版本、原生App、镜头、模式控制项及可选数值范围；以后才开放对应数值建议。

不要凭EXIF的短焦距套全画幅安全快门；官方规格、界面可调项、建议试拍起点与实拍结论要分别记录。
