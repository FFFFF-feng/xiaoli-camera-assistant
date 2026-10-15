# 摄影与手机知识扩展包 expanded-v1

核对日期：2026-10-11。本批是在网页检索和已有知识契约基础上整理的 **80 条中文知识草稿**，不是 80 个独立实拍实验，也不是准确率已提升的证明。数据可直接通过现有导入界面预览并保存为草稿；不自动审核、不自动发布、不自动修改器材能力目录。

## 先找到可上传文件

```text
data/knowledge_drafts/expanded-v1/
├── batch-01/   20条：构图
├── batch-02/   20条：拍摄技术
├── batch-03/   20条：拍摄技术12 + 场景8
└── batch-04/   20条：场景2 + 风格6 + 器材12
knowledge_sources/expanded-v1/
├── sources.json    来源索引，不能当作知识卡上传
└── manifest.json   文件/ID/核对状态索引，不能当作知识卡上传
```

当前项目中的绝对数据目录为 `E:\develop\cmera\data\knowledge_drafts\expanded-v1`。不需要ZIP：上传某个batch文件夹里面的 **20个JSON文件**，不要上传整个文件夹、sources.json、manifest.json或本文档。

1. 打开现有知识导入工作台（运行时通常为 http://localhost:8502/）。
2. 选择一个batch内的20个JSON，点击“校验并预览”。
3. 应显示20条记录。展开条目查看来源、前提和限制。
4. 勾选确认后保存为草稿；再按同样步骤导入下一批。
5. 重复导入未修改的同版本文件应显示未变化，不应新增重复修订。
6. 同ID内容有修改须递增version；不要覆盖旧修订。

UI每批最多20文件、单文件2MiB、总计10MiB，本批按这些限制划分。程序化只读检查可使用：

```powershell
python -m camera_assistant.knowledge import data/knowledge_drafts/expanded-v1 --dry-run
```

本轮开发只进行了临时数据库测试和dry-run，**没有把这80条写入你的真实数据库**。

## 内容覆盖与核对强度

| 知识库 | 条数 | 主要覆盖 |
| --- | ---: | --- |
| 构图 composition | 20 | 主体位置、对称、地平线、引导线、留白、框景、边缘检查、横竖幅与比例 |
| 技术 technique | 32 | 曝光、ISO、快门、景深、AF/MF、白平衡、直方图、防抖、HDR、频闪、手机操作 |
| 场景 scene | 10 | 窗边/逆光人像、运动、风景、亮窗建筑、夜景、光轨、花卉近摄、混合光、静物 |
| 风格 style | 6 | 自然、柔和、温暖、冷色夜景、黑白、鲜明：均为可选表达目标 |
| 器材 equipment | 12 | 普通iPhone15、S24 Ultra、小米14全球版及未知设备的边界 |
| 真实案例 case | 0 | 未采集带原图、EXIF、拍摄结果和授权证明的真实案例，不编造案例 |

实际使用了 **41个已读正文的页面，来自7个发布方组**：Sony、Canon、Nikon、Apple、Samsung、Xiaomi、Google。教程同属一个厂商时，即使域名不同也不当作两方独立验证；厂商教程、型号手册、规格页和原作者技术说明承担不同证据角色。

| verification.status | 条数 | 准确含义 |
| --- | ---: | --- |
| cross_source_agreement | 14 | 核心主张得到至少两个不同发布方支持；不代表全部执行步骤经过实验验证 |
| primary_source_only | 21 | 仅有一个官方发布方支持，或多页同发布方；机型事实仍需系统/地区/模式核对 |
| synthesized_guideline | 30 | 根据所列原理组合的操作流程，是整理者推导，不是原文逐条一致或实拍证明 |
| interpretive_goal | 15 | 构图、风格等主观选择；方法有出处，但没有唯一“正确”或“最优”效果 |

四种状态都需要独立人工审核。`checked_at`只表示本次资料阅读/核对日期；`human_review_status=not_performed`和`field_test_status=not_performed`明确表示尚未有人审、尚未真机评测。

## 每条卡里有什么

- `content`：中文原创短归纳，包含核心规则、动作、前提、限制。
- `payload.core_claim`：核对的核心主张，不把整条执行流程标成已实测。
- `payload.requires / actions / limitations`：适用前提、操作建议、反例与不能推断的结论。
- `payload.verification.evidence`：每个证据的source_id、URL、章节定位和支持内容。
- `payload.manufacturer_facts`：仅器材卡可能提供的官方规格；未知值保留null。
- `conditions`：使用当前检索管线已有的字段；手机型号、Pro模式、用户确认项严格限定。
- `numeric_default=null`：不伪造万能曝光参数。器材标称光圈或等效焦距是事实字段，不是要求用户直接设置的推荐值。
- `automatic_execution=false`：这批是资料，不声明已执行几何检测、裁剪、自动调参或图像编辑。

注意：`requires`目前是供审核者/生成模型阅读的前提，不是已经实现的自动视觉硬过滤。发布前必须确认消费方会检查这些前提；单张照片也不能可靠推断精确距离、速度、真实照度和机型全部能力。

## 本次比较后保留的修正与边界

| 常见简化说法 | 本批处理 | 核对依据 |
| --- | --- | --- |
| 提高ISO就是让镜头进更多光 | 区分输出放大和光圈/时间决定的进光；不沿用旧夜景教程的简化措辞 | sony-iso；nikon-night |
| 用三脚架就能慢曝光而任何主体都清晰 | 三脚架稳定相机，移动主体另看快门；OIS也不冻结主体 | sony-shutter；google-nightsight-research |
| 直方图柱子越过图顶就是过曝 | 柱高为像素数量；亮度横轴、高光警告和重要细节分别检查 | nikon-histogram；nikon-hdr |
| 肖像必须三分或必须竖拍 | 和中心构图、环境叙事作为不同可选目标 | sony-portrait；nikon-center |
| 手机所有2×/10×都对应独立长焦 | 普通iPhone15的2×与S24 Ultra的光学品质倍率单独标注 | apple-iphone15；samsung-s24 |
| 夜景界面显示几秒就是单帧快门 | 区分总拍摄等待、EXIF与历史多帧实现，不反推当代所有算法 | apple-night；google-nightsight-research |
| 小米14支持10cm近摄，所以测量基准已确定 | 只保留官方描述，基准未知；照片/人像输出像素按脚注分别记录 | xiaomi-14 |
| Pro模式菜单和范围可跨手机直接复用 | 原生Pro、Expert RAW、第三方应用分开，数值范围未知；要求用户确认 | samsung-modes；xiaomi-pro |
| 工频经验能解决所有LED条纹 | 区分工频和高频LED，具体快门和抗闪功能按型号确认 | sony-flicker |
| 看到构图指南就意味着机内默认具备 | Canon Cropping Guide示例涉及服务安装，不能生成通用菜单指令 | canon-crop |

没有获得可读正文的页面不作为本批证据；失败候选及原因保存在sources.json。Google研究页是2018年Pixel历史算法说明，仅用于机制边界，不把当时帧数和时长作为2026手机能力。Apple动态手册会变化，本次只抽取与已收录设备相关的通用触屏操作，新增机型特性不能继承给iPhone15。

## 许可、草稿与实际接入

本批没有下载/再分发厂商全文、图片、用户原片或平台视频，也没有批量搬运小红书、论坛等未经授权内容。只保存原创短规则、必要规格和公开出处。**事实正确性核对不等于原文转载或RAG使用授权。**

所有记录默认 `source.retrieval_allowed=false`、`dataset_split=reference`，导入状态为draft。这不是上传失败，而是有意保留审核与许可门槛。不能为“让检索有结果”一键批量改成true。

后续按条目进行：

1. 队友打开证据链接，核实核心主张、限定条件、地区与软件版本；不通过时新增修订或退回。
2. 核实当前原创归纳的使用权及来源使用限制；需要原文/图片时另取得对应授权。审核通过与许可确认分别记录。
3. 内容有修改或许可字段变化时使用新version，重新导入；来源、事实和风险说明不得丢失。
4. 由不同于作者的真实队友审核，再按[知识库开发说明](knowledge-development.md)的submit / approve / publish流程操作；不要伪造审核身份。
5. 本批与starter-v1存在主题重叠但ID不同，不会自动覆盖旧卡。发布前做语义去重/合并，需要时按既有流程退役旧卡，避免重复知识挤占Top-K。

### 当前程序还不会做的事

现有受管主推荐流程在 `src/camera_assistant/pipeline.py` 中只请求 `scene / technique / equipment` 三库；**composition / style不会因为导入就自动进入主推荐结果**。后续需要另行实现构图/风格检索路由，以及前提检查和引用展示，不能把“已入库”写成“已支持自动构图指导”。

主界面也需要显式启用managed检索模式，并只读取已发布、reference、允许检索的记录。手机运行时仍由本地受控能力目录约束，本批器材payload不会自动改写那个目录，不从RAG正文直接推断ISO或快门上限。

## 如何真正验证准确性

建议三位队员把“资料、检索、实拍”分开验收：

1. **资料复核**：每条检查来源和反例，先复核14条多方支持与型号卡，仍有疑问保留待修订。
2. **检索验证**：建立独立evaluation集，例如60个问法，每条有人审的期望知识ID、型号、模式、运动与支撑条件；评测资料禁止发布到reference检索库。
3. **约束验证**：重点检查“普通15要ProRAW”“未知手机套S24范围”“已改镜头仍继承Pro能力”等负例，统计错误召回和越界参数。
4. **真机实拍**：用实际机身/手机，记录系统、镜头、光线、主体运动、原片EXIF、建议与复拍结果；不是只看模型回答是否顺畅。
5. **构图评估**：至少两人按用户目标分别评分，记录分歧；先比较建议前后画面，禁止把审美分数当物理正确率。
6. **指标报告**：检索可看Recall@K、条件错配率、引用支持率；输出可看越界率、建议可执行率；实拍清晰/曝光按预定义标准人工评估。没有数据前不写“准确率90%”。

真实case库应另外采集有许可的现场图→建议→复拍图，标注“原始/裁剪/重拍/生成”，记录失败案例，避免只留成功作品。

## 自动验证范围

本批新增tests/test_knowledge_expansion.py：80条模型校验、来源/索引一致性、交叉核对发布方数量、四批容量、手机模式隔离、临时SQLite导入80条草稿及重复幂等、许可阻断，以及Streamlit工作台首批20条预览→确认→保存。

这些测试验证**文件结构和系统行为**，不验证外部事实本身，不等同浏览器人工实测，更不等同摄影效果评测。临时测试的模拟审核不作用于项目真实数据库。

运行：

```powershell
python -m pytest tests/test_knowledge_expansion.py -q -p no:cacheprovider
python -m camera_assistant.knowledge import data/knowledge_drafts/expanded-v1 --dry-run
```

## 已使用的来源索引

详细章节和限制见[来源登记](../knowledge_sources/expanded-v1/sources.json)；每条映射见[数据清单](../knowledge_sources/expanded-v1/manifest.json)。

- `sony-focal` — [Sony：焦距与视角](https://www.sony.com/electronics/support/articles/00267921)
- `sony-light` — [Sony：光线方向及效果](https://www.sony.com/electronics/support/articles/00267922)
- `sony-defocus` — [Sony：背景虚化的影响因素](https://www.sony.com/electronics/support/articles/00267923)
- `sony-minfocus` — [Sony：镜头最近对焦距离](https://www.sony.com/electronics/support/articles/00267924)
- `sony-exposure` — [Sony：曝光与曝光补偿](https://www.sony.com/electronics/support/articles/00267925)
- `sony-aperture` — [Sony：光圈与A模式](https://www.sony.com/electronics/support/articles/00267926)
- `sony-wb` — [Sony：白平衡](https://www.sony.com/electronics/support/articles/00267928)
- `sony-shutter` — [Sony：快门与S模式](https://www.sony.com/electronics/support/articles/00267929)
- `sony-iso` — [Sony：ISO与放大](https://www.sony.com/electronics/support/articles/00267930)
- `sony-af` — [Sony：自动与手动对焦](https://www.sony.com/electronics/support/articles/00267931)
- `sony-manual` — [Sony：M模式与手动曝光](https://www.sony.com/electronics/support/articles/00267933)
- `sony-look` — [Sony：Creative Look](https://www.sony.com/electronics/support/articles/00273574)
- `sony-portrait` — [Sony：突出人物的肖像教程](https://www.sony.co.uk/electronics/support/articles/00206555)
- `sony-flicker` — [Sony：条纹与频闪控制](https://www.sony.com/electronics/support/articles/00122281)
- `canon-focal` — [Canon：RF镜头知识：焦距](https://files.canon-europe.com/files/webcontent/rf-lens-world/knowledge/focus/index.html)
- `canon-dof` — [Canon：RF镜头知识：景深](https://files.canon-europe.com/files/webcontent/rf-lens-world/knowledge/depth-of-field/index.html)
- `canon-shutter` — [Canon：RF镜头知识：快门](https://files.canon-europe.com/files/webcontent/rf-lens-world/knowledge/shutter/index.html)
- `canon-is` — [Canon：RF镜头知识：防抖](https://files.canon-europe.com/files/webcontent/rf-lens-world/knowledge/correction/index.html)
- `canon-composition` — [Canon：Mastering Photo Composition](https://www.canon.com.au/get-inspired/mastering-photo-composition-ideas)
- `canon-af` — [Canon：EOS R7对焦操作手册](https://cam.start.canon/en/C005/manual/html/UG-05_AF-Drive_0040.html)
- `canon-af-area` — [Canon：EOS R7对焦区域与困难条件](https://cam.start.canon/en/C005/manual/html/UG-05_AF-Drive_0070.html)
- `canon-crop` — [Canon：Cropping Guide说明](https://www.canon.com.au/get-inspired/cropping-guide)
- `nikon-composition` — [Nikon：5 Easy Composition Guidelines](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/5-easy-composition-guidelines)
- `nikon-center` — [Nikon：中心构图的人像表达](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/when-center-composition-can-elevate-a-portrait)
- `nikon-autoiso` — [Nikon：自动ISO说明](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/understanding-auto-iso)
- `nikon-wb` — [Nikon：设置白平衡](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/setting-white-balance)
- `nikon-hdr` — [Nikon：HDR摄影教程](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/high-dynamic-range-photography)
- `nikon-night` — [Nikon：黄昏与夜晚摄影](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/taking-pictures-at-dusk-and-at-night)
- `nikon-histogram` — [Nikon：Z6III照片信息手册](https://onlinemanual.nikonimglib.com/z6III/en/photo_information_53.html)
- `nikon-compensation` — [Nikon：D850曝光补偿手册](https://onlinemanual.nikonimglib.com/d850/en/11_exposure_06.html)
- `apple-iphone15` — [Apple：iPhone 15技术规格](https://support.apple.com/zh-cn/111831)
- `apple-tools` — [Apple：iPhone相机工具](https://support.apple.com/zh-cn/guide/iphone/iph3dc593597/ios)
- `apple-night` — [Apple：iPhone夜间模式](https://support.apple.com/zh-cn/102519)
- `apple-portrait` — [Apple：iPhone人像与景深效果](https://support.apple.com/zh-cn/guide/iphone/iphd7d3a91a2/ios)
- `apple-proraw` — [Apple：Apple ProRAW支持范围](https://support.apple.com/zh-cn/119916)
- `samsung-s24` — [Samsung：Galaxy S24系列发布规格](https://news.samsung.com/global/enter-the-new-era-of-mobile-ai-with-samsung-galaxy-s24-series)
- `samsung-modes` — [Samsung：Galaxy相机模式说明](https://www.samsung.com/uk/support/mobile-devices/what-are-the-different-camera-modes-and-how-do-i-use-them/)
- `xiaomi-14` — [Xiaomi：Xiaomi 14全球版规格](https://www.mi.com/global/product/xiaomi-14/specs/)
- `xiaomi-pro` — [Xiaomi：手机专业模式说明](https://www.mi.com/es/support/article/KA-51452/)
- `google-night` — [Google：Pixel低光与天文摄影帮助](https://support.google.com/pixelcamera/answer/9708795?hl=en-GB)
- `google-nightsight-research` — [Google：Night Sight原作者技术说明](https://research.google/blog/night-sight-seeing-in-the-dark-on-pixel-phones/)

## 80条规则速查

“状态”仅对应上文定义的核心主张核对范围；所有条目仍待人审和实拍。

| 文件 | 标题 | 核对状态 | 证据ID |
| --- | --- | --- | --- |
| [01_composition_thirds.json](../data/knowledge_drafts/expanded-v1/batch-01/01_composition_thirds.json) | 三分法：一个可比较的主体位置 | 多发布方支持核心主张 | nikon-composition、sony-portrait |
| [02_composition_center.json](../data/knowledge_drafts/expanded-v1/batch-01/02_composition_center.json) | 中心构图：直接突出主体 | 可选表达目标 | nikon-center、canon-composition |
| [03_composition_symmetry.json](../data/knowledge_drafts/expanded-v1/batch-01/03_composition_symmetry.json) | 对称构图：先确认真正的对称轴 | 可选表达目标 | canon-composition、nikon-composition |
| [04_composition_horizon.json](../data/knowledge_drafts/expanded-v1/batch-01/04_composition_horizon.json) | 地平线：平直检查与位置选择分开 | 综合推导流程 | apple-tools、nikon-composition |
| [05_composition_leading-lines.json](../data/knowledge_drafts/expanded-v1/batch-01/05_composition_leading-lines.json) | 引导线：观察线条指向哪里 | 多发布方支持核心主张 | nikon-composition、canon-composition |
| [06_composition_framing.json](../data/knowledge_drafts/expanded-v1/batch-01/06_composition_framing.json) | 框中框：用现场结构包围主体 | 多发布方支持核心主张 | nikon-center、canon-composition |
| [07_composition_negative-space.json](../data/knowledge_drafts/expanded-v1/batch-01/07_composition_negative-space.json) | 留白：为空间感服务 | 可选表达目标 | canon-composition |
| [08_composition_depth-layers.json](../data/knowledge_drafts/expanded-v1/batch-01/08_composition_depth-layers.json) | 前中后景：帮助表达空间层次 | 可选表达目标 | canon-composition |
| [09_composition_fill-frame.json](../data/knowledge_drafts/expanded-v1/batch-01/09_composition_fill-frame.json) | 填满画面：突出细节而非盲目靠近 | 综合推导流程 | canon-composition、sony-minfocus |
| [10_composition_look-room.json](../data/knowledge_drafts/expanded-v1/batch-01/10_composition_look-room.json) | 视线方向留空间 | 多发布方支持核心主张 | nikon-composition、sony-portrait |
| [11_composition_motion-room.json](../data/knowledge_drafts/expanded-v1/batch-01/11_composition_motion-room.json) | 运动方向留空间：不要把朝向当速度 | 可选表达目标 | nikon-composition |
| [12_composition_patterns.json](../data/knowledge_drafts/expanded-v1/batch-01/12_composition_patterns.json) | 重复图案：寻找节奏和例外 | 多发布方支持核心主张 | nikon-composition、canon-composition |
| [13_composition_curves.json](../data/knowledge_drafts/expanded-v1/batch-01/13_composition_curves.json) | 曲线与斜向线：提供另一种视线路径 | 可选表达目标 | nikon-composition |
| [14_composition_edge-scan.json](../data/knowledge_drafts/expanded-v1/batch-01/14_composition_edge-scan.json) | 画面边缘检查：减少非预期干扰 | 综合推导流程 | nikon-center、sony-portrait |
| [15_composition_background-separation.json](../data/knowledge_drafts/expanded-v1/batch-01/15_composition_background-separation.json) | 主体分离：先换背景，再讨论虚化 | 综合推导流程 | nikon-center、sony-defocus |
| [16_composition_orientation.json](../data/knowledge_drafts/expanded-v1/batch-01/16_composition_orientation.json) | 横竖构图：由叙事与输出决定 | 可选表达目标 | sony-portrait |
| [17_composition_eye-placement.json](../data/knowledge_drafts/expanded-v1/batch-01/17_composition_eye-placement.json) | 肖像眼睛位置：三分交点仅是候选 | 可选表达目标 | sony-portrait |
| [18_composition_viewpoint.json](../data/knowledge_drafts/expanded-v1/batch-01/18_composition_viewpoint.json) | 换机位：把建议变成可比较的版本 | 可选表达目标 | canon-composition |
| [19_composition_aspect-plan.json](../data/knowledge_drafts/expanded-v1/batch-01/19_composition_aspect-plan.json) | 宽高比：先确定输出，再留裁剪余量 | 综合推导流程 | canon-composition、apple-tools |
| [20_composition_crop-guide.json](../data/knowledge_drafts/expanded-v1/batch-01/20_composition_crop-guide.json) | 构图辅助线：建议与机内功能要区分 | 综合推导流程 | canon-crop、apple-tools |
| [21_technique_aperture-dof.json](../data/knowledge_drafts/expanded-v1/batch-02/21_technique_aperture-dof.json) | 光圈：进光与景深要同时考虑 | 多发布方支持核心主张 | sony-aperture、canon-dof |
| [22_technique_shutter-motion.json](../data/knowledge_drafts/expanded-v1/batch-02/22_technique_shutter-motion.json) | 快门：冻结与拖影是不同目标 | 多发布方支持核心主张 | sony-shutter、canon-shutter |
| [23_technique_exposure-stops.json](../data/knowledge_drafts/expanded-v1/batch-02/23_technique_exposure-stops.json) | 曝光变化：不要把一挡当成任意加一 | 单一官方发布方 | sony-aperture、sony-shutter |
| [24_technique_iso-not-photons.json](../data/knowledge_drafts/expanded-v1/batch-02/24_technique_iso-not-photons.json) | ISO：不把提亮说成增加进光量 | 单一官方发布方 | sony-iso |
| [25_technique_iso-tradeoff.json](../data/knowledge_drafts/expanded-v1/batch-02/25_technique_iso-tradeoff.json) | ISO与噪声：按设备和进光条件权衡 | 综合推导流程 | sony-iso、google-nightsight-research |
| [26_technique_compensation-direction.json](../data/knowledge_drafts/expanded-v1/batch-02/26_technique_compensation-direction.json) | 曝光补偿：按目标与高光判断方向 | 多发布方支持核心主张 | sony-exposure、nikon-compensation |
| [27_technique_aperture-priority.json](../data/knowledge_drafts/expanded-v1/batch-02/27_technique_aperture-priority.json) | 光圈优先：设好景深后检查自动快门 | 单一官方发布方 | sony-aperture、sony-iso |
| [28_technique_shutter-priority.json](../data/knowledge_drafts/expanded-v1/batch-02/28_technique_shutter-priority.json) | 快门优先：不能假定自动光圈永远足够 | 单一官方发布方 | sony-shutter |
| [29_technique_manual-autoiso.json](../data/knowledge_drafts/expanded-v1/batch-02/29_technique_manual-autoiso.json) | M与Auto ISO：先确认到底谁在自动变化 | 综合推导流程 | sony-manual、nikon-autoiso |
| [30_technique_autoiso-limits.json](../data/knowledge_drafts/expanded-v1/batch-02/30_technique_autoiso-limits.json) | 自动ISO：上限不是画质保证 | 单一官方发布方 | nikon-autoiso |
| [31_technique_af-static.json](../data/knowledge_drafts/expanded-v1/batch-02/31_technique_af-static.json) | 静止主体：单次对焦是候选起点 | 多发布方支持核心主张 | sony-af、canon-af |
| [32_technique_af-moving.json](../data/knowledge_drafts/expanded-v1/batch-02/32_technique_af-moving.json) | 移动主体：连续对焦与快门配合 | 多发布方支持核心主张 | sony-af、canon-af |
| [33_technique_manual-focus-check.json](../data/knowledge_drafts/expanded-v1/batch-02/33_technique_manual-focus-check.json) | 手动对焦：放大检查，勿只信峰值 | 综合推导流程 | sony-af、canon-af-area |
| [34_technique_too-close-focus.json](../data/knowledge_drafts/expanded-v1/batch-02/34_technique_too-close-focus.json) | 太近无法合焦：先退后，不急着换参数 | 单一官方发布方 | sony-minfocus |
| [35_technique_background-distance.json](../data/knowledge_drafts/expanded-v1/batch-02/35_technique_background-distance.json) | 背景虚化：拉开主体与背景是一种办法 | 单一官方发布方 | sony-defocus |
| [36_technique_focal-angle.json](../data/knowledge_drafts/expanded-v1/batch-02/36_technique_focal-angle.json) | 焦距与视角：等效标注不能混为实体焦距 | 多发布方支持核心主张 | sony-focal、canon-focal |
| [37_technique_close-dof.json](../data/knowledge_drafts/expanded-v1/batch-02/37_technique_close-dof.json) | 近摄景深：更近时要复查清晰范围 | 多发布方支持核心主张 | canon-dof、sony-defocus |
| [38_technique_wb-start.json](../data/knowledge_drafts/expanded-v1/batch-02/38_technique_wb-start.json) | 白平衡：自动起步，按目标修正 | 多发布方支持核心主张 | sony-wb、nikon-wb |
| [39_technique_wb-reference.json](../data/knowledge_drafts/expanded-v1/batch-02/39_technique_wb-reference.json) | 中性参考：测量对象须真中性 | 单一官方发布方 | nikon-wb |
| [40_technique_mixed-wb.json](../data/knowledge_drafts/expanded-v1/batch-02/40_technique_mixed-wb.json) | 混合光：单一白平衡未必能全画面中性 | 综合推导流程 | sony-wb、nikon-wb |
| [41_technique_histogram-axes.json](../data/knowledge_drafts/expanded-v1/batch-03/41_technique_histogram-axes.json) | 直方图：柱高不是曝光溢出 | 单一官方发布方 | nikon-histogram |
| [42_technique_highlights-check.json](../data/knowledge_drafts/expanded-v1/batch-03/42_technique_highlights-check.json) | 高光保护：区分重要细节与允许的纯亮区域 | 综合推导流程 | nikon-histogram、sony-exposure |
| [43_technique_blur-diagnosis.json](../data/knowledge_drafts/expanded-v1/batch-03/43_technique_blur-diagnosis.json) | 模糊诊断：焦点、机震、主体运动分开排查 | 综合推导流程 | sony-shutter、canon-af-area |
| [44_technique_tripod-moving.json](../data/knowledge_drafts/expanded-v1/batch-03/44_technique_tripod-moving.json) | 三脚架：稳定相机，不冻结移动主体 | 综合推导流程 | sony-shutter、nikon-hdr、google-nightsight-research |
| [45_technique_is-subject-motion.json](../data/knowledge_drafts/expanded-v1/batch-03/45_technique_is-subject-motion.json) | 防抖：不能替代冻结主体所需的曝光时间 | 综合推导流程 | canon-is、google-nightsight-research |
| [46_technique_hdr-bracket.json](../data/knowledge_drafts/expanded-v1/batch-03/46_technique_hdr-bracket.json) | 曝光包围：先确认场景适合多张合成 | 单一官方发布方 | nikon-hdr |
| [47_technique_multiframe-motion.json](../data/knowledge_drafts/expanded-v1/batch-03/47_technique_multiframe-motion.json) | 多帧合成：移动边缘要单独检查 | 综合推导流程 | google-nightsight-research、nikon-hdr |
| [48_technique_flicker-banding.json](../data/knowledge_drafts/expanded-v1/batch-03/48_technique_flicker-banding.json) | 灯光条纹：确认光源与快门方式 | 单一官方发布方 | sony-flicker |
| [49_technique_iphone-touch-focus.json](../data/knowledge_drafts/expanded-v1/batch-03/49_technique_iphone-touch-focus.json) | iPhone 15：点按主体调整对焦区域 | 单一官方发布方 | apple-tools |
| [50_technique_iphone-aeaf-lock.json](../data/knowledge_drafts/expanded-v1/batch-03/50_technique_iphone-aeaf-lock.json) | iPhone 15：稳定场景可尝试AE/AF锁定 | 单一官方发布方 | apple-tools |
| [51_technique_phone-night-steady.json](../data/knowledge_drafts/expanded-v1/batch-03/51_technique_phone-night-steady.json) | 手机夜景：快门后仍需等待拍摄结束 | 多发布方支持核心主张 | apple-night、google-night |
| [52_technique_night-time-exif.json](../data/knowledge_drafts/expanded-v1/batch-03/52_technique_night-time-exif.json) | 夜间时长：总拍摄过程与EXIF单帧时长分开 | 综合推导流程 | apple-night、google-nightsight-research |
| [53_scene_window-portrait.json](../data/knowledge_drafts/expanded-v1/batch-03/53_scene_window-portrait.json) | 窗边人像：先观察主光方向 | 综合推导流程 | sony-light、sony-portrait |
| [54_scene_backlit-portrait.json](../data/knowledge_drafts/expanded-v1/batch-03/54_scene_backlit-portrait.json) | 逆光人像：在主体和背景间选择目标 | 综合推导流程 | sony-light、sony-exposure、nikon-histogram |
| [55_scene_moving-child.json](../data/knowledge_drafts/expanded-v1/batch-03/55_scene_moving-child.json) | 跑动儿童或宠物：运动优先，而非三脚架优先 | 综合推导流程 | sony-shutter、canon-af |
| [56_scene_landscape-depth.json](../data/knowledge_drafts/expanded-v1/batch-03/56_scene_landscape-depth.json) | 风景：清晰范围比固定f值重要 | 综合推导流程 | canon-dof、sony-shutter、nikon-histogram |
| [57_scene_bright-window-building.json](../data/knowledge_drafts/expanded-v1/batch-03/57_scene_bright-window-building.json) | 室内建筑与亮窗：先处理亮暗差异 | 综合推导流程 | nikon-hdr、nikon-histogram |
| [58_scene_night-city.json](../data/knowledge_drafts/expanded-v1/batch-03/58_scene_night-city.json) | 夜景街道：先区分静态建筑与移动行人 | 综合推导流程 | nikon-night、google-nightsight-research |
| [59_scene_light-trails.json](../data/knowledge_drafts/expanded-v1/batch-03/59_scene_light-trails.json) | 车流光轨：慢曝光是表达手段 | 综合推导流程 | nikon-night、sony-shutter |
| [60_scene_flower-closeup.json](../data/knowledge_drafts/expanded-v1/batch-03/60_scene_flower-closeup.json) | 花卉近摄：距离、清晰范围与风分开判断 | 综合推导流程 | sony-minfocus、canon-dof、sony-shutter |
| [61_scene_mixed-indoor.json](../data/knowledge_drafts/expanded-v1/batch-04/61_scene_mixed-indoor.json) | 室内混合灯光：先围绕主体光源决策 | 综合推导流程 | sony-wb、nikon-wb、sony-flicker |
| [62_scene_food-stilllife.json](../data/knowledge_drafts/expanded-v1/batch-04/62_scene_food-stilllife.json) | 食物与静物：角度、背景和光线联合比较 | 综合推导流程 | canon-composition、sony-light、sony-wb |
| [63_style_natural-clean.json](../data/knowledge_drafts/expanded-v1/batch-04/63_style_natural-clean.json) | 简洁自然：先定义保留什么 | 可选表达目标 | nikon-center、sony-look |
| [64_style_soft-portrait.json](../data/knowledge_drafts/expanded-v1/batch-04/64_style_soft-portrait.json) | 柔和人像：柔光目标不等于整张失焦 | 可选表达目标 | sony-portrait、sony-look、apple-portrait |
| [65_style_warm-memory.json](../data/knowledge_drafts/expanded-v1/batch-04/65_style_warm-memory.json) | 温暖记忆感：色彩选择而非曝光配方 | 可选表达目标 | nikon-wb、sony-look |
| [66_style_cool-night.json](../data/knowledge_drafts/expanded-v1/batch-04/66_style_cool-night.json) | 冷色夜景：保留夜感，而非统一压暗 | 可选表达目标 | sony-wb、sony-exposure |
| [67_style_black-white.json](../data/knowledge_drafts/expanded-v1/batch-04/67_style_black-white.json) | 黑白表达：先看明暗与主体关系 | 可选表达目标 | sony-look、nikon-center |
| [68_style_vivid-scene.json](../data/knowledge_drafts/expanded-v1/batch-04/68_style_vivid-scene.json) | 鲜明风格：饱和度和高光分开检查 | 可选表达目标 | sony-look、nikon-histogram |
| [69_equipment_iphone15-rear.json](../data/knowledge_drafts/expanded-v1/batch-04/69_equipment_iphone15-rear.json) | iPhone 15：两枚后置实体相机的标称规格 | 单一官方发布方 | apple-iphone15 |
| [70_equipment_iphone15-2x.json](../data/knowledge_drafts/expanded-v1/batch-04/70_equipment_iphone15-2x.json) | iPhone 15：2×取景不登记成独立长焦 | 单一官方发布方 | apple-iphone15 |
| [71_equipment_iphone15-formats.json](../data/knowledge_drafts/expanded-v1/batch-04/71_equipment_iphone15-formats.json) | iPhone 15：HEIF/JPEG与原图传输 | 单一官方发布方 | apple-iphone15 |
| [72_equipment_iphone15-no-proraw.json](../data/knowledge_drafts/expanded-v1/batch-04/72_equipment_iphone15-no-proraw.json) | iPhone 15：不继承Pro系列Apple ProRAW | 单一官方发布方 | apple-proraw、apple-iphone15 |
| [73_equipment_s24ultra-lenses.json](../data/knowledge_drafts/expanded-v1/batch-04/73_equipment_s24ultra-lenses.json) | S24 Ultra：实体镜头与光圈对应关系 | 单一官方发布方 | samsung-s24 |
| [74_equipment_s24ultra-zoom-quality.json](../data/knowledge_drafts/expanded-v1/batch-04/74_equipment_s24ultra-zoom-quality.json) | S24 Ultra：光学变焦与光学品质表述区分 | 单一官方发布方 | samsung-s24 |
| [75_equipment_s24ultra-pro-check.json](../data/knowledge_drafts/expanded-v1/batch-04/75_equipment_s24ultra-pro-check.json) | S24 Ultra专业操作：当前镜头与菜单先确认 | 综合推导流程 | samsung-modes、samsung-s24 |
| [76_equipment_xiaomi14-lenses.json](../data/knowledge_drafts/expanded-v1/batch-04/76_equipment_xiaomi14-lenses.json) | 小米14全球版：等效焦距和镜头规格 | 单一官方发布方 | xiaomi-14 |
| [77_equipment_xiaomi14-tele-footnotes.json](../data/knowledge_drafts/expanded-v1/batch-04/77_equipment_xiaomi14-tele-footnotes.json) | 小米14长焦：10cm描述与输出像素须带脚注 | 单一官方发布方 | xiaomi-14 |
| [78_equipment_xiaomi14-pro-check.json](../data/knowledge_drafts/expanded-v1/batch-04/78_equipment_xiaomi14-pro-check.json) | 小米14专业操作：不要照抄通用EV建议 | 综合推导流程 | xiaomi-pro、xiaomi-14、sony-exposure |
| [79_equipment_unknown-phone.json](../data/knowledge_drafts/expanded-v1/batch-04/79_equipment_unknown-phone.json) | 未收录手机：补充型号，禁止近似能力继承 | 综合推导流程 | apple-proraw、xiaomi-pro |
| [80_equipment_camera-stabilization.json](../data/knowledge_drafts/expanded-v1/batch-04/80_equipment_camera-stabilization.json) | 相机防抖能力：机身和镜头分别确认 | 综合推导流程 | canon-is、nikon-night |
