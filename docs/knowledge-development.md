# 知识库工程底座：开发规划与使用说明

本模块服务于负责知识库搭建的队员。它负责格式、导入、存储、审核发布、检索和可追溯性，不负责摄影知识整理，也不包含新构图算法。

## 1. 本轮范围与后续路线

| 阶段 | 工作 | 本轮状态 |
| --- | --- | --- |
| 工程底座 | 六库注册、统一模型、SQLite、草稿与版本、审核退回／发布、审计日志 | 本轮实现 |
| 导入与查询 | JSON／YAML／Markdown校验、批次原子导入、dry-run、分库关键词检索、结构化查询 | 本轮实现 |
| 兼容接入 | 旧版／受管检索显式切换，页面展示依据状态，保留原有演示 | 本轮实现 |
| 导入管理界面 | 独立上传／粘贴、格式校验预览、确认后保存草稿、只读条目与审计 | 已实现，见独立工作台；审核发布仍使用命令行 |
| 完整协作管理 | 审核表单、版本比较、身份认证和权限 | 后续 |
| 检索升级 | 有实际资料与题集后对比关键词和向量检索，再决定是否增加混合检索 | 后续，不预设效果提升 |
| 图片案例与规则执行 | 图片资源授权存储、图文检索、几何标注校验、构图规则执行 | 由队友接口协作，当前仅保存JSON结构 |

不新增模型调用或向量数据库依赖；使用现有 Pydantic、PyYAML 与 Python 内置 SQLite。没有自动下载资料，没有自动将旧知识判定为审核通过，没有导入正式内容。

## 2. 六类库与数据关系

固定注册六个逻辑库，共用一个数据库：

| library_id | 名称 | 用法 |
| --- | --- | --- |
| scene | 场景库 | 场景定义、适用条件与解释 |
| composition | 构图库 | 构图规则及说明；执行算法由构图模块负责 |
| style | 风格库 | 目标风格与关联规则 |
| technique | 拍摄技术库 | 曝光、对焦、故障排查等资料 |
| equipment | 器材库 | 器材结构化事实和操作说明 |
| case | 参考案例库 | 案例描述、标注、资源ID等JSON元数据 |

`content` 保存文本，`payload` 保存JSON结构，两者至少有一个非空。器材参数查询不应只依赖语义相似度；使用 `query_structured` 精确筛选，并由参数模块核验单位与条件。

```text
队员整理的文件
    ↓ 格式、重复键、字段和同批冲突检查
SQLite草稿与版本 ──→ 审计记录
    ↓ 提交 → 非作者审核 → 权限与评测边界校验
已发布版本
    ├─ 分库、条件过滤 → 关键词检索 → 带来源与版本的KnowledgeHit
    └─ payload精确查询 → 器材／规则模块
```

## 3. 文件与职责

源码根目录：`E:\develop\cmera\src\camera_assistant\knowledge\`。

| 文件 | 职责 |
| --- | --- |
| models.py | 知识记录、来源、版本与状态的数据模型 |
| store.py | 六库注册、SQLite事务、版本、状态流转、审计日志 |
| importer.py | 严格文件解析、批次检查与原子导入 |
| retriever.py | 只读已发布资料、条件过滤、来源追踪、结构化查询 |
| context.py | 从目标设备、用户明确输入及场景观测构建精确检索条件；不读取参考照片EXIF |
| cli.py／__main__.py | 命令行管理入口 |
| uploads.py | 上传尺寸与文件名限制、临时预览、输入指纹与原子草稿提交 |
| ui_helpers.py | 工作台显示词汇与默认无检索许可的占位模板 |

接入位置：`E:\develop\cmera\src\camera_assistant\pipeline.py`；配置：`E:\develop\cmera\src\camera_assistant\config.py`。

模型与导入格式由知识库队员维护；整理队员只提交符合模板的内容；构图队员通过检索器获取规则，不直接操作数据库表。

### 独立导入工作台

入口 `knowledge_app.py`，样式 `assets/knowledge.css`。使用项目已有环境启动：

```powershell
python -m streamlit run knowledge_app.py --server.address 127.0.0.1 --server.port 8503
```

在 `http://localhost:8503/` 操作，使用同一个 `KNOWLEDGE_DB_PATH` 配置。页面包含「导入工作台」「知识条目」「操作记录」；左侧库范围只筛选浏览，不改写上传记录的 `library_id`。

1. 上传一文件一条的JSON／YAML／Markdown标准记录，或直接粘贴一条内容。
2. 点击「校验并预览」，检查条目、来源、适用条件与授权字段。单文件2MiB、最多20文件、总计10MiB；同批有任何错误均禁止写入。
3. 勾选确认后点击「导入为草稿」。提交时复核预览完整性，并调用现有原子事务；同内容同版本幂等，冲突不部分写入。
4. 从只读条目与日志查看结果；提交审核、互审和发布仍执行下文CLI。

用于验证实际上传与保存的 [样本集与预期结果](../data/knowledge_samples/upload-smoke-v1/README.md) 覆盖六库、三类文件格式、错误批次、幂等、冲突与版本更新。只上传指定文件，不导入父目录或说明文档；所有样本均为禁止检索的测试数据。

只读示例是占位模板，不会入库。改变输入会清除旧预览和确认。原始上传仅临时解析，返回前清理；正式保存的是结构化记录。JSON模板默认 `retrieval_allowed=false`，不提供正式摄影内容或自动判断授权。

没有新增审核页面、登录鉴权或公网部署能力；只应在本机／可信团队环境运行。格式检查不证明知识准确，实拍与人工事实核查仍是必要环节。

## 4. 初始化与日常命令

在项目根目录，使用已经安装项目依赖的 Python：

```powershell
python -m camera_assistant.knowledge init
python -m camera_assistant.knowledge libraries
python -m camera_assistant.knowledge stats
python -m camera_assistant.knowledge schema
python -m camera_assistant.knowledge list
```

若尚未安装项目，先执行 `python -m pip install -e ".[dev]"`。安装后也可用 `camera-knowledge` 替代 `python -m camera_assistant.knowledge`。

默认数据库为 `E:\develop\cmera\data\knowledge.db`，不提交Git。可通过 `KNOWLEDGE_DB_PATH` 或全局 `--db` 指定其他文件；相对环境配置路径基于项目根目录解析。

```powershell
python -m camera_assistant.knowledge --db data/team-knowledge.db init
python -m camera_assistant.knowledge --help
```

正常初始化／导入可以创建数据库；dry-run只解析资料，不创建数据库、不检查已有数据库中的版本冲突。只读管理命令不应当用来隐式初始化，请先执行 init。

### 导入与审核

```powershell
python -m camera_assistant.knowledge import docs/knowledge-drafts --dry-run
python -m camera_assistant.knowledge import docs/knowledge-drafts
python -m camera_assistant.knowledge show demo_card_001
python -m camera_assistant.knowledge submit demo_card_001
python -m camera_assistant.knowledge approve demo_card_001 --reviewer reviewer_B --note "已核验出处与适用条件"
python -m camera_assistant.knowledge publish demo_card_001
python -m camera_assistant.knowledge search "构图 留白" --library composition --top-k 4
python -m camera_assistant.knowledge structured --library equipment
python -m camera_assistant.knowledge audit
python -m camera_assistant.knowledge retire demo_card_001
```

上述命令中的文件夹与ID须换成实际资料；文件夹不会自动填充。不要直接导入整个 `docs/` 或旧 `knowledge/`，旧资料尚未适配新模型。发布命令只适用于已审核、明确允许检索的参考资料；下面模板默认禁止检索，因此不能发布。

发现问题时不批准，而是执行 `python -m camera_assistant.knowledge reject demo_card_001 --reviewer reviewer_B --note "缺少适用条件"`。原记录进入 `needs_revision`，作者通过新增版本修正，不覆盖旧正文。

支持显式 `--version` 操作指定版本；默认操作最新版本。修改正文、来源、授权、条件等任一内容需增加版本号再导入。审核／发布不由文件字段控制。

## 5. 可交给整理队员的实际格式

以下JSON是草稿模板，不是正式知识，也不是准确性评测素材。只保存在草稿区。

```json
{
  "schema_version": 1,
  "knowledge_id": "demo_card_001",
  "library_id": "composition",
  "title": "待填写真实知识标题",
  "kind": "guideline",
  "content": "此处填写经过整理的正文。当前仅为模板，禁止作为摄影依据。",
  "payload": {},
  "tags": [],
  "conditions": {},
  "source": {
    "name": "待填写原始资料发布者",
    "url": "",
    "location": "待填写页码或章节",
    "license": "待核验",
    "retrieval_allowed": false
  },
  "author": "author_A",
  "version": 1,
  "dataset_split": "reference"
}
```

`kind` 只能是 `manufacturer_fact`、`guideline`、`observed_case`。缺失结构化事实使用JSON `null`；参数单位与模式条件由整理规范和业务模块约定，不由通用库猜测。

YAML使用相同字段。Markdown必须有YAML前置元数据，正文成为 `content`。不允许重复键、未知字段、导入状态或审核人；单个文件最大2MiB，不支持PDF、图片文件、网络URL或符号链接导入。

目录导入先检查全部文件，再通过一个数据库事务提交；任何格式、冲突或保存失败都不应留下半批内容。重复导入相同ID／版本／内容是幂等操作，不产生新版本。

原知识整理手册中的 `draft-1` 模板是讨论稿，不能直接作为本工程的 `schema_version: 1` 格式导入。以本节和实际模型为准。

## 6. 发布边界与版本规则

- 新资料或新版本统一为 `draft`，文件不能指定为已发布。
- `draft → pending_review → approved → published → retired`。
- 待审核记录也可经非作者退回到 `needs_revision`，必须填写理由；修正内容以新版本重新进入草稿流程。
- 审核人不能为空，且不能与作者相同；内容修改以新版本重新提交。
- `dataset_split=evaluation` 永远不能发布到检索库。
- `source.retrieval_allowed=false` 不能发布。
- 发布新版本原子替换旧发布版本；仅导入或批准草稿不会停用正在使用的旧版。
- 旧版保留可追溯记录，停用资料即刻从受管检索移除。
- 检索每次读取当前发布状态，不需要重新构建内存关键词索引。

这里是本地可信团队工具：审核人姓名由操作者填写，没有账户认证或角色权限，也不是防篡改审计系统。若部署开放服务，需要另加身份认证、访问控制、授权证明管理与备份方案。

内容通过审核不等于拥有所有图片用途权限。`retrieval_allowed` 只表达检索使用许可；公开展示、再分发和被摄人物许可仍需队员另外核验。当前不保存图片二进制、私人原图或授权证明。

## 7. 检索接口与条件约定

```python
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore

retriever = ManagedKnowledgeRetriever(KnowledgeStore("data/knowledge.db"))
hits = retriever.search(
    "主体位置 留白",
    libraries=["composition", "style"],
    conditions={"scene": "outdoor_portrait", "motion": "static"},
)
equipment = retriever.query_structured(
    "equipment", filters={"camera_model": "待填写型号"}
)
```

规则：

- 条件对象的键由模块共同约定；参数与构图链路共同使用 `knowledge.context.build_knowledge_conditions(request, scene, camera, canonical_subject, localization=None)`。基础字段为 `scene`、`subject`、`motion`、`camera_profile_id`、`device_type`、`handheld`、`tripod`、`subject_confirmed`，相机另有 `camera_format`，手机保留 `phone_profile_id`、`phone_capture_mode`、`phone_lens_id`、`phone_pro_controls_confirmed`。`subject` 使用运行时场景定义中的标准主体类别（包括 `person`、`pet`、`landscape`、`food`、`architecture`、`bird`、`fireworks`、`small subject`、`moving subject`、`product` 等），而不是模型自由文本描述。具体物种或属性可用标签检索，不应把 `cat`/`dog` 误写成这里的 `pet` 条件。
- 标量条件精确匹配；列表表示多个可接受值；`null`表示未声明限制。
- 资料声明了条件但请求没有该字段时，保守排除。空条件表示通用资料。
- 不支持数值区间或复杂谓词执行；不能把 `{"min": 50}` 当成已实现的范围约束。
- `query_structured` 对已发布payload作点路径等值筛选，并接受 `conditions` 上下文作同样的适用条件过滤；仍不替业务模块证明器材适配。
- `top_k`范围1～100；匹配不到返回空列表，不自动补造知识或切回旧资料。
- 结果携带知识ID、所属库、版本、来源位置、审核人、内容哈希；相关度不是准确率。

JSON结构查询只返回资料，不会自动执行里面的脚本、URL或指令。检索资料仍应作为数据而非系统指令对待；后续模型调用还需要评测引用真实性和提示注入风险。

### 目标设备与条件兼容修复（2026-10-14）

新增条件的取值与证据边界如下。所有键在 `KNOWLEDGE_CONDITION_KEYS` 中登记；登记字段不表示每次请求都具备该事实。卡片要求的字段缺失时，仍由检索器排除。

| 条件 | 可靠来源与精确取值 |
| --- | --- |
| `camera_model` | 已收录且明确选中的设备档案优先；`target_model_name` 仅补充通用画幅／未知手机档案，不允许把具体档案的参数能力与另一个自填机型混用。具体型号别名规范为卡片同一型号，例如 `Sony α7 IV` → `Sony ILCE-7M4`，`iPhone 15` → `Apple iPhone 15`。未选具体档案且未自填型号时省略；不继承相邻代际或 Pro／Ultra 变体 |
| `lens_model` | 仅用户明确的 `target_lens_name`；如 `RF50mm F1.8 STM` → `Canon RF50mm F1.8 STM`。没有目标镜头时省略，不从参考照片EXIF或机身型号推断 |
| `app` | 用户明确的 `camera_app`；已知、目标一致的手机档案可用 `native_app`。`Apple 相机` → `Apple Camera`；通用档案的“原生相机”不能证明具体应用 |
| `os_major` | 仅用户明确输入；已知 Apple iPhone 的 `18` → `iOS 18`，其他设备保留输入整数，不冒充 iOS，也不从档案检查日期推断系统版本 |
| `capture_mode` | 当前静态照片工作流的相机为 `still_photo`；手机 `auto` → `photo`，`portrait`／`night`／`pro` 保留各自值，不扩大成所有照片模式 |
| `lighting` | 显式 `lighting_type` 优先，否则保留普通 `scene.lighting` 观测描述。频闪卡片只接受用户确认的 `flickering_artificial`；单张照片的模型猜测不能确认频闪 |
| `shutter_type` | 仅用户输入；`efcs` → `electronic_front_curtain`，`mechanical` 与 `electronic` 保留。电子快门不证明逐行读取，不能自动变成 `electronic_rolling` |
| `drive_mode` | 仅用户输入 `single`／`continuous`，未知省略 |
| `focus_mode` | 仅用户输入，`MF` → `manual`；`AF-S`／`AF-C` 保留。没有模式事实时不因为场景或建议使用MF就填写MF |
| `motion` | 用户明确运动枚举优先于模型场景结果，`静止`／`缓慢`／`快速` 分别为 `static`／`slow`／`fast`；未知沿用场景结果，不从单张图片断言速度 |

运行时新增 `architecture`、`astro_landscape`、`bird`、`concert_stage`、`fireworks`、`fog_landscape`、`group_portrait`、`indoor_sports`、`macro`、`motion`、`pet_portrait`、`portrait`、`product_still`、`snow_landscape`、`window_portrait` 共15个真实类别，并保留原有11个场景ID及接口。对应43张卡片的场景约束现可解析；没有把不同场景归并到 `general_scene`。猫／狗物种词本身不证明快速运动，静止宠物选 `pet_portrait`，明确快速运动仍选 `fast_pet`；文字中紧邻宠物名称的直接运动事实只在枚举未指定时使用。

`data/knowledge_drafts/photography-20261013/upload_cards` 中7张机身／手机卡新增具体 `camera_model`，4张镜头卡新增具体 `lens_model`；后两张原空条件的镜头卡同时限制 `device_type=camera`。共11张器材卡升为v2，正文、payload事实、作者、来源与许可证均保留。逐行电子快门卡的 `motion=moving` 另以v2改为 `motion=[slow, fast]`，使约束与既有运动枚举一致；仍保留 `shutter_type=electronic_rolling`，因此没有逐行读取事实的普通电子快门请求继续排除。集合manifest同步当前文件路径、版本及SHA-256，Git历史及数据库旧版本保留修订前资料。

本次兼容性审计由 `tests/test_knowledge_context.py` 覆盖：所有集合场景ID均已注册、条件键均在公共契约内、11张器材卡匹配正确型号并排除错误／缺失型号、型号变体不互借、未知条件保守排除、缺失系统／快门／对焦模式不补造、manifest与文件哈希一致。集合121张卡的 `source.retrieval_allowed` 全部保持false；测试只核对适用性边界，不将这些实际卡片发布或授权用于检索。同步到正式数据库必须作为新草稿导入，不能覆盖旧版本或改变发布状态。

实际离线审计结果：运行时26个场景定义；未注册场景约束0、未识别条件键0、缺少具体机身／镜头约束的器材卡0、允许检索卡0；当前集合有12张v2卡。与Git原始资料逐字段对比，12张修订卡仅 `conditions` 和 `version` 改变。定向验证命令 `python -m pytest -q tests/test_knowledge_context.py tests/test_scene_knowledge.py tests/test_knowledge_documentation.py` 通过53项，相关源码与测试Ruff通过。运动文字回归还覆盖否定描述、多个宠物运动状态冲突及静止背景前的运动宠物：无法确定当前主体运动时保留unknown；用户明确运动枚举继续优先。具体相机／手机档案不会被冲突自填型号替换，同型号别名正常匹配。完整应用回归在集成后统一执行。

## 8. 接入现有应用

默认保持旧版演示资料，避免在空库阶段影响已有功能。在自己的本地 `.env` 设置：

```dotenv
KNOWLEDGE_RETRIEVAL_MODE=managed
KNOWLEDGE_DB_PATH=data/knowledge.db
```

重启Streamlit以加载配置。受管模式不会混入旧版Markdown；没有已发布匹配资料时，页面明确提示缺少受管知识依据，演示参数生成器仍按旧规则运行，不代表新知识准确性已验证。

参数推荐链路检索 `scene`、`technique`、`equipment`。开启 `CAMERA_AI_COMPOSITION_ENABLED=true`（`glm-dino` 预设默认开启）后，独立构图链路检索 `composition`、`style`、`case`，并要求建议引用本次命中的 `document_id`（包含资料版本）。两个链路各取 Top-4，构图资料不会挤占参数资料。新增可用条件 `subject_confirmed`，仅在检测与语义关联状态为 `selected` 时为 true；它表示自动关联成立，不等于人工确认或准确率证明。原有场景候选和机型能力服务仍使用旧YAML配置，不会自动被结构化资料覆盖。

GitHub 资料文件需在部署环境导入、审核并发布后才能供受管检索使用，详见 [真实环境接入](real-environment.md)。空库及没有相关资料时，构图结果明确显示缺少知识依据；不能将文件上传或引用 ID 当作建议正确性的证明。

## 9. 验证与队友交接

```powershell
python -m pytest -q
python -m ruff check .
```

验证范围：空库、格式错误、重复键、批次原子性、版本冲突、互审、许可／评测拦截、发布切换、停用、条件过滤、来源追踪、CLI和原应用回归。测试数据仅用于软件行为验证，不是正式语料或实拍效果证据。

给整理队员：本节模板、六库ID、条件键约定、dry-run和审核交接方式。

给构图队员：`search`／`query_structured` 接口、结果ID与版本、明确的空库行为；需要额外几何字段时放进payload并约定模型，不自行改库表。

给界面队员：保留来源、版本和空依据提示；后续管理页面调用存储API，不绕过状态流转。
