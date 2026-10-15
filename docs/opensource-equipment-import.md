# 开源设备资料导入说明

本批资料用于建立可追溯的器材知识库草稿。包含 7,546 条相机、镜头及转接器档案，已转换为现有导入器支持的单条 JSON 文件。它们不是已核准的设备能力表，不会自动改变设备下拉选项、曝光参数限制或正式 RAG 检索。

## 资料范围和许可

| 来源 | 档案内容 | 条数 | 数据许可 |
| --- | --- | ---: | --- |
| [CameraDatabase](https://github.com/leavestylecode/CameraDatabase) | 相机原始规格 | 3,860 | MIT |
| [Lensfun](https://github.com/lensfun/lensfun) | 相机型号及卡口 | 1,057 | CC BY-SA 3.0 |
| Lensfun | 多卡口镜头元数据 | 1,571 | CC BY-SA 3.0 |
| [Z Mount Product Database](https://github.com/KatsuraIwamoto/z-mount-product-database) | 普通镜头 | 607 | CC BY 4.0 |
| Z Mount Product Database | 转接器 | 447 | CC BY 4.0 |
| Z Mount Product Database | 增距镜和针孔光学产品 | 4 | CC BY 4.0 |

档案条数不等于互不重复的设备型号数：同一设备可能在不同来源各有一条。不同来源暂不自动合并，避免把校正模型、地区名称及产品版本混为一谈。Lensfun 镜头包含多个 18–55 型号和卡口版本，不能把它们合并成一个通用镜头。

[OpenSfM 的传感器库](https://github.com/mapillary/OpenSfM/blob/b25c07b648b49352797125f2b40f9cef28bbac62/opensfm/data/sensor_data.readme.txt)包含 3,709 条宽度记录，本批只用于相机数据一致性检查，不另生成重复设备卡。其数据说明采用 Simplified BSD 许可，并说明初始数据来自 Digicamdb，因此跨库一致不应视为独立证据。

本批没有手机档案。前期发现的手机目录或含非商业许可，或只有型号代码，或缺少稳定的拍摄能力字段，暂不当作可信手机规格库导入。照片、产品图片、视频和第三方网站正文均不在下载范围内。

## 文件位置

以下均为项目根目录下的相对路径：

- 全量可导入文件：`data/knowledge_drafts/opensource-equipment-20261014/`。
- 界面演示用的 20 个文件：`data/knowledge_samples/opensource-equipment-20261014/`。
- 来源版本和文件哈希：`knowledge_sources/opensource-equipment-20261014/source-manifest.json`。
- 全量索引、转换统计和冲突清单：同目录的 `conversion-report.json`。
- 许可原文和署名说明：同目录的 `licenses/`；Lensfun 原始 XML 另保存在 `lensfun-original/`，保留原有注记。
- 原始下载缓存：`data/source_cache/opensource-equipment-20261014/`，该目录被 Git 忽略，可按固定提交重新下载。
- 本地知识库：`data/knowledge.db`，导入前备份在 `data/backups/`。

不要把来源报告、许可文件或原始 XML 上传为知识卡。全量目录按来源及器材类型分组，每个 `part-xxx` 子目录最多 20 个 JSON 文件；无需 ZIP。演示目录是全量资料的子集，勿和全量目录一起递归导入。

## 规则卡约定

每个 JSON 文件是一条 `KnowledgeRecord`，包括标题、中文适用规则、结构化原始规格、来源地址、固定 Git 提交、原文件 SHA256、许可和修改说明。

本批全部使用 `library_id=equipment`、`kind=guideline`、`version=1`、`source.retrieval_allowed=false`。导入状态只能由存储层设为 `draft`。这是社区设备档案，不标为 `manufacturer_fact`；`payload.verification.officially_verified=false` 明确表示没有完成逐条厂家核验。

适用条件以完整相机型号或具体镜头型号约束，不做子串匹配。转接器暂按尼康 Z 机身卡口收窄范围，但**组合级兼容校验尚未实现，不得批量发布转接器卡**。运行时别名映射和设备选择目录也需要独立对接。

结构化字段的含义：

| 字段 | 用途 |
| --- | --- |
| `payload.entity_type` | 区分 camera、lens、adapter、teleconverter、pinhole |
| `payload.provenance` | 原始仓库、提交、记录定位、文件哈希、署名和许可 |
| `payload.source_specs` | CameraDatabase 原始字段，移除图片路径 |
| `payload.source_metadata` | Lensfun 明示的型号、卡口、裁切系数及元数据 |
| `payload.source_product` | Z Mount 产品结构，保留规格条件、空值和官方复核链接 |
| `payload.consistency_checks` | 相机传感器宽度跨库检查结果 |
| `payload.usage.controls_hardware_limits` | 固定 false，禁止直接据此覆盖参数约束 |

## 准确性检查和待复核项

相机传感器宽度只从明确写出的毫米尺寸提取，不把 `1/2.3 英寸型`当作物理英寸直接换算。型号匹配仅统一 Unicode、大小写及空白，不自动推断别名、同系列或地区版本。一致性容差是 `max(0.1 mm, CameraDatabase 宽度 × 1%)`，只是筛查阈值，不是测量精度保证。

- 3,212 条在容差内一致。
- 647 条无法进行完整型号和宽度比对，保留未知。
- 1 条存在冲突：`Canon PowerShot S200`，两个来源的宽度分别为 7.53 mm 和 5.33 mm，保留两值，不自动择一。

佳能官网分别记录了 [2002 年的 PowerShot S200 DIGITAL ELPH](https://global.canon/en/c-museum/product/dcc477.html)和 [2013 年的 PowerShot S200](https://global.canon/en/c-museum/product/dcc646.html)，传感器类型分别为 1/2.7 英寸型和 1/1.7 英寸型。这支持“短型号可能指向不同产品”的判断，但没有直接证明上述毫米数值。审核时须补全具体产品、年份及地区，不得仅凭 S200 自动合并。

其他边界：

- 保留 ISO 原文，不能把扩展感光度当作标准范围。
- 未区分机械和电子的快门字段，不能作为机械快门上限。
- 物理光圈、等效光圈、物理焦距和 35mm 等效焦距分别保留，不混用。
- Lensfun 的校正采样点不代表完整焦段或最大光圈；其裁切系数不直接替代厂家标称画幅。
- 不使用 Lensfun 的 `mount compat` 推断无需转接环的原生兼容。
- 转接器的上游自动对焦、电子触点声明，不保证任意镜头、机身及固件组合可用。
- 官方链接仅是复核入口，不等于已读取该页面并证实所有字段。空值表示未知，不表示不支持。

## 界面上传和命令行导入

在知识库导入页面选择演示目录里的 20 个 JSON 文件，点击“校验并预览”，检查型号、器材知识库和“允许检索：否”，再确认保存草稿。已导入的相同 ID 和版本会显示未变化，不会重复新增。

全量校验和导入可使用现有命令：

```powershell
python -m camera_assistant.knowledge.cli import data/knowledge_drafts/opensource-equipment-20261014 --dry-run
python -m camera_assistant.knowledge.cli --db data/knowledge.db import data/knowledge_drafts/opensource-equipment-20261014
```

普通 CLI 导入不会自动备份。需要重新下载、转换并备份导入时，可使用本批脚本：

```powershell
# 下载固定提交的数据和许可，生成相同规则卡，不导入数据库
python scripts/prepare_open_equipment.py

# 有原始缓存时离线重跑；先验证快照哈希和已有文件一致性
python scripts/prepare_open_equipment.py --offline

# 先在独立临时库验证全量写入和幂等性，再备份本地库并保存草稿
python scripts/prepare_open_equipment.py --offline --import-db data/knowledge.db
```

脚本遇到已有不同内容的文件会停止，不覆盖人工修改。同一知识 ID 和版本出现内容冲突时，公共存储接口整批事务回滚。导入报告保存为来源目录中的 `local-import-时间戳.json`，包括导入数量、备份位置、旧记录完整性与 SQLite 完整性检查结果。不会启动应用或调用模型 API。

## 本次本地导入结果

2026 年 10 月 14 日已新增 7,546 条草稿，数据库记录由 101 条变为 7,647 条。原有记录逐行保持不变，SQLite 完整性检查返回 `ok`，新增记录全部为 `draft` 且不允许检索。

导入前的备份为 `data/backups/before-opensource-equipment-20261014-20261014T152628096522Z.db`。详细记录在 `knowledge_sources/opensource-equipment-20261014/local-import-20261014T152633048378Z.json`，时间戳使用 UTC。

全量 JSON 的 CLI 格式校验通过；独立测试库的全量导入、重复导入不新增、草稿检索隔离通过。20 文件示例也通过真实上传桥接的预览和保存测试。新增测试及现有导入、存储、上传、CLI 回归合计 **154 项通过，1 项跳过**；未在真实浏览器中逐项点击全部批次。

## 审核和正式使用

先按常用设备挑选一小批，核对厂家手册、地区版本、原生卡口、镜头焦段及各焦段光圈条件；对冲突型号保留隔离。不能为了增加检索条数批量把本批草稿设为已验证。

需要补充或开放检索的内容应建立更高版本，保留社区来源及许可，并添加逐项厂家证据。确认 `retrieval_allowed`、适用条件和许可后，再走提交、审核、发布流程。Lensfun 衍生资料继续标注 CC BY-SA 3.0，Z Mount 衍生资料保留 CC BY 4.0 署名及修改说明，不将这些数据统一改标为项目代码许可。

设备选择器和参数校验仍读取 `knowledge/cameras/camera_profiles.yaml`、`knowledge/devices/phone_profiles.yaml` 及镜头档案。RAG 草稿导入和设备目录扩展是两个独立步骤；后续必须把审核通过的器材规格映射到运行时档案，并添加型号、卡口、画幅、焦段及光圈联动测试，才能改变用户选项。
