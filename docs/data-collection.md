# LeRobot / LeLab 浏览器数采

此链路处于 `dev` 开发分支。入口为 `agilex-data-collection`，实现放在
`src/agilex_data_collection/`，设备适配在独立子模块 `agilex-adapters/`。
原有 controller 源码、配置和五个 Shell 脚本的行为保持不变。

## 安装与模拟运行

先完成原环境安装，再配置独立的 Python 3.12 应用环境：

```bash
./scripts/setup.sh --skip-system --skip-submodules
uv run agilex-data-collection setup
uv run agilex-data-collection serve --simulate
```

打开 <http://127.0.0.1:8000>，依次点击“启动跟随”“开始采样”“保存本段”。
可以再次采样、丢弃本段，最后点击“停止跟随”。模拟模式不会访问串口、CAN 或相机。

安装会构建 LeLab 前端，需要网络；LeLab 构建依赖提供 Node。
LeLab 固定到 Git 提交，LeRobot 使用其官方指定的 v0.6.0，Linux PyTorch
使用 CPU 源。原 controller 的 Python 3.11 环境不会安装这些依赖。
默认选择 Python 3.12.14，以避免系统解释器缺少 `Python.h` 导致 evdev
构建失败；已有完整解释器时可用 `setup --python /path/to/python3.12`。

## 真机运行

先按原安装指南配置 CAN，确认现有 `read`、`status` 检查及设备标定正确：

```bash
uv run agilex-controller read
uv run agilex-controller status
uv run agilex-data-collection serve
```

网页勾选运动确认后才能启动。启动会检查设备、预热相机，启动 SDK，JS 回零并对齐
GELLO；停止会再次尝试 JS 回零。网页关闭不会停止会话，必须使用“停止跟随”或
服务端 Ctrl+C。未保存的本段不会进入数据集，原始输入仍保留。
首次真机验证必须由操作人员在场完成；模拟测试不证明运动与时序精度。

## 配置与数据

`config/data_collection.toml` 控制新应用。`hardware_config` 只读引用原安装配置，
复用串口、关节标定、CAN、相机序列号和分辨率；新应用独立启用 RGB-D。
修改采样频率时保持 `dataset_fps <= control_hz`。

新应用 `camera_mode="auto"` 默认使用相机库中的 640×360@90 高速预设，
逐路测速不足时按 90/60/30 回退；`slow` 直接尝试低速，`manual` 精确使用
`hardware_config` 的相机分辨率和 FPS。高速候选和探测阈值在
`camera-realsense/config/default.toml` 的 `[performance]`。
这不会提高默认 30 FPS 的数据集时间轴或 50 Hz 控制频率。实际 profile、
内外参和吞吐诊断取自启动后的 metadata；旧 controller 的显式 profile 保持原值。

- `data/lerobot/app/<session>/`：直接由官方 LeRobotDataset 写入的 v3 数据集。
- `data/raw/app/<session>/`：不可变输入，含设备标定/时钟元数据、各 take 的时间戳
  JSONL、原始 RGB uint8 / 深度 Z16 `.npy`，以及保存或丢弃结果。
- `data/logs/<session>.log`：硬件进程初始化、故障与清理日志。

RGB 输出为视频；深度输出为以米计的 float32 图像特征，原始 Z16 和深度单位
另行保留。新 raw 格式不是旧 converter 的输入格式，请勿混用转换命令。

控制默认 50 Hz，采样默认 30 FPS，写盘通过有界队列与控制分离。采样取最新帧，
以主机 monotonic 时间检查 RGB、深度与机器人反馈的偏差，超过 `max_skew_ms`
即终止会话。原始时间、帧号、时钟偏移/不确定度、命令发送区间和反馈请求区间
写入审计记录。LeRobot 时间轴为标称固定 FPS，实际采样抖动请检查原始记录；
软件时间映射与偏差检查不等于硬件同步。

## LeLab 集成边界

首页为本项目采集面板。点击“打开 LeLab 数据集浏览器”进入官方
`/edit-dataset` 页面，可浏览已保存的 episode、RGB 视频和关节变化。
目前只开放本地数据集及官方只读媒体接口；官方 SO101 运动、标定、追加采集、上传、删除、
训练和安装接口未开放。深度请通过 LeRobot 或原始 `.npy` 检查。
PiPER-X 不应套用 SO101 的录制或标定配置。

Python 3.12 适配器通过 owner-private Unix IPC 连接 3.11 硬件进程；
此进程复用现有低层初始化、GELLO 校准、SDK 客户端和清理函数，不调用旧
`run_workflow`。两条真机链路共享原有互斥锁。控制停止发送命令后硬件看门狗
触发清理；正常退出先清理硬件，再完成数据集刷新。

## 开发检查

```bash
uv run pytest -q
uv run ruff check src tests
uv run --project agilex-adapters --extra app pytest agilex-adapters/tests -q
uv build
```

适配包测试包括真实 LeRobot 工厂、Unix IPC、模拟 RGB-D 保存/丢弃与回读。
测试不会驱动真机。当前改动未经操作人员真机验证前，请勿用于正式采集。
