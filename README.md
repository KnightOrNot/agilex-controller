# agilex-controller

PiPER-X 与 GELLO 的应用编排和数采入口。controller 创建客户端，管理设备检查、SDK 服务、JS 定位、跟随循环和原始 episode；`lerobot-converter` 在独立 Python 3.12 环境中完成时间对齐和 LeRobot Dataset v3 转换。保留原有无相机流程，并提供带相机预览的跟随与 RGB-D 数采入口。

新增的 `agilex-data-collection` 提供独立的浏览器按键数采流程：使用
`agilex-adapters` 接入 LeRobot，在独立 Python 3.12 环境中运行，并复用
LeLab 的数据集浏览功能。原 `agilex-controller` 命令和 Shell 流程保持不变。
安装与使用见[新数采流程](docs/data-collection.md)。

## 职责与目录

| 组件 | 职责 |
| --- | --- |
| controller，Python 3.11 | 应用配置、客户端组合、进程生命周期、跟随和 raw 录制 |
| `agilex-gello-software/`，Python 3.11 | GELLO/Dynamixel 读取、设备校准、上游通用实验工具 |
| `agilex-sdk-python/`，Python 3.11 | CAN 硬件、运动控制、反馈、ZMQ 服务；本次迁移未修改 SDK |
| `camera-realsense/`，Python 3.11 | RGB-D 采集、设备时间戳、深度单位与标定 |
| `lerobot-converter/`，Python 3.12 | raw 校验、时间戳重采样、LeRobot 数据集与质量报告 |

```text
src/agilex_controller/     Python 应用和 CLI
config/default.toml       项目默认值与本机主手校准
scripts/setup.sh          一键配置
scripts/start_gello_follow.sh  无相机跟随 → controller follow
scripts/start_data_record.sh   无相机数采 → controller record
scripts/start_camera_follow.sh 跟随 + 相机预览
scripts/start_camera_record.sh 跟随 + 相机预览 + RGB-D 数采
tests/                    无硬件回归测试与转换集成测试
docs/                     安装、架构、命令、配置和排障
data/raw/                 原始 session，Git 忽略
data/lerobot/             派生数据集，Git 忽略
```

五个子项目以 Git submodule 固定版本，包括新加入的 `agilex-adapters/`。
controller 将 GELLO 基础包和相机库作为本地 editable 依赖安装；SDK 服务、
转换器和新数采应用使用各自的解释器，通过 IPC、ZMQ 和文件协作。

GELLO 的原生 `gello/` 与本地 `src/` 适配分开维护。controller 继续使用 `agilex_gello_software` 的校准/生命周期 API；DynamixelSDK 改由 GELLO 内固定的嵌套 submodule 提供，安装脚本会初始化它。详情见 [GELLO 开发文档](agilex-gello-software/README.md)。

## 安装

在 Linux 上 clone 项目，然后运行：

```bash
./scripts/setup.sh
```

脚本初始化 submodule、准备 pyenv 和 uv、安装系统依赖并同步五个环境。开发中保留已有子模块修改时：

```bash
./scripts/setup.sh --skip-system --skip-submodules
./scripts/setup.sh --check-only
```

加入 `dialout` 后需要注销并重新登录。完整依赖与手工安装流程见[安装指南](docs/installation.md)。

## 配置与只读检查

五个一级子模块现在都提供 `config/default.toml`；配置范围、覆盖规则和
快速相机预设见[子模块配置说明](docs/reference/submodule-config.md)。
新数采应用默认优先 RGB-D 640×360@90 FPS，按逐路实测回退到 60/30；
原 controller 的显式相机参数保持不变。

先检查 [config/default.toml](config/default.toml)。设备 ID、弧度 offset、设备方向和夹爪端点必须与当前 GELLO 标定一致；`follower_signs` 是额外的主手到从臂方向映射。

```bash
uv run agilex-controller --help
uv run agilex-controller config
uv run agilex-controller read
uv run agilex-controller status
uv run --project camera-realsense camera-realsense info --profiles
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

原来的两个脚本保持无相机流程。带 RGB 预览的跟随与数采使用新增入口：

```bash
./scripts/start_camera_follow.sh
./scripts/start_camera_record.sh
```

follow 只跟随和预览；record 在此基础上通过 R/S/D 录制、保存或丢弃关节、RGB 与深度。

等价的无相机 Python 应用入口：

```bash
uv run agilex-controller follow
uv run agilex-controller record
```

四个运行脚本均为 controller CLI 包装；相机脚本默认传入 `--camera --camera-preview`，其余用户参数随后转交，可以显式覆盖。完整流程由 controller 实现：

1. 持有互斥锁，检查串口、配置 CAN、检查真实反馈并读取主手。
2. 确认目标；启用相机时预热 RGB-D 并验证时间域、打开预览，再启动 SDK 服务并等待 RPC 就绪。
3. 通过同一 JS 服务分步回零、对齐，然后开始跟随。
4. Ctrl+C 或 SIGTERM 停止新命令，释放客户端与主手，通过新客户端尝试 JS 回零，再关闭所启动的 SDK 服务。
5. 关闭相机并刷新图像与未完成 raw episode；数采命令随后离线转换已保存的数据。

数采按键：

| 按键 | 操作 |
| --- | --- |
| R | 开始关节 episode；相机数采同时开始 RGB 与深度录制 |
| S | 保存当前 episode |
| D | 丢弃当前 episode |
| P / H | 状态 / 帮助 |
| Ctrl+C | 退出；当前未保存 episode 保留为 `.partial` |

必须先按 S 才会得到可转换的正式 episode。`--start-recording` 自动开始第一集，仍需按 S 保存。`--skip-conversion` 仅保留 raw；`--yes` 跳过运动确认。标准输入不是终端时，单键操作不可用。

退出保持现有 SDK 的 JS 控制方式，不切换普通 J 模式、不额外 reset，也不自动失能。失能可能造成机械臂下坠；按硬件手册操作。回零失败会报告错误并继续关闭本程序启动的服务。

## 相机配置与时间对齐

默认 `[camera].enabled=false`，原有跟随和数采入口不打开相机。新增相机脚本显式启用采集与 RGB 弹窗；启用后请求单台相机的 RGB 和深度各 640×480 @30 FPS。先用 `info --profiles` 核对设备支持；多台设备连接时在配置中填写 `serial`。无桌面运行相机脚本时可加 `--no-camera-preview`；只采 RGB 加 `--no-camera-depth`。

相机独立线程采集，R/S/D 同时管理各路数据。S 等全部写盘后才发布正式关节 episode；未保存数据保留 `.partial`。相机停帧、断开或写盘队列满会报错并进入既有安全退出流程。

相机 global/system 时间映射到主机单调时钟；converter 将 RGB、深度分别匹配到关节建立的输出时间轴。默认每路最大目标匹配误差 50 ms，超限拒绝转换，实际误差写入质量报告。这是软件对齐，不保证硬件曝光同步；原生深度也未投影到 RGB 像素。算法、单位和误差边界见[相机与同步](docs/cameras.md)。

## 数据与离线转换

```text
data/raw/session_YYYYMMDD_HHMMSS/
├── manifest.json
├── episodes/
│   ├── episode_000000.jsonl
│   └── episode_000001.jsonl.partial
└── cameras/
    ├── front/episode_000000/{frames.jsonl,frames/*.png}
    └── front_depth/episode_000000/{frames.jsonl,frames/*.png}
```

启用相机时使用 `piper_x_gello_raw` v2，RGB 为无损 PNG，深度为无损 Z16 PNG；关闭相机仍写兼容的 v1。每行保存最终下发的 action、随后返回的 observation、单调时钟和墙钟时间；录制不会直接导入 LeRobot 或 PyTorch。原始数据是权威数据源，转换器只读它们。

```bash
uv run agilex-controller convert data/raw/SESSION data/lerobot/DATASET
```

将 `SESSION` 和 `DATASET` 替换为实际目录。转换器忽略 `.partial`，拒绝覆盖已存在的输出；成功后生成 `meta/`、`data/`、RGB `videos/` 和 `quality_report.json`，深度以米制浮点图像无损嵌入 Parquet。同步算法和格式说明见[转换器文档](lerobot-converter/README.md)。

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

测试使用本地 ZMQ 假服务、模拟主手和 RGB-D 帧，不访问实体硬件。转换集成测试使用真实 converter 环境生成并读回数据集；它不能替代真实设备联调。
