---
schema_version: 1
knowledge_id: expanded-v1-composition-background-separation
library_id: composition
title: "背景干扰：先比较机位，不默认用虚化解决"
kind: guideline
version: 2
dataset_split: reference
author: "小栗资料整理助手（待独立复核）"
tags: ["构图", "背景干扰", "主体分离", "人像", "构图核验v2"]
conditions: {}
source:
  name: "Nikon｜Take Better Portraits"
  url: "https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/take-better-portraits"
  location: "开篇背景选择、标志杆穿头与移动机位的示例"
  license: "仅原创短归纳与出处；未保存或再分发原文和配图，检索及公开用途待人工核对。"
  retrieval_allowed: false
payload:
  core_claim: "背景中的线条或物体可能与主体形成视觉干扰，换机位是可比较的解决办法。"
  goal: "让主体清楚，同时保留必要的环境信息"
  previous_version: 1
  requires: ["确认主要主体及实际可见的干扰", "知道用户是否需要环境叙事", "移动前确认现场安全"]
  actions: ["检查主体周围的杆线、亮斑与重叠边缘", "在安全范围内换一个机位，比较背景关系", "保留原构图作对照，再决定是否需要虚化"]
  limitations: ["环境信息有叙事作用时，不应一律删除", "单张图片不能确定画外背景或可移动空间", "虚化不是修复失焦的办法，不默认手机支持某种虚化模式"]
  suggested_text: "背景的线条有些抢眼。若方便，可以换一个安全机位，比较它是否仍与主体重叠。"
  numeric_default: null
  automatic_execution: false
  discovery_source_ids: [douyin-shortlist-v1-002, douyin-shortlist-v1-006]
  discovery_note: "抖音链接仅关联选题，不代表已核验完整教学或获准收录作品。"
  verification:
    checked_at: "2026-10-13"
    status: cross_source_agreement
    scope: "核对核心构图原则；动作、安全提醒及拒答边界是整理者归纳，未实拍测定效果。"
    needs_human_review: true
    human_review_status: not_performed
    field_test_status: not_performed
    evidence:
      - source_id: nikon-portraits
        url: "https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/take-better-portraits"
        location: "背景选择及移动机位示例"
        read_status: body_read
        supports: "背景干扰可通过改变机位改善。"
      - source_id: adobe-emphasis
        url: "https://www.adobe.com/creativecloud/photography/discover/emphasis-in-photography.html"
        location: "Distance / Practice makes perfect"
        read_status: body_read
        supports: "调整距离及观察角度可改变主体与其他元素的视觉关系。"
---

背景中的线条或物体可能与主体形成视觉干扰，换机位是可比较的解决办法。

先确认用户要突出什么，观察背景杆线、亮斑与主体的重叠；安全允许时改变机位，与原构图对照。环境本身在讲故事时保留必要信息，不设置“元素最多三个”的上限。

移动机位是重新拍摄建议，不等同于对现有图片裁切；不能由单张图保证另一个机位一定干净。虚化另需设备能力与合焦条件，不替代失焦排查。
