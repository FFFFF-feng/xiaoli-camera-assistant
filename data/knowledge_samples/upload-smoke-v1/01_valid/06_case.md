---
schema_version: 1
knowledge_id: upload-smoke-v1-case-001
library_id: case
title: "[上传测试] 窗边杯子合成案例"
kind: guideline
payload:
  test_only: true
  synthetic: true
  has_real_photo: false
tags:
  - 上传测试
  - 合成案例
conditions:
  device_type: phone
source:
  name: 小栗上传功能自制测试样本
  location: 样本集 upload-smoke-v1 / 参考案例库
  license: 仅用于项目导入功能测试，未授权作为正式推荐依据
  retrieval_allowed: false
author: 上传功能测试员
version: 1
dataset_split: evaluation
---

合成情境：窗边摆放一只杯子，用户希望杯子清楚、背景简单。

这不是实拍案例，没有参考照片或EXIF。使用`guideline`类型，避免把合成描述伪装成已观测的拍摄证据。
本记录仅用于测试参考案例库上传与中文Markdown正文保存。
