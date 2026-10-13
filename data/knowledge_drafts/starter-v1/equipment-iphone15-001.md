---
schema_version: 1
knowledge_id: "equipment-iphone15-001"
library_id: "equipment"
title: "iPhone 15原生后置相机事实卡"
kind: "manufacturer_fact"
version: 1
dataset_split: "reference"
author: "小栗资料初整理（需队友复核）"
tags: ["iPhone 15","手机型号","主摄","超广角"]
conditions: {"device_type":"phone","phone_profile_id":"apple_iphone_15"}
payload: {"camera_model":"iPhone 15","phone_profile_id":"apple_iphone_15","device_type":"phone","rear_modules":[{"id":"main","aperture":1.6,"equivalent_focal_length_mm":26},{"id":"ultrawide","aperture":2.4,"equivalent_focal_length_mm":13}],"iso_range":null,"shutter_range":null,"verification":{"checked_at":"2026-10-10","status":"needs_human_review"}}
source: {"name":"Apple / iPhone 15规格","url":"https://support.apple.com/zh-cn/111831","location":"摄像头","license":"仅结构化事实与短摘要；原文再分发及检索许可待核验","retrieval_allowed":false}
---

iPhone 15主摄标称f/1.6、26mm等效，超广角f/2.4、13mm等效；2×取景由主摄传感器实现，不记录成独立长焦。支持人像和夜间功能，额外兼容性以具体型号及系统为准。
