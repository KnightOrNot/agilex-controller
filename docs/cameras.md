# RGB-D 采集与时间对齐

## 运行与边界

`camera-realsense` 负责可复用的设备/profile、逐流 SDK 时间戳、RGB/Z16 帧和标定；controller 组合设备、录制 raw 并管理退出；converter 负责目标时间匹配及 LeRobot 转换。机器人 SDK 与 GELLO 代码未改动。

```bash
./scripts/setup.sh --skip-system --skip-submodules
./scripts/start_camera_follow.sh
./scripts/start_camera_record.sh
```

`start_camera_follow.sh` 跟随时打开并检查 RGB-D，同时显示 RGB 预览，不保存图像。`start_camera_record.sh` 在此基础上加入关节与图像采样。数采按 R 开始、S 保存、D 丢弃；两路图像与关节共同构成一个 episode。默认单台相机，两路各 640×480 @30 FPS；controller `[camera]` 是应用配置来源，先用相机独立 CLI 的 `info --profiles` 检查设备支持。多设备连接时明确指定 serial，本次不编排多台相机。

两个新脚本默认打开独立 RGB 预览进程；Q/Esc/关窗只关闭预览，停止跟随使用终端 Ctrl+C。无桌面可加 `--no-camera-preview`。`--no-camera-depth` 只录 RGB。

原有 `start_gello_follow.sh` / `start_data_record.sh` 保持无相机默认行为；TOML 的 `camera.enabled=false`、`preview=false`。直接 CLI 启用相机与弹窗，使用 `uv run agilex-controller follow --camera --camera-preview` 或相应的 `record` 命令。两种流程仍共用时间戳和退出逻辑。

## 两个时间层次

每个相机流保留 `sdk_timestamp_ms` 和 `sdk_timestamp_domain`。SDK global/system 时间与主机墙钟相关；采样 `monotonic → time_ns → monotonic` 得到 epoch 偏移，再将 SDK 毫秒映射为机器人同一主机上的 `time.monotonic_ns`。不把未经映射的 hardware_clock 数字直接与关节比较。SDK 时间域定义见 [RealSense 官方头文件](https://realsenseai.github.io/librealsense/doxygen/rs__frame_8h_source.html)。

每路先预热并等待 global/system 时间域；校验时间严格递增，采样跨度不超过 5 ms，相邻 epoch 偏移跳变不超过 5 ms，映射时间最多比接收时间晚 50 ms 或早 1 s。超限报错；这些是合理性保护阈值，不是同步精度承诺。相机型号/固件对 global time 的估计和 USB 延迟仍会影响真实误差。

converter 以每集首个关节 `observation_time_ns` 为起点，按 `recording.dataset_fps` 建立时间轴。关节整行、RGB、深度分别选择最近时间戳，等距选较早帧。action 与 observation 保持同一原始行。每路图像的目标匹配误差默认不能超过 manifest 中的 50 ms，超限拒绝整次转换；质量报告记录实际误差、原始帧数、重复使用帧数和 SDK 帧号缺口。

关节时间是客户端收到反馈后的打点，并非传感器硬件采样时间。时间对齐不等于曝光触发同步；若实验需要严格物理同步，需要额外硬件与延迟标定。RGB 与深度间的间隔也必须结合各自目标误差判断。

## 原始数据与保存完整性

启用相机使用 raw v2，关节 JSONL 行与 v1 相同：

```text
SESSION/
├── manifest.json
├── episodes/episode_000000.jsonl
└── cameras/
    ├── front/episode_000000/frames.jsonl
    ├── front/episode_000000/frames/000000.png
    ├── front_depth/episode_000000/frames.jsonl
    └── front_depth/episode_000000/frames/000000.png
```

manifest 记录每路 profile、设备、时钟、存储类型、内参，以及深度尺度和深度到 RGB 的外参。RGB 为 uint8 RGB PNG，深度为原生视角的 uint16 Z16 PNG；零表示无效深度。真实距离为 `raw_value * depth_units_m`，不固定假设每个单位是 1 mm。

写入使用固定 None 行过滤和默认 0 级 PNG 压缩，降低实时编码开销，仍完整保留 RGB 通道与 16 位深度；每张图像仍执行 fsync，保存时再同步索引。可通过 `[camera].png_compress_level` 或 `--camera-png-compress-level 0..9` 调整，较高等级需要验证持续吞吐。默认双路 640×480@30 的图像数据约 46 MB/s，约 2.8 GB/分钟。

每路 frames.jsonl 记录连续 frame_index、图像相对路径、SDK 帧号、映射/接收时间、SDK 原时间及时间域、epoch 偏移与采样跨度。目录未保存时带 `.partial`。采集线程不等待磁盘；每路有界写队列满或写盘错误都会使当前集失败，不静默丢帧。设备/SDK 未交付的帧无法恢复，帧号缺口留在 raw 并进入报告。

S 等待所有写线程并 fsync，先改名相机目录，最后发布正式关节 JSONL。正式关节文件是完成标志；进程被杀死可能留下孤立相机目录，不会单独转换。Ctrl+C/SIGTERM 先走既有 JS 回零与 SDK 清理，再关闭相机、刷新 partial；不要将 partial 手工改名冒充完整集。

## LeRobot 输出与验收

RGB 输出 `observation.images.front`，由 LeRobot 编码为 MP4。深度输出 `observation.images.front_depth`，为带 `is_depth_map=true, depth_unit=m` 元数据的 float32 单通道 image，以无损 TIFF 图像嵌入 Parquet，保留 Z16 的有效值和无效零，不使用会量化测距的普通视频编码。转换发生米制 float32 舍入；原始 Z16 始终保留在 raw。

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset

dataset = LeRobotDataset("local/demo", root="data/lerobot/DATASET", depth_output_unit="m")
rgb = dataset[0]["observation.images.front"]       # (3, H, W), 0..1
z_m = dataset[0]["observation.images.front_depth"] # (1, H_depth, W_depth), m
```

锁定 LeRobot 版本默认读回单位为 mm；显式传 `depth_output_unit="m"`。原生深度没有投影到 RGB 像素，即使宽高相同也不能直接视作像素对应；空间配准需要依据保留的内外参另行实现。

离线回归覆盖三种数据集的真实写入/读回：纯状态、RGB 视频、RGB-D。RGB-D 测试包含深度 0/65535、独立的 1 ms 深度偏移及 raw 内容不变；不能代替实体相机、USB 带宽或机械臂运动验证。首次实机采集保存一小集，检查图像、深度单位和 `quality_report.json`，再进行长集。
