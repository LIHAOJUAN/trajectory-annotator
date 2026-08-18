# 单标签轨迹复核指南

## 人工只需要做什么

每条轨迹只核对一个字段：`trajectory_verdict`（整条轨迹结论）。

1. 先看“轨迹”页的逐轮摘要；
2. 查看机器建议、理由、来源和置信度；
3. 同意则点击“确认机器建议”；
4. 不同意则从下拉框改选；
5. 可选填写一句备注并保存。

## 标签含义

| 标签 | 含义 |
|---|---|
| Healthy Success | 官方成功，过程直接、诊断清楚、验证充分。 |
| Costly Success | 官方成功，但存在较多无效调用、反复修改或额外成本。 |
| Recovered Success | 前期出错，后来通过反馈或自我纠错恢复成功。 |
| False Accept | Agent/Evaluator声称成功，但官方结果失败。 |
| False Reject | Agent/Evaluator声称失败或impossible，但官方结果成功。 |
| Looping Failure | 最终失败，主要表现为重复命令、错误或无进展尝试。 |
| Destructive Drift Candidate | 疑似后期修改破坏了较好状态，但证据尚不足以确认。 |
| Verification Failure | 主要因验证不足、错误或误读而失败。 |
| Protocol Failure | 主要因结构化输出、Schema、API或轮次协议问题失败。 |
| Environment Failure | 主要因依赖、解释器、构建、网络、容器或权限问题失败。 |
| Non-addressable Failure | 主要问题不属于当前Agent/Harness可合理解决范围。 |
| Provenance Invalid | 轨迹归属、实例身份或数据来源不可信。 |
| Other | 不属于现有标签，需在备注中解释。 |
| Uncertain | 证据不足，无法可靠选择其他标签。 |

## 轨迹摘要怎么看

每轮分别展示Worker和Evaluator：

- 思考内容；
- 每次工具调用做什么；
- 工具返回的概括；
- 成功还是失败；
- 是否改动代码、涉及哪些文件；
- Checkpoint Replay是否显示实际改善或回归。

机器建议仅是辅助，人工最终选择才是复核结果。
