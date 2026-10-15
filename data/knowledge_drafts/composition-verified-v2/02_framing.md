---
schema_version: 1
knowledge_id: expanded-v1-composition-framing
library_id: composition
title: "前景框架：用已有结构引导注意力，先检查遮挡"
kind: guideline
version: 2
dataset_split: reference
author: "小栗资料整理助手（待独立复核）"
tags: ["构图", "前景", "框中框", "主体遮挡", "构图核验v2"]
conditions: {}
source:
  name: "Adobe｜Emphasis in photography"
  url: "https://www.adobe.com/creativecloud/photography/discover/emphasis-in-photography.html"
  location: "Framing"
  license: "仅原创短归纳与出处；未保存或再分发原文和配图，检索及公开用途待人工核对。"
  retrieval_allowed: false
payload:
  core_claim: "现场的门窗、枝叶等结构可围绕主体形成构图框架。"
  goal: "用已有前景组织画面，引导注意力"
  previous_version: 1
  requires: ["画面确有可利用的结构", "明确用户要保留的主体区域", "取景调整不破坏环境、不危及安全"]
  actions: ["选择实际存在的门窗或枝叶边缘", "比较框架是否遮住用户想强调的部分", "拍一张有框、一张无框的版本再选择"]
  limitations: ["不生成不存在的现场前景作为移动指令依据", "遮挡也可以是创作选择，不默认所有遮挡错误", "装饰边框或生成式添加不能称为现场框架"]
  suggested_text: "这里已有前景可以作框架。先确认它没有遮住你想强调的部分，再比较有框和无框的取景。"
  numeric_default: null
  automatic_execution: false
  discovery_source_ids: [douyin-shortlist-v1-001]
  discovery_note: "仅关联前景框架选题；不保存博主原片或照搬案例。"
  verification:
    checked_at: "2026-10-13"
    status: cross_source_agreement
    scope: "两家资料支持现场框架的核心原则；遮挡检查和比较流程为整理者归纳，未实拍验证。"
    needs_human_review: true
    human_review_status: not_performed
    field_test_status: not_performed
    evidence:
      - source_id: adobe-emphasis
        url: "https://www.adobe.com/creativecloud/photography/discover/emphasis-in-photography.html"
        location: "Framing"
        read_status: body_read
        supports: "枝叶、门窗等现场元素可为主体提供框架。"
      - source_id: canon-composition
        url: "https://www.canon.com.au/get-inspired/mastering-photo-composition-ideas"
        location: "Framing"
        read_status: body_read
        supports: "自然框架可引导注意并增加空间层次。"
---

现场的门窗、枝叶等结构可围绕主体形成构图框架。

先确认结构确实存在，再检查它与主体的遮挡关系，比较有框和无框版本。需要清楚展示面部或物体细节时，优先保留用户指定的区域；用户希望朦胧遮挡时，则不机械纠正。

不保证加入前景一定更好看，不要求触碰或折损植物。软件新增边框和生成式添加前景应另行标注，不能伪称现场取景。
