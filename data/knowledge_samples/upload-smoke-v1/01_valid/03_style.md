---
schema_version: 1
knowledge_id: upload-smoke-v1-style-001
library_id: style
title: "[上传测试] 简洁自然风格描述"
kind: guideline
payload:
  test_only: true
  desired_mood: 简洁自然
tags:
  - 上传测试
  - 风格样本
conditions:
  device_type: phone
source:
  name: 小栗上传功能自制测试样本
  location: 样本集 upload-smoke-v1 / 风格库
  license: 仅用于项目导入功能测试，未授权作为正式推荐依据
  retrieval_allowed: false
author: 上传功能测试员
version: 1
dataset_split: evaluation
---

测试风格描述：希望照片的主体明确、背景简洁、颜色自然。

本正文用于确认Markdown前置元数据会被解析，正文会写入`content`。
这是合成上传样本，不是经过摄影师审核或实拍评测的风格知识。
