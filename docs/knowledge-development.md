# 知识库工程底座：开发规划与使用说明

本模块服务于负责知识库搭建的队员。它负责格式、导入、存储、审核发布、检索和可追溯性，不负责摄影知识整理，也不包含新构图算法。

## 1. 本轮范围与后续路线

| 阶段 | 工作 | 本轮状态 |
| --- | --- | --- |
| 工程底座 | 六库注册、统一模型、SQLite、草稿与版本、审核退回／发布、审计日志 | 本轮实现 |
| 导入与查询 | JSON／YAML／Markdown校验、批次原子导入、dry-run、分库关键词检索、结构化查询 | 本轮实现 |
| 兼容接入 | 旧版／受管检索显式切换，页面展示依据状态，保留原有演示 | 本轮实现 |
| 管理界面 | 导入预览、审核表单、版本比较、身份认证和权限 | 后续，先用命令行 |
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
| cli.py／__main__.py | 命令行管理入口 |

接入位置：`E:\develop\cmera\src\camera_assistant\pipeline.py`；配置：`E:\develop\cmera\src\camera_assistant\config.py`。

模型与导入格式由知识库队员维护；整理队员只提交符合模板的内容；构图队员通过检索器获取规则，不直接操作数据库表。

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

- 条件对象的键由模块共同约定；已有参数链路提供 `scene`、`subject`、`motion`、`camera_profile_id`、`camera_format`、`handheld`、`tripod`。
- 标量条件精确匹配；列表表示多个可接受值；`null`表示未声明限制。
- 资料声明了条件但请求没有该字段时，保守排除。空条件表示通用资料。
- 不支持数值区间或复杂谓词执行；不能把 `{"min": 50}` 当成已实现的范围约束。
- `query_structured` 对已发布payload作点路径等值筛选，并接受 `conditions` 上下文作同样的适用条件过滤；仍不替业务模块证明器材适配。
- `top_k`范围1～100；匹配不到返回空列表，不自动补造知识或切回旧资料。
- 结果携带知识ID、所属库、版本、来源位置、审核人、内容哈希；相关度不是准确率。

JSON结构查询只返回资料，不会自动执行里面的脚本、URL或指令。检索资料仍应作为数据而非系统指令对待；后续模型调用还需要评测引用真实性和提示注入风险。

## 8. 接入现有应用

默认保持旧版演示资料，避免在空库阶段影响已有功能。在自己的本地 `.env` 设置：

```dotenv
KNOWLEDGE_RETRIEVAL_MODE=managed
KNOWLEDGE_DB_PATH=data/knowledge.db
```

重启Streamlit以加载配置。受管模式不会混入旧版Markdown；没有已发布匹配资料时，页面明确提示缺少受管知识依据，演示参数生成器仍按旧规则运行，不代表新知识准确性已验证。

目前参数推荐链路只检索 `scene`、`technique`、`equipment`；`composition`、`style`、`case` 已具备独立查询接口，留给构图队员接入。原有场景候选和机型能力服务仍使用旧YAML配置，不会自动被结构化资料覆盖。

## 9. 验证与队友交接

```powershell
python -m pytest -q
python -m ruff check .
```

验证范围：空库、格式错误、重复键、批次原子性、版本冲突、互审、许可／评测拦截、发布切换、停用、条件过滤、来源追踪、CLI和原应用回归。测试数据仅用于软件行为验证，不是正式语料或实拍效果证据。

给整理队员：本节模板、六库ID、条件键约定、dry-run和审核交接方式。

给构图队员：`search`／`query_structured` 接口、结果ID与版本、明确的空库行为；需要额外几何字段时放进payload并约定模型，不自行改库表。

给界面队员：保留来源、版本和空依据提示；后续管理页面调用存储API，不绕过状态流转。
