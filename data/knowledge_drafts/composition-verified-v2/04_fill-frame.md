---
schema_version: 1
knowledge_id: expanded-v1-composition-fill-frame
library_id: composition
title: "收紧取景：减少干扰，同时保留故事背景"
kind: guideline
version: 2
dataset_split: reference
author: "小栗资料整理助手（待独立复核）"
tags: ["构图", "填满画面", "主体占比", "取景", "环境叙事", "构图核验v2"]
conditions: {}
source:
  name: "Adobe｜Fill the frame photography"
  url: "https://www.adobe.com/creativecloud/photography/technique/fill-the-frame.html"
  location: "What is fill the frame photography? / When should you use it?"
  license: "仅原创短归纳与出处；未保存或再分发原文和配图，检索及公开用途待人工核对。"
  retrieval_allowed: false
payload:
  core_claim: "更紧的取景可强调主体细节，但承载故事的背景应按表达目标保留。"
  goal: "比较主体突出与环境信息之间的取舍"
  previous_version: 1
  requires: ["用户目标偏向突出主体或细节", "确认哪些背景信息必须保留", "移动或更换取景方式前检查安全与设备能力"]
  actions: ["比较原构图与主体占比更大的版本", "检查被排除的背景是否影响故事或人物关系", "分别说明移动重拍、镜头取景和现有照片裁切的选择"]
  limitations: ["不设置跨场景通用的人物占比或头顶留白", "不指定未确认机型的固定倍数或镜头", "裁切不会改变拍摄机位，放大与靠近不能视为完全等效", "不为更紧取景冒险接近主体或进入禁入区域"]
  suggested_text: "若主要想展示主体细节，可以比较更紧的取景；如果背景在讲故事，就保留相关部分。"
  numeric_default: null
  automatic_execution: false
  discovery_source_ids: [douyin-shortlist-v1-002, douyin-shortlist-v1-003, douyin-shortlist-v1-004]
  discovery_note: "选题关联不代表原视频的固定倍数、角度或身材效果已通过核验。"
  verification:
    checked_at: "2026-10-13"
    status: cross_source_agreement
    scope: "核对紧取景强调细节及背景保留例外；设备限制、选择流程为整理者归纳，未做机型实测。"
    needs_human_review: true
    human_review_status: not_performed
    field_test_status: not_performed
    evidence:
      - source_id: adobe-fill-frame
        url: "https://www.adobe.com/creativecloud/photography/technique/fill-the-frame.html"
        location: "What is fill the frame photography? / When should you use it?"
        read_status: body_read
        supports: "收紧取景减少背景；背景帮助叙事时可保留其中一部分。"
      - source_id: canon-composition
        url: "https://www.canon.com.au/get-inspired/mastering-photo-composition-ideas"
        location: "Fill the Frame"
        read_status: body_read
        supports: "紧取景可减少干扰并突出细节。"
---

更紧的取景可强调主体细节，但承载故事的背景应按表达目标保留。

比较原图与主体更大的方案，检查环境信息是否仍足够。用户想记录人与环境的关系时，不必追求填满画面；没有统一的人物占比、头顶“一格”或固定变焦倍数。

移动重拍、选择镜头和裁切现有照片应分别说明。不能把裁切视为改变机位，也不能在未确认机型、距离及对焦能力时保证效果。
