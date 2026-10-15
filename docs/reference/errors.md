# 故障排查

## RealSense frame counter reset

相机在用户确认后、SDK 启动和 JS 回零之前初始化。当前会输出“相机初始化与预热中”与“相机已就绪”，用来区分阶段；之前的回零计划提示不表示机械臂已开始动作。

首次交付前的帧号回退、时间域变化或时钟映射失败会清除 RGB/深度旧缓存并重新预热。两路均稳定后才继续；持续不稳定会触发 camera.startup_timeout_s，错误附预热计数和最近重启原因。运行阶段回退仍终止流程，避免录制错误时间轴。日志含 phase、previous/current 帧号、SDK 时间和时间域，可据此区分启动与运行故障；该错误本身不能证明 USB 接触不良或供电问题。

## 找不到库或命令

从 controller 根目录执行 `uv sync --frozen`；完整安装用 `scripts/setup.sh`。controller 的 GELLO 依赖安装在根环境，SDK 与 converter 使用自己的环境。不要通过激活另一个子项目的环境来替代安装。

如果 setup 提示子模块有改动，先审阅修改；开发中用 `--skip-submodules`。如果路径移动导致 console-script 的解释器失效，在新位置重新创建环境。

## 配置被拒绝

`unknown configuration sections/options` 表示 TOML 拼写或表名不正确。关节 offset、符号和 ID 必须各有六项，gripper 有三项；所有电机 ID 唯一。正数参数不能使用 NaN/Inf，布尔值必须写为 true/false。

`--joint-signs` 修改的是主从方向；设备方向使用配置中的 `gello.joint_signs`。

## 串口不存在、无权限或超时

检查 `/dev/serial/by-id/` 与 `gello.port`，确认供电、波特率 57600、唯一电机 ID 和 dialout 权限。加入组后注销并重新登录。

`another PiPER-X/GELLO workflow is running` 表示应用锁已被持有；先正常退出旧流程。锁文件存在本身不代表被持有，不要删除文件来绕开正在运行的流程。

Dynamixel 持续 `-3001` 时检查是否有其他 GELLO/YAM/串口工具并发访问。同一串口只运行一个采集进程。真实设备初始化失败会报错，不使用模拟主手继续控制。

## CAN / SDK 反馈不完整

接口 UP 只说明本机配置完成。检查供电、急停、CAN-H/CAN-L、终端电阻及 1 Mbit/s 参数，确认 RX 增长：

```bash
ip -details -statistics link show can0
uv run agilex-controller status
```

缺少六轴有限角度、接收 FPS 非正或 arm_status 缺失时，controller 拒绝启动运动。硬件诊断见 SDK 文档和 `docs/assets/`。

## 端口占用与 RPC 超时

托管模式拒绝占用的 host/port，避免误接其他服务。需要使用已有服务时显式加 `--existing-server`。host 在托管模式下应是本机可绑定地址。

服务启动失败会输出 SDK 子进程日志。RPC 超时后原客户端不再复用；controller 通过新客户端尝试退出回零。检查服务进程、端口、SDK 反馈和超时设置。

## 启动误差或 JS 定位失败

核对校准、两个方向映射和主手姿态，不要通过随意增大安全阈值绕过错误。JS 定位等待真实反馈收敛，超时返回错误。发生错误后先确认机械臂状态，再排查 CAN 和硬件限位。

## 保存后没有数据集

只有按 S 保存的 `episode_*.jsonl` 才会转换。活动 episode 在 Ctrl+C/SIGTERM 时保持 `.partial`；`--start-recording` 不会自动保存。非终端输入无法使用 R/S/D。

写盘错误、队列满或清理错误会使流程失败；检查磁盘、权限与负载。原始文件仍保留，已完成的集可以稍后通过 `convert` 转换。

## camera image queue is full

这是图像编码/写盘速度跟不上采集，不是物体距离问题。每路默认 32 帧，30 FPS 下约一秒缓冲；RGB 和深度分别写入。错误中的 path 表示堵塞流，capacity 是容量，written 是已完成数量，writer_fps 是包含编码和 fsync 的平均处理速率（不计等帧时间）。它是诊断值，不是相机实测 FPS。

当前默认使用快速无损 PNG 编码、png_compress_level=0；若设置过较高压缩等级，先用 `./scripts/start_camera_record.sh --camera-png-compress-level 0` 重试。检查保存盘空间、负载和写入速率，优先使用本地 SSD，可用 `--no-camera-preview` 减少系统负载。仍持续积压时再降低双方 profile 的 FPS 或分辨率（RGB 可用 CLI，深度在 TOML 设置）；修改 FPS 时重新核查转换的 max_skew_ms 是否适合目标时间轴。

增大 `[camera].queue_size` 只能缓解短暂抖动，并增加内存占用。持续写入不足不能靠队列解决。发生此错误的当前集不完整，会保留 `.partial`，不能手工改名成正式集；退出时重复出现 flush failed 是同一次失败被各清理阶段报告，已经保存完成的集不受影响。

## 转换失败

先验证 converter 的 Python 3.12 环境及 `dataset` extra。目标目录必须不存在；不要把输出指向 raw 输入目录。失败输出可审阅后移走，再选择新目录重试。

FFmpeg/TorchCodec 问题属于 converter 环境：执行 `ffmpeg -version` 和 `lerobot-converter/.venv/bin/python -c "from torchcodec.decoders import VideoDecoder"`。时间序列、维度或 raw 格式错误依据 converter 的错误位置排查，保持原始数据不变。

## 退出异常

正常终止使用 Ctrl+C 或 SIGTERM。清理阶段屏蔽重复停止信号，先尝试 JS 回零，再停止所拥有的服务。回零失败会明确报告，不额外 reset、切换模式或自动失能；按现场硬件状态和急停流程处置。

## 相机与图像匹配

- 无设备/多设备：检查 USB 与 udev 权限，多设备在 `[camera].serial` 指定一台；无相机验证旧流程可用 `--no-camera`。
- profile 不支持：先运行相机 `info --profiles`；RGB 与深度各自选择设备支持的尺寸/FPS，USB 2 连接可能无法维持请求带宽。
- startup timeout：预热后必须两路都产生 global/system 时间域的帧；仅硬件时钟的数据不接受。确认固件、SDK、连接和设备权限，不要用接收时间冒充曝光时间。
- 停帧/断连/写盘队列满：流程报错并尝试 JS 回零；当前集不发布。检查磁盘、USB、CPU 和实际帧率；只增大队列不能修复持续吞吐不足。
- clock stepped / host clock window：采集期间系统时钟突变或 SDK 时间异常，当前对齐失效；重新开始 session 并检查主机时间服务。
- camera matching error：converter 在目标时间附近找不到允许范围内的帧。检查对应帧索引和采集完整性；提高 `--max-camera-skew-ms` 会放宽质量要求，不能消除误差。
- LeRobot 深度读数：显式 `depth_output_unit="m"` 得到米制 Tensor；0 代表无效测距。当前锁定版本默认读回单位是 mm。
