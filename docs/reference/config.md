# 配置参考

默认配置位于 [config/default.toml](../../config/default.toml)。显式 `--config FILE` 选择另一份 TOML；未写字段由内置默认值补全。未知表、未知字段、非法维度和非有限数值会在硬件工作之前拒绝。命令行显式值优先。

## robot 与 safety

```toml
[robot]
host = "127.0.0.1"
port = 6001
hz = 50.0
can_interface = "can0"
can_bitrate = 1000000

[safety]
max_start_error_rad = 0.35
transition_step_rad = 0.02
max_command_step_rad = 1.0
request_timeout_s = 2.0
startup_timeout_s = 15.0
```

port 为 1..65535 的整数；频率、超时和步长必须正且有限。transition 步长上限 0.05 rad，运行步长上限 1.0 rad。修改频率会同时改变控制周期和所启动 SDK 服务的命令频率上限；CAN 的实际反馈频率仍由硬件决定。

## gello

```toml
[gello]
port = "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTBM4Z46-if00-port0"
joint_ids = [1, 2, 3, 4, 5, 6]
joint_offsets = [3.141592653589793, 3.141592653589793, 3.141592653589793, 3.141592653589793, 3.141592653589793, 3.141592653589793]
joint_signs = [1, -1, -1, -1, 1, 1]
gripper_config = [7, 159, 201]
follower_signs = [1, 1, -1, -1, 1, 1]
```

上述数值迁自原采集链路，只适用于同一台已标定主手。offset 单位 rad；gripper 的三个整数分别是电机 ID 和两个端点的角度（deg），七个 ID 必须唯一。

两层方向不能混淆：

1. GELLO 设备层按 `(encoder - joint_offsets) * joint_signs` 得到主手坐标。
2. controller 按 `follower_signs` 将六个主手坐标映射到 PiPER-X 目标。

夹爪归一化使用 `(angle - endpoint_0) / (endpoint_1 - endpoint_0)` 并截断到 [0,1]。controller 沿用原流程，直接透传归一化值；SDK 将该值映射到 AGX 开口宽度（0=闭，1=开）。请依据实际安装确定主手两个端点的方向，迁移本身不交换它们。

启动时使用方向映射前的主手角度选择 Dynamixel 多圈分支。库的 `PORT_CONFIG_MAP` 不再是当前安装的配置来源；controller 显式传入 `DynamixelRobotConfig`。GELLO 自己的 `read` CLI 仍使用库自己的端口表，和 controller 配置独立。

## recording

```toml
[recording]
task = "PiPER-X GELLO teleoperation"
queue_size = 500
dataset_fps = 30
convert = true
start_recording = false
```

task 必须非空；queue_size 与 dataset_fps 必须为正整数。50 Hz raw 与 30 FPS dataset 是两个阶段的频率；对齐和重采样由 converter 实现。`start_recording` 只自动开始，不自动保存。

## paths

```toml
[paths]
sdk_project = "agilex-sdk-python"
converter_project = "lerobot-converter"
raw_data_root = "data/raw"
lerobot_data_root = "data/lerobot"
```

相对路径统一基于 controller 项目根目录，绝对路径也可使用。它们不相对于配置文件目录或 Shell 工作目录。

开发时需要调用独立 SDK 工作副本，可使用 `sdk_project = "../agilex-sdk-python"`，无需修改 SDK。converter 子进程同理。controller 的 GELLO Python 依赖路径由 `pyproject.toml` 中 `tool.uv.sources` 管理，不由本文件切换。

## 自定义实验

```bash
cp config/default.toml config/experiment.toml
uv run agilex-controller --config config/experiment.toml config
uv run agilex-controller record --config config/experiment.toml \
  --hz 50 --task "pick object" --skip-conversion
```

修改设备配置后先执行只读 `read` 并核对各轴与夹爪，再进行运动验证。
