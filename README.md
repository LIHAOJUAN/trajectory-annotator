# SWE-bench Trajectory Reviewer

一个可独立部署的 SWE-bench Agent 轨迹审阅工具。当前正式版本采用**单标签复核**：系统先概括每轮 Worker/Evaluator 的行为并建议一个整条轨迹标签，人工只需确认或改选。

## 当前功能

- A、B 两组各50条，互不重复，合计100条；
- 每轮分别概括 Worker 和 Evaluator；
- 直接显示思考内容；
- 逐项概括每次工具调用的用途、返回、成功/失败、代码变化和效果；
- 展示官方 F2P/P2P、自动初筛和 Checkpoint Replay；
- 机器建议一个合法的整条轨迹标签，并说明理由、来源和置信度；
- 人工只需核对一个 `trajectory_verdict`，可选写备注；
- 多标注员结果按 `annotation_id + annotator` 并存；
- 文件锁和原子写入，支持共享部署。

## 数据说明

仓库自带100条精简样本、自动分析和 Replay 结果。完整 `trajectory.jsonl`、patch 和测试日志体积较大，不包含在仓库中；需要查看逐轮原始轨迹时，通过 `SWE_TRAJECTORY_ROOT` 挂载。

建议先使用 private GitHub 仓库，确认数据允许公开后再设为 public。

## 快速启动

```bash
git clone https://github.com/LIHAOJUAN/trajectory-annotator.git
cd trajectory-annotator
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
PORT=18080 python3 run.py
```

浏览器打开：

```text
http://127.0.0.1:18080
```

## 启动A组或B组

A组50条：

```bash
ANNOTATOR_SAMPLE_FILE=assignments/A.jsonl PORT=18080 python3 run.py
```

B组50条：

```bash
ANNOTATOR_SAMPLE_FILE=assignments/B.jsonl PORT=18080 python3 run.py
```

不指定 `ANNOTATOR_SAMPLE_FILE` 时显示完整100条。

## 挂载原始轨迹

```bash
export SWE_TRAJECTORY_ROOT=/path/to/trajectories/swebench_verified
ANNOTATOR_SAMPLE_FILE=assignments/A.jsonl PORT=18080 python3 run.py
```

没有原始轨迹时，官方结果、自动分析和 Replay 仍可查看，但逐轮思考与工具摘要不可用。

## 标注结果

默认保存到：

```text
workspace/trajectory_label_reviews.jsonl
```

每条结果主要包含：

```text
annotation_id
annotator
trajectory_verdict
accepted_suggestion
machine_suggestion
notes
updated_at
```

## Docker

```bash
docker compose up -d --build
```

## 配置

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8765` | 服务端口 |
| `THREADS` | `8` | Waitress线程数 |
| `ANNOTATOR_SAMPLE_FILE` | `annotation_sample_100.jsonl` | 样本文件，可设为 `assignments/A.jsonl` 或 `assignments/B.jsonl` |
| `ANNOTATOR_REVIEW_STORE_PATH` | `workspace/trajectory_label_reviews.jsonl` | 单标签复核输出 |
| `SWE_TRAJECTORY_ROOT` | 空 | 原始轨迹根目录 |
| `ANNOTATOR_DATA_DIR` | `./data` | 数据目录 |

## 测试

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```

## 项目结构

```text
├── app.py
├── run.py
├── static/
├── templates/
├── data/
│   ├── assignments/A.jsonl
│   ├── assignments/B.jsonl
│   └── outputs/
├── workspace/
├── tests/
└── docker-compose.yml
```
