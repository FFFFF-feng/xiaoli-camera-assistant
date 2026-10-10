3. 六类库的资料范围

| 库 | 必须整理什么 | 必须说明的边界 | 交付形式 |
| --- | --- | --- | --- |
| 场景库 | 场景定义、可观察特征、主体、光线、运动、常见问题、别名 | 用户想拍的场景不一定等于图中场景；不能确认的信息保留未知 | 场景卡／YAML ＋示例索引 |
| 构图库 | 主体布局、留白、居中／对称、引导线、地平线、前景层次、边缘干扰 | 每条原则都有适用条件和例外；不能把三分法符合程度等同于照片好坏 | 规则卡＋结构化条件＋案例 |
| 风格库 | 目标表达、构图倾向、光线倾向、景深目标、色彩倾向 | 区分拍摄阶段与后期阶段；避免只写“高级、电影感”等空泛标签 | 风格卡＋关联规则／案例 |
| 拍摄技术库 | 曝光模式、光圈／快门／ISO、曝光补偿、对焦、测光、手持、运动与失败排查 | 区分硬件上限、建议起点和案例实际参数；不要声称单一参数普遍最佳 | 单问题知识卡＋条件与风险 |
| 器材库 | 机身、镜头、画幅、ISO、快门类型、模式能力、焦段与光圈限制 | 按机型、镜头、焦段和模式记录；未知能力不能写成支持或固定默认值 | 结构化规格＋操作说明＋逐字段出处 |
| 参考案例库 | 原图、目标、条件、问题、调整动作、裁切或重拍结果、评价 | EXIF 不是最佳参数答案；真实裁切、实拍和生成示意必须区分 | 授权图片＋标注记录＋规则关联 |

反馈案例先进入待审核区，不能自动升级为知识。独立评测集不属于上述六库，始终与检索资料分开。

## 4. 所有队员必须遵守的知识规则

### 4.1 给结论分类

- `manufacturer_fact`：官方手册或规格可核验的器材事实。
- `guideline`：摄影原则与建议，必须有适用条件、例外和风险。
- `observed_case`：一次真实拍摄的记录，不推广为通用规律。

图像或用户字段还需标记信息来源：`exif`、`user_report`、`human_annotation`、`model_inference`、`unknown`。模型推断不能伪装成 EXIF 或人工事实。

### 4.2 一条卡片解决一个问题

例如“单人肖像的视线方向留白”“手持拍摄出现模糊时如何排查”，不要把一本书或整篇长教程不加整理地作为一条知识。

提取时保留上下文和脚注，特别是参数表中的快门类型、摄影／视频模式、限制条件。OCR 和 AI 摘要只能辅助，数字和单位必须人工核对。

### 4.3 参数必须带条件

至少确认与结论相关的：曝光模式、主体运动、手持／支撑状态、镜头、焦段、最大光圈、快门类型、光线线索和目标效果。缺少关键条件时缩小结论范围或暂缓发布。

- 快门以秒记录，例如 `0.004` 秒对应 `1/250` 秒；若另存分母，字段名称必须明确。
- 光圈存 f 数值，ISO 存数值，不把展示字符串当可计算参数。
- 焦距以 mm 记录，区分实际焦距与 35mm 等效焦距。
- ISO 区分普通范围、扩展范围、自动 ISO 支持范围及团队建议上限。
- 机械、电子前帘、电子快门按实际支持情况分别记录，不合并成一个最快快门事实。
- 变焦镜头最大光圈按焦段条件记录；未知中间焦段限制不要由模型编造。
- 参数建议是起点或范围，不是已保证正确的曝光；防抖标称级数不是保证移动主体清晰的能力。

### 4.4 构图规则必须可执行

每条规则写明目标、所需视觉信息、适用条件、保护区域、动作、例外和解释依据。未确认视线方向或关键区域时，不强行输出对应操作。

真实裁切方案只能利用原图内已有内容。改变机位、移除遮挡、看到画外区域等属于重拍建议；不能把生成示意图当成可保证实现的画面。

### 4.5 统一图片和坐标

坐标基准为经过 EXIF 方向校正后的标注基图；记录其宽、高、基图版本或哈希。原点左上，x 向右、y 向下，框为归一化 `[x1, y1, x2, y2]`。

有效框应满足 `0 <= x1 < x2 <= 1`、`0 <= y1 < y2 <= 1`。人物关键区域、干扰物等采用同一基准。

展示缩放须正确映射；裁切、翻转或旋转生成新图后，要变换或重新生成标注，不能直接沿用旧坐标。无法可靠标注的字段用 `null`，不要填写猜测值。

### 4.6 来源、权限与隐私分开记录

记录作者／发布者、原始链接、手册页码或章节、访问／核验日期、资料版本、使用许可。原始出处优于转载截图。

- 官方资料可用于核验事实，不代表整本手册或配图可随意重新发布。
- 仓库代码许可证不自动覆盖其引用的照片、产品图和教材 PDF。
- 照片拍摄者的许可与被摄人物的同意分别核验。
- 图片权限分别记录保存、检索使用、公开展示、再分发；不要用一个“已授权”代替全部用途。
- 权限不明确时，只登记来源链接，暂不收录正文或图片。
- 原图与脱敏副本分别管理。公开副本不保留 GPS、精确时间、序列号、人物身份等敏感信息；日志不打印完整 EXIF。
- 不把私人照片、授权证明、密钥、第三方整本教材或受限数据集提交 GitHub。

## 5. 可复制的提交模板

以下模板均为待适配规范示例，不是已经核验的知识。复制到草稿区后填写；禁止直接作为正式语料发布。

### 5.1 文字知识卡模板：构图／技术／风格／场景

```markdown
---
schema_version: "draft-1"
knowledge_id: "待分配唯一ID"
library: "composition"
knowledge_type: "guideline"
category: "composition"
scene: "待确认标准场景ID"
subject: "person"
motion: "unknown"
source: "待填写作者或发布者"
source_url: "待填写原始链接"
source_location: "待填写页码或章节"
rights_status: "pending"
review_status: "draft"
author: "待填写整理人"
reviewer: ""
verified_at: ""
version: "1"
---
# 标题：一条卡片只解决一个问题

## 目标与结论
说明帮助用户解决什么，结论是事实、建议还是案例观察。

## 适用条件与所需信息
写明场景、目标、器材或图像条件；缺失时如何处理。

## 执行动作
写成用户可执行的步骤；需要程序执行的条件另附结构化规则。

## 例外、限制与风险
说明什么时候不采用、何时应澄清或改用其他方案。

## 依据与案例
关联来源ID、具体位置、已审核案例ID；没有案例就注明缺失。

## 审核记录
记录核验事项、意见、修改内容、审核人和日期。
```

填写时按实际所属库修改 `library`、`category`、`scene`、`subject` 等字段，分配唯一 ID，不照抄占位值。构图卡必须补充保护区域与几何条件；风格卡必须区分拍摄目标和后期目标；技术卡必须区分硬件上限与建议值。

### 5.2 器材事实模板

```yaml
schema_version: "draft-1"
equipment_id: "equipment_template_001"
camera_model: null
lens_model: null
camera_firmware: null
review_status: draft
author: null
reviewer: null
facts:
  - field: "fastest_shutter_seconds"
    value: null
    unit: "s"
    conditions:
      capture_mode: null
      shutter_type: null
    source_id: null
    source_location: null
    verification_status: pending
  - field: "maximum_aperture_f_number"
    value: null
    unit: "f_number"
    conditions:
      lens_model: null
      actual_focal_length_mm: null
    source_id: null
    source_location: null
    verification_status: pending
conflicts: []
notes: []
```

每个关键事实关联出处。团队建议的自动 ISO 上限应另存为 `guideline`，不能混入厂家硬件事实。相互冲突的资料进入待核验区，不取平均、不静默覆盖。

### 5.3 图片案例模板

```yaml
schema_version: "draft-1"
case_id: "case_template_001"
capture_session_id: null
split_group_id: null
dataset_split: "reference"
scene_id: null
user_goal: null
style_id: null
before_image_id: null
after_image_id: null
after_image_type: null  # actual_reshoot / crop / generated_illustration
annotation_base:
  image_id: null
  width: null
  height: null
  image_hash: null
  orientation_corrected: null
subject_bbox_xyxy_normalized: null
gaze_direction: unknown
motion_direction: unknown
protected_regions: []
horizon: null
distractions: []
capture_parameters:
  camera_model: null
  lens_model: null
  actual_focal_length_mm: null
  aperture_f_number: null
  shutter_seconds: null
  iso: null
  exposure_mode: null
  field_sources: {}
issues: []
actions: []
linked_knowledge_ids: []
human_evaluation:
  reviewer: null
  result: null  # improved / unchanged / worse / uncertain
  reasons: []
  confounding_changes: []
rights:
  photographer_permission: unknown
  depicted_person_permission: unknown  # 非人物案例可按实际标记 not_applicable
  storage: unknown
  retrieval_use: unknown
  public_display: unknown
  redistribution: unknown
review_status: draft
```

上述 ID 是占位示例。缺失 EXIF 不补造参数；将人工提供值、模型推断与 EXIF 区分。前后对照记录光线、机位、主体姿态等共同变化，不能把所有改善都归因于助手。



流程：来源登记 → 资料提取 → 单条整理 → 事实／权限核验 → 图片标注复核 → 发布 → 检索与应用测试 → 根据错误修订。

状态约定：

- `draft`：整理中，禁止正式检索。
- `pending_review`：等待独立审核，禁止正式检索。
- `needs_revision`：有冲突、缺条件、缺权限或标注问题，退回修改。
- `approved`：内容审核通过；还需满足对应使用权限才能发布。
- `published`：完成格式适配、发布与索引核验。
- `retired`：停用；从正式检索和相关索引移除，保留必要版本记录。

上述状态已由新增的受管知识库执行，实际导入格式、审核命令和队友接口见 [知识库工程说明](knowledge-development.md)。本文 `draft-1` 模板是讨论稿，不能直接导入当前 `schema_version: 1` 模型。默认旧版目录仍不执行受管审核，草稿继续与其隔离；受管检索每次读取发布状态，发布／停用会立即影响后续查询。切换配置或修改旧版目录时仍需重启流程。权限受限的图片即使内容审核通过，也不能公开展示或再分发。

每次交接附上：任务ID、变更条目、来源ID、审核意见、未解决问题、版本、测试记录。修改已发布条目时重新审核，并记录旧结论、修订原因和影响范围。
