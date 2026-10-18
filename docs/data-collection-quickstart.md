# LeRobot / LeLab 数采快速启动

适用于当前 `dev` 分支的 GELLO → PiPER-X + RealSense RGB-D 浏览器数采。
以下命令均在 `agilex-controller` 仓库根目录执行。

## 日常启动

已完成环境安装和设备配置后，只需运行：

```bash
uv run agilex-data-collection serve
```

保持终端运行，打开 <http://127.0.0.1:8000>。首页用于采集，页面底部的
“打开 LeLab 数据集浏览器”用于查看已保存的数据。

**真机启动会 JS 回零并对齐 GELLO，停止时也会尝试回零。** 操作人员须在场，
确认底座固定、运动空间清空、急停可用，且主手标定正确。
这条链路使用浏览器按钮操作；原来的 `scripts/start_*.sh` 属于旧流程，
运行新流程时应先停止旧流程及其他占用串口、CAN 或相机的程序。

## 首次准备（只需一次）

当前本地仓库和子模块均已准备好；保留本地子模块提交，按需同步环境：

```bash
./scripts/setup.sh --skip-system --skip-submodules
uv run agilex-data-collection setup
```

第一条复用现有系统依赖，准备底层环境；第二条安装独立的 Python 3.12
数采环境及 LeRobot、LeLab，并构建网页，需要网络。无需手工切换虚拟环境。
新机器尚未安装系统依赖时，先按[安装指南](installation.md)完成基础安装。

真机运行前检查以下配置与设备：

| 文件 | 需要确认的内容 |
| --- | --- |
| `config/default.toml` | GELLO 串口与标定、CAN 接口、相机序列号；多台相机时必须指定目标序列号 |
| `config/data_collection.toml` | 新数采应用配置；默认启用 RGB、深度及相机自动快速模式 |
| `camera-realsense/config/default.toml` | 快速相机候选和测速阈值，通常无需修改 |

CAN 尚未配置时执行第一条；随后执行只读检查：

```bash
./agilex-sdk-python/scripts/config_can.sh
uv run agilex-controller read
uv run agilex-controller status
uv run --project camera-realsense camera-realsense info --profiles
```

默认 CAN 为 `can0`；使用其他接口时按[安装指南](installation.md#串口与-can)配置。
先解决设备缺失、权限或标定问题，再启动真机跟随。

## 先模拟走通按钮流程（可选）

```bash
uv run agilex-data-collection serve --simulate
```

打开同一个网页，按下面的步骤采一段模拟数据。模拟模式不访问真实机械臂、
主手或相机，但会写入数据目录。试完停止跟随、终端 Ctrl+C，再用日常启动命令
启动真机服务；两种模式不要同时运行。模拟测试不能代替真机精度验证。

## 采集一段数据

1. 填写“任务描述”，例如“将方块放入盒子”；该描述写入本次会话的数据。
2. 真机模式勾选运动范围确认，点击“启动跟随”。等待状态变为 `following`，
   检查 RGB 预览和跟随是否正常；启动期间请勿重复点击。
3. 点击“开始采样”，等待 `recording` 后完成动作。
4. 点击“保存本段”，等待状态回到 `following`，并确认 `saved_episodes` 增加。
   不满意时使用“丢弃本段”。保存或丢弃后仍会继续跟随。
5. 重复“开始采样 → 保存本段”，在同一会话中采集多个 episode。
6. 结束前保存需要的数据，再点击“停止跟随”。等待 `completed`，确认没有错误；
   随后可查看数据，最后在终端 Ctrl+C 关闭服务。

**关闭网页不会停止跟随。停止跟随会丢弃尚未保存的当前段**，已保存的 episode
保留；已落盘的原始输入也保留。首次建议只采几秒，检查保存结果后再长时间采集。

## 查看采集结果

点击“打开 LeLab 数据集浏览器”，选择本次本地数据集和 episode，查看 RGB 视频、
关节曲线及帧数。首页状态中的 `dataset`、`raw` 字段给出本次实际保存路径。

| 默认位置 | 内容 |
| --- | --- |
| `data/lerobot/app/<session>/` | 直接写入的 LeRobot v3 数据集；无需再运行 converter |
| `data/raw/app/<session>/manifest.json` | 配置、设备标定与相机实际 profile / 吞吐诊断 |
| `data/raw/app/<session>/take_*/` | `samples.jsonl` 时间审计、RGB / 原生 Z16 `.npy`、保存或丢弃结果 |
| `data/logs/<session>.log` | 硬件初始化、故障与清理日志 |

LeLab 当前用于只读浏览；深度通过 LeRobot 或原始 `.npy` 检查。
数据集深度单位为米，原始深度保留 Z16 和单位信息。

相机默认优先 **640×360 @90 FPS**，启动时按逐路实测尝试回退到 60 / 30 FPS；
这不改变默认 **50 Hz 控制、30 FPS 数据集**。实际模式以 `manifest.json` 为准。
采样按主机单调时钟检查图像与反馈偏差，默认上限 50 ms；这是软件对齐，
实际时间抖动应查 `samples.jsonl`。当前 90 FPS 持续吞吐仍待真机验证。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示先运行 setup | 执行 `uv run agilex-data-collection setup` |
| 8000 端口被占用 | 停止旧服务，或用 `uv run agilex-data-collection serve --port 8001`，打开对应端口 |
| 启动失败或状态为 `error` | 查看网页 `error` 和本次日志，等待清理结束，排除设备权限、占用或 CAN 问题后重试 |
| 相机快速模式不稳定 | 将 `config/data_collection.toml` 的 `camera_mode` 改为 `"slow"`，停止当前会话后重启服务 |
| 时间偏差超限或写盘队列满 | 停止采集，检查相机、USB 链路、磁盘及负载；必要时降低 `dataset_fps`，保持其不超过 `control_hz` |
| LeLab 看不到本次数据 | 确认至少保存了一段、`saved_episodes` 增加，停止跟随后刷新数据集列表 |

更多配置、时序与集成边界见[数采流程说明](data-collection.md)。
