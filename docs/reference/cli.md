# CLI 参考

公共形式：

```bash
uv run agilex-controller [--project-root PATH] [--config FILE] COMMAND [OPTIONS]
```

公共选项也可以放在子命令后。`--project-root` 默认使用 editable 安装的源码根目录；使用 wheel 安装时应显式指定包含四个子项目的 checkout。`--config` 相对于当前工作目录解析，默认读取项目的 `config/default.toml`。所有命令支持 `--help`，帮助不会访问硬件。

## 命令

| 命令 | 行为 |
| --- | --- |
| `config` | 输出有效配置 JSON |
| `read [--gello-port PATH] [--json]` | 使用项目校准读取一次真实 GELLO，随后关闭串口 |
| `status [--can-interface IF] [--sdk-project PATH]` | 调用 SDK 自己的解释器读取机械臂状态 |
| `follow` | 完整的检查、启动、对齐、跟随与退出流程 |
| `record` / `follow-record` | 完整跟随流程，加 episode 录制和可选自动转换 |
| `movejs` | 通过现有服务分步定位并验收反馈 |
| `convert SESSION OUTPUT` | 在 converter 环境中离线转换 |

`read` 和托管跟随使用相同应用锁，避免主手串口被并发打开；直接定位也使用该锁。

## follow / record

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--gello-port PATH` | 使用配置的稳定 by-id 串口 |
| `--host HOST` / `--hostname HOST` | `127.0.0.1` |
| `--port N` / `--robot-port N` | `6001` |
| `--hz HZ` | `50`，控制与 raw 采样频率 |
| `--can-interface IF` | `can0` |
| `--can-bitrate N` | `1000000` |
| `--sdk-project PATH` | SDK 项目目录 |
| `--joint-signs S1 ... S6` | 覆盖 `gello.follower_signs`，各值必须 ±1 |
| `--max-start-error-rad RAD` | `0.35`，启动误差限制 |
| `--transition-step-rad RAD` | `0.02`，最大允许 0.05 |
| `--max-command-step-rad RAD` | `1.0`，最大允许 1.0 |
| `--request-timeout-s SEC` | `2.0`，每次 RPC 超时 |
| `--startup-timeout-s SEC` | `15.0`，服务就绪总等待时间 |
| `--camera` / `--no-camera` | 启用/关闭相机，默认配置关闭；相机脚本启用 |
| `--camera-depth` / `--no-camera-depth` | 启用/关闭原始深度，默认启用 |
| `--camera-preview` / `--no-camera-preview` | RGB 预览，默认配置关闭；相机脚本启用 |
| `--camera-serial SERIAL` | 指定设备序列号 |
| `--camera-width N` / `--camera-height N` / `--camera-fps N` | 覆盖 RGB profile；深度 profile 在 TOML 中设置 |
| `--camera-png-compress-level N` | 无损 PNG 压缩等级 0..9；默认取 TOML 的 0，最快但文件较大；影响 RGB 和深度 |
| `--yes` | 跳过一次运动确认 |
| `--skip-can-setup` | 使用已有 CAN 配置；仍检查 SDK 反馈 |
| `--existing-server` | 连接手动管理的服务，跳过本地 CAN/SDK 预检及启停 |

托管模式的 host 必须是本机可绑定的地址。已存在服务时必须显式使用 `--existing-server`；该模式仍会在进入跟随前回零/对齐，并在退出时尝试回零。

record 的额外参数：

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--raw-data-root PATH` | `data/raw` |
| `--lerobot-data-root PATH` | `data/lerobot` |
| `--converter-project PATH` | `lerobot-converter` |
| `--task TEXT` | session 的非空任务描述 |
| `--record-queue-size N` | `500`，有界异步队列 |
| `--dataset-fps FPS` | `30`，仅影响离线输出 |
| `--start-recording` | 对齐后立即创建第一集 |
| `--no-start-recording` | 覆盖配置，等待 R |
| `--skip-conversion` | 退出后不自动转换 |

R 开始、S 保存、D 丢弃、P 状态、H 帮助。非终端输入不提供这些单键控制。Ctrl+C 与 SIGTERM 都走清理路径；尚未保存的活动集保留 partial。

## movejs

```bash
uv run agilex-controller movejs --joints 0 0 0 0 0 0 --gripper 0.5
```

要求 SDK 服务已在运行。支持 host/port 的两组别名、`--request-timeout-s`、`--joints`（6 个 rad，默认全零）、`--gripper`（0..1，默认保留当前反馈）、`--step-rad`（0.02）、`--period`（0.02 s）、`--tolerance-deg`（1.0）。达到目标后根据反馈验收，失败时报错。

此命令直接定位，不创建 SDK 服务；它不包含托管跟随的确认和退出回零流程。

## convert

```bash
uv run agilex-controller convert data/raw/SESSION data/lerobot/DATASET \
  --fps 30 --repo-id local/demo
```

支持 `--converter-project`、`--fps`、`--repo-id`、`--without-velocity`、`--without-ee-pose`、`--max-camera-skew-ms`（正有限数，覆盖 manifest 每路最大匹配误差）。session/output 相对于调用时工作目录解析；converter 项目路径相对于项目根目录解析。

controller 不导入 converter，使用其 `.venv/bin/python` 调用原 CLI，保留其返回码。转换不创建或控制硬件。目标目录必须尚不存在。

## Shell 入口与退出码

| 脚本 | 默认行为 |
| --- | --- |
| `scripts/start_gello_follow.sh` | `follow`，无相机 |
| `scripts/start_data_record.sh` | `record`，无相机数采 |
| `scripts/start_camera_follow.sh` | `follow --camera --camera-preview`，跟随并显示 RGB 图像 |
| `scripts/start_camera_record.sh` | `record --camera --camera-preview`，跟随/预览并提供 RGB-D 数采 |

原脚本保持原有调用形式，使用默认配置时不打开相机。相机脚本在用户参数前加入启用参数；用户仍可用 `--no-camera-preview` 或自定义 TOML 调整行为。所有运行脚本使用同一应用锁和根目录环境，可以从任意工作目录调用。record 均通过 R/S/D 管理 episode，未保存的活动集在退出时保持 partial。

正常完成、人工取消、托管跟随经 Ctrl+C/SIGTERM 清理完成返回 0；应用或清理错误返回 1；参数语法错误返回 2。非托管操作被中断返回 130。转换子进程的失败码原样返回；发生控制/清理异常时自动转换不会执行，之后可手工转换已保存 raw。
