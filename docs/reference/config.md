# 配置参考

默认配置位于 [config/default.toml](../../config/default.toml)，命令行 controller 与
浏览器数采 `agilex-data-collection` 共用这一份文件。显式 `--config FILE` 选择另一份
TOML；未写字段由内置默认值补全。未知表、未知字段、非法维度和非有限数值会在
硬件工作之前拒绝。命令行显式值优先。`[collection]` 只由浏览器数采解析，controller
忽略该表。

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

## camera

```toml
[camera]
enabled = false
name = "front"
serial = ""
width = 640
height = 480
fps = 30
depth_enabled = true
depth_width = 640
depth_height = 480
depth_fps = 30
warmup_frames = 15
startup_timeout_s = 10.0
frame_timeout_s = 1.0
queue_size = 32
png_compress_level = 0
max_skew_ms = 50.0
preview = false
```

`serial` 为空仅允许发现一台相机；尺寸/FPS 必须是设备支持的组合。RGB 与深度可配置不同 profile，按各自时间戳对齐。`name` 必须以字母开头且仅包含字母、数字和下划线；深度流自动命名为 `<name>_depth`。

`warmup_frames` 是每路跳过的初始帧数；startup 超时要求全部启用流产生主机时间域的新帧，frame 超时检查每路最后接收时刻。`queue_size` 为每路写盘队列容量，满时失败而非静默丢帧。尺寸/FPS/容量为正整数，预热帧数可为零，三个超时/误差值为正有限数。

`png_compress_level` 是 0..9 的整数，默认 0：关闭 PNG 的压缩计算，仍然无损保存完整 RGB8/Z16。1..9 可以减小文件，但增加 CPU 负担；CLI `--camera-png-compress-level` 优先于 TOML。编码使用固定 None 行过滤以避免逐行自适应过滤开销。默认 640×480 双路 30 FPS 的图像数据约 46 MB/s（约 2.8 GB/分钟），请保留足够空间。增大 queue_size 仅能吸收瞬时写盘抖动，不能弥补长期吞吐不足；默认每路 32 帧约一秒缓冲。

`max_skew_ms` 写入 manifest，约束转换时每路帧与目标时间的误差；不是曝光精度保证。`preview` 仅预览 RGB，独立进程可跳过显示帧但不跳过录制帧。`enabled=false` 是默认值，原有脚本保持无相机 raw v1；新的相机跟随/数采脚本通过 CLI 启用 camera 与 preview，覆盖 TOML。`depth_enabled=false` 仅关闭深度。

## collection

```toml
[collection]
hardware_config = ""
data_root = "data/lerobot/app"
control_hz = 50
dataset_fps = 30
max_skew_ms = 50.0
queue_size = 90
watchdog_s = 1.0
position_tolerance_deg = 1.1
preview_depth_max_m = 3.0
preview_cloud_stride = 4
camera_enabled = true
camera_mode = "auto"
depth_enabled = true
```

浏览器数采专用。`hardware_config` 为空表示 `[robot]`、`[gello]`、`[camera]` 和
`[paths]` 就在当前文件（默认行为）；也可以填写另一份硬件 TOML 的相对路径，
该文件仍由 controller 的加载器校验。`data_root` 是 LeRobot 数据集根目录（默认
`data/lerobot/app`）。`control_hz`、`dataset_fps`、`queue_size` 和
`preview_cloud_stride` 必须是正整数，且 `dataset_fps <= control_hz`。

`max_skew_ms` 是 RGB、深度与机器人反馈之间允许的主机单调时钟偏差；
`watchdog_s` 是控制心跳超时。`position_tolerance_deg` 是启动回零、GELLO 对齐和
退出回零的每轴到位容差，当前用户授权值为 1.1°（J3 零位即机械上限，输出侧约
0.5° 柔度）。不得通过扣除 offset、切换控制模式或自动重标定来规避超差。

`camera_enabled`、`depth_enabled` 控制是否打开相机与深度；`camera_mode` 取
`auto`、`fast`、`slow` 或 `manual`，`auto` 首选 640×360@90 并按逐路实测回退，
`manual` 使用 `[camera]` 的 profile。`preview_depth_max_m` 和
`preview_cloud_stride` 只影响深度着色与点云抽稀，不改变数据集或原始 `.npy`。

独立的最小配置文件仍可使用扁平键（不写 `[collection]` 表）；多了一份
`[collection]` 的共享文件则只读取该表。未知键会报错。
