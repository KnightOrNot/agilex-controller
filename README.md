# agilex-controller

PiPER-X 与 GELLO 的应用编排和数采入口。controller 创建客户端，管理设备检查、SDK 服务、JS 定位、跟随循环和原始 episode；`lerobot-converter` 在独立 Python 3.12 环境中完成时间对齐和 LeRobot Dataset v3 转换。当前采集七维关节、夹爪和末端状态。

## 职责与目录

| 组件 | 职责 |
| --- | --- |
| controller，Python 3.11 | 应用配置、客户端组合、进程生命周期、跟随和 raw 录制 |
| `agilex-gello-software/`，Python 3.11 | GELLO/Dynamixel 读取、设备校准、上游通用实验工具 |
| `agilex-sdk-python/`，Python 3.11 | CAN 硬件、运动控制、反馈、ZMQ 服务；本次迁移未修改 SDK |
| `lerobot-converter/`，Python 3.12 | raw 校验、时间戳重采样、LeRobot 数据集与质量报告 |

```text
src/agilex_controller/     Python 应用和 CLI
config/default.toml       项目默认值与本机主手校准
scripts/setup.sh          一键配置
scripts/start_gello_follow.sh  一键跟随 → controller follow
scripts/start_data_record.sh   一键数采 → controller record
tests/                    无硬件回归测试与转换集成测试
docs/                     安装、架构、命令、配置和排障
data/raw/                 原始 session，Git 忽略
data/lerobot/             派生数据集，Git 忽略
```

三个子项目以 Git submodule 固定版本。controller 只将 GELLO 基础包作为本地 editable 依赖安装；SDK 服务和转换器使用各自的解释器，通过 ZMQ 和文件协作。

## 安装

在 Linux 上 clone 项目，然后运行：

```bash
./scripts/setup.sh
```

脚本初始化 submodule、准备 pyenv 和 uv、安装系统依赖并同步四个环境。开发中保留已有子模块修改时：

```bash
./scripts/setup.sh --skip-system --skip-submodules
./scripts/setup.sh --check-only
```

加入 `dialout` 后需要注销并重新登录。完整依赖与手工安装流程见[安装指南](docs/installation.md)。

## 配置与只读检查

先检查 [config/default.toml](config/default.toml)。设备 ID、弧度 offset、设备方向和夹爪端点必须与当前 GELLO 标定一致；`follower_signs` 是额外的主手到从臂方向映射。

```bash
uv run agilex-controller --help
uv run agilex-controller config
uv run agilex-controller read
uv run agilex-controller status
```

`read` 只打开主手串口；`status` 调用 SDK 的只读检查，要求 CAN 已配置。手工配置默认 CAN：

```bash
./agilex-sdk-python/scripts/config_can.sh
```

以下启动示例直接使用默认配置。需要自定义实验配置或覆盖参数时，参见[配置参考](docs/reference/config.md)。路径字段相对于项目根目录解析。

## 跟随与采集

以下命令会控制真实机械臂。运行前固定底座、清空工作区，确认急停可用，并完成上面的只读检查。默认启动流程在运动前显示目标，要求输入 `yes`。

```bash
./scripts/start_gello_follow.sh
./scripts/start_data_record.sh
```

等价的 Python 应用入口：

```bash
uv run agilex-controller follow
uv run agilex-controller record
```

两个脚本仅传递参数，完整流程由 controller 实现：

1. 持有互斥锁，检查串口、配置 CAN、检查真实反馈并读取主手。
2. 确认目标，启动独立进程中的 SDK 服务并等待 RPC 就绪。
3. 通过同一 JS 服务分步回零、对齐，然后开始跟随。
4. Ctrl+C 或 SIGTERM 停止新命令，释放客户端与主手，通过新客户端尝试 JS 回零，再关闭所启动的 SDK 服务。
5. 刷新未完成 raw episode；数采命令随后离线转换已保存的数据。

数采按键：

| 按键 | 操作 |
| --- | --- |
| R | 开始一个 episode |
| S | 保存当前 episode |
| D | 丢弃当前 episode |
| P / H | 状态 / 帮助 |
| Ctrl+C | 退出；当前未保存 episode 保留为 `.partial` |

必须先按 S 才会得到可转换的正式 episode。`--start-recording` 自动开始第一集，仍需按 S 保存。`--skip-conversion` 仅保留 raw；`--yes` 跳过运动确认。标准输入不是终端时，单键操作不可用。

退出保持现有 SDK 的 JS 控制方式，不切换普通 J 模式、不额外 reset，也不自动失能。失能可能造成机械臂下坠；按硬件手册操作。回零失败会报告错误并继续关闭本程序启动的服务。

## 数据与离线转换

```text
data/raw/session_YYYYMMDD_HHMMSS/
├── manifest.json
└── episodes/
    ├── episode_000000.jsonl
    └── episode_000001.jsonl.partial
```

raw 格式保持 `piper_x_gello_raw` v1。每行保存最终下发的 action、随后返回的 observation、单调时钟和墙钟时间；录制不会直接导入 LeRobot 或 PyTorch。原始数据是权威数据源，转换器只读它们。

```bash
uv run agilex-controller convert data/raw/SESSION data/lerobot/DATASET
```

将 `SESSION` 和 `DATASET` 替换为实际目录。转换器忽略 `.partial`，拒绝覆盖已存在的输出；成功后生成 `meta/`、`data/` 和 `quality_report.json`。同步算法和格式说明见[转换器文档](lerobot-converter/README.md)。

## 文档与验证

- [架构与数据流](docs/index.md)
- [安装指南](docs/installation.md)
- [CLI 参考](docs/reference/cli.md)
- [配置参考](docs/reference/config.md)
- [故障排查](docs/reference/errors.md)
- [贡献指南](CONTRIBUTING.md)
- [第三方代码声明](THIRD_PARTY_NOTICES.md)

```bash
uv run --frozen pytest
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv build
```

测试使用本地 ZMQ 假服务和模拟主手，不访问 CAN 或串口。转换集成测试使用真实 converter 环境生成并读回数据集；它不能替代真实设备联调。
