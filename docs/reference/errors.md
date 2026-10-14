# 故障排查

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

## 转换失败

先验证 converter 的 Python 3.12 环境及 `dataset` extra。目标目录必须不存在；不要把输出指向 raw 输入目录。失败输出可审阅后移走，再选择新目录重试。

FFmpeg/TorchCodec 问题属于 converter 环境：执行 `ffmpeg -version` 和 `lerobot-converter/.venv/bin/python -c "from torchcodec.decoders import VideoDecoder"`。时间序列、维度或 raw 格式错误依据 converter 的错误位置排查，保持原始数据不变。

## 退出异常

正常终止使用 Ctrl+C 或 SIGTERM。清理阶段屏蔽重复停止信号，先尝试 JS 回零，再停止所拥有的服务。回零失败会明确报告，不额外 reset、切换模式或自动失能；按现场硬件状态和急停流程处置。
