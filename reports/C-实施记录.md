# C 摄影一致性实施记录

基线：986fd0594150dce96b3255c8cc77ff54e8174620；分支 codex/photography-consistency。
任务依据：协调包 03-C、00-共同约定、BASELINE.json、INTERFACES.md。
本记录采用 writing-plans 的分步验证方式；用户已要求直接执行，在本会话自行实现。

## 计划与边界

- [x] 核对独立工作树、源码导入位置、原始四图摄影错误和 13 项 Ruff。
- [x] 保留既有 46 项事实回归；先加入失败正反例，再修正局部关系检查。
- [x] 区分用户明示运动与场景估计；未知光源类别不能确认具体灯种；统一白平衡目标且保留无关对焦建议。
- [x] 对称与三分按同一主体、同一方案检查；连续取景保护可见边界，不补造新视角。
- [x] 保留 fixture 注册，跑实际 fixture、语义、并行与 ready/final 测试。
- [x] 跑归属文件 Ruff、关联后端回归与启动检查；交跨模块最小调用要求和报告，有序提交。

不修改 composition.py/pipeline.py、公共 schema、依赖或配置。真实云请求为 0。
优先关注：跨逗号条件、转折后的独立断言、泛化灯光类别、否定的白平衡目标、偏置主体与局部对称、重复校验幂等。

## 已有证据

- 原生 worktree 工具绑定外层仓库，找不到嵌套项目提交；从核对过的项目根用 git worktree add 创建独立工作树成功，未切换原目录。
- 基线 photography_facts + validator：117 passed；首次默认沙箱临时目录不可建，第二次 .tmp 父目录未建；创建工作树 .tmp 后重跑通过，均为环境问题。
- Ruff：photography_facts.py 6 项、test_photography_facts.py 7 项，与交接一致。
- 当前 fixture 使用跨测试模块导入注册；不能直接删掉 F401 导入。
- 启动入口三个文件已阅读，本轮不涉及入口/依赖/配置变更，维护交 A。

## 实施结果与决策

- 首轮新增36个案例，25个 RED；修正到153项事实+validator通过。
- 自查条件泄漏/连续文字/Demo并补用例，159项通过；原13项Ruff清零。
- requesting-code-review只读审查发现6类Important，无Critical；已用8个RED用例覆盖后修复，167项通过，不做额外云审查。
- 用户肯定声明和问句/条件/否定补6例；顶层构图观察补1例；事实文件最终103项（原46+新增57）。
- 决策：不把场景估计当事实；明确用户声明可作来源，结构化字段优先。raw scene 的发布归A，交最小标注建议，不越界修改。
- 决策：恢复原未测量距离拒绝链，不预先改掉其证据；两项原构图测试先复现失败，再恢复通过。
- 最终关联测试316 passed，包含实际跨模块fixture；Ruff归属4文件通过。
- 完整pytest沙箱socketpair阻塞已定位；受控离线包装器限制外部socket，审批后仅允许回环执行。完整回归的启动器缺前端依赖失败保留并报告；不擅自安装D/A依赖。
- 四图保存结果的本地语义重放完成，原0板样本仍为0板；真实云0，未生成新画面。
- 最终两代码提交完整回归：1500 passed、1 failed、2 skipped、1 warning，137.34s。唯一失败为隔离工作树缺前端依赖的test_forwarding_cmd_works_from_a_unicode_desktop_folder；根CMD --check退出1，同原因。
- 代码提交：32babd2206a8819d0fafff60b14a60ef68acd659、081ffcca676a60f4adb5e19b3063d3f8f874c608；文档单独提交，完整顺序见交付报告和最终消息。
