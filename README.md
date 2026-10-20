# agilex-controller

PiPER-X 与 GELLO 的遥操作和数据采集项目。仓库提供两个并列、都常用的入口，
共用同一套设备配置、硬件互斥锁和底层客户端：

| 入口 | 运行形态 | 输出 |
| --- | --- | --- |
| `agilex-controller`（Python 3.11） | 终端命令与 Shell 脚本：跟随、录制、JS 定位、离线转换 | raw JSONL + 图像，再由 converter 生成 LeRobot Dataset v3 |
| `agilex-data-collection`（3.11 入口 → 3.12 应用） | 浏览器面板：跟随、采样、保存/丢弃、实时预览、LeLab 数据集管理 | 直接写入 LeRobot Dataset v3，同时保留 raw 审计数据 |

前者适合脚本化、低开销的跟随和原始数据采集；后者适合按键操作、实时查看
RGB-D 预览并直接在网页中浏览、合并、上传或删除 LeRobot 数据集。
两条链路不要同时运行，它们共享硬件锁、串口、CAN 和相机。

## 职责与目录

| 组件 | 职责 |
| --- | --- |
| controller，Python 3.11 | 应用配置、客户端组合、进程生命周期、跟随和 raw 录制 |
| `src/agilex_data_collection/`，Python 3.12 | 浏览器数采、硬件 worker、预览、LeLab 集成 |
| `agilex-adapters/`，Python 3.12 | LeRobot Robot/Teleoperator 协议适配与私有 IPC 客户端 |
| `agilex-gello-software/`，Python 3.11 | GELLO/Dynamixel 读取、设备校准、上游通用实验工具 |
| `agilex-sdk-python/`，Python 3.11 | CAN 硬件、运动控制、反馈、ZMQ 服务 |
| `camera-realsense/`，Python 3.11 | RGB-D 采集、设备时间戳、深度单位与标定 |
| `lerobot-converter/`，Python 3.12 | raw 校验、时间戳重采样、LeRobot 数据集与质量报告 |

```text
src/agilex_controller/         命令行应用与 raw 录制
src/agilex_data_collection/    浏览器数采与 LeLab 集成
config/default.toml            两个入口共用的全部配置
scripts/setup.sh               一键配置
scripts/start_gello_follow.sh  无相机跟随 → controller follow
scripts/start_data_record.sh   无相机数采 → controller record
scripts/start_camera_follow.sh 跟随 + 相机预览
scripts/start_camera_record.sh 跟随 + 相机预览 + RGB-D 数采
tests/                         无硬件回归测试与转换集成测试
docs/                          安装、架构、命令、配置和排障
data/raw/                      原始 session，Git 忽略
data/lerobot/                  派生数据集，Git 忽略
data/lerobot/app/              浏览器数采直接写入的数据集
```

五个一级子项目以 Git submodule 固定版本。controller 将 GELLO 基础包和相机库作为
本地 editable 依赖安装；SDK 服务、converter 和浏览器数采使用各自的解释器，
通过 IPC、ZMQ 和文件协作。GELLO 的原生 `gello/` 与本地 `src/` 适配分开维护，
DynamixelSDK 由 GELLO 内固定的嵌套 submodule 提供。详见
[GELLO 开发文档](agilex-gello-software/README.md)。

## 安装

在 Linux 上 clone 项目，然后运行：

```bash
./scripts/setup.sh
```

脚本初始化 submodule、准备 pyenv 和 uv、安装系统依赖并同步各环境。
开发中保留已有子模块修改时：

```bash
./scripts/setup.sh --skip-system --skip-submodules
./scripts/setup.sh --check-only
```

首次使用浏览器数采还需安装独立的 Python 3.12 应用环境（需要网络）：

```bash
uv run agilex-data-collection setup
```

它安装 LeRobot（官方 v0.6.0）与固定提交的 LeLab，并构建网页。默认选择
Python 3.12.14，以避免系统解释器缺少 `Python.h` 导致 evdev 构建失败；
已有完整解释器时可用 `setup --python /path/to/python3.12`。原 controller 的
Python 3.11 环境不会安装这些依赖。

加入 `dialout` 后需要注销并重新登录。完整依赖与手工安装流程见
[安装指南](docs/installation.md)。

## 配置与只读检查

两个入口都读取 [config/default.toml](config/default.toml)：

- `[robot]`、`[gello]`、`[camera]`、`[safety]`、`[paths]` 由 controller 使用，
  浏览器数采也只读复用同一份；`[collection].hardware_config` 为空即表示本文件，
  为实验指定另一份硬件 TOML 时才需要填写。
- `[collection]` 只属于浏览器数采，controller 会忽略该表。

设备 ID、弧度 offset、设备方向和夹爪端点必须与当前 GELLO 标定一致；
`follower_signs` 是额外的主手到从臂方向映射。修改后先用只读命令核对：

```bash
uv run agilex-controller config
uv run agilex-controller read
uv run agilex-controller status
uv run --project camera-realsense camera-realsense info --profiles
```

`read` 只打开主手串口；`status` 调用 SDK 的只读检查，要求 CAN 已配置。
手工配置默认 CAN：

```bash
./agilex-sdk-python/scripts/config_can.sh
```

各字段含义见[配置参考](docs/reference/config.md)。路径字段相对于项目根目录解析。

## 入口一：命令行跟随与录制

以下命令会控制真实机械臂。运行前固定底座、清空工作区，确认急停可用，
并完成上面的只读检查。默认启动流程在运动前显示目标，要求输入 `yes`。

```bash
./scripts/start_gello_follow.sh
./scripts/start_data_record.sh
```

带 RGB 预览的跟随与数采：

```bash
./scripts/start_camera_follow.sh
./scripts/start_camera_record.sh
```

等价的 Python 入口为 `uv run agilex-controller follow` 和
`uv run agilex-controller record`。四个脚本都是 CLI 包装；相机脚本默认传入
`--camera --camera-preview`，其余用户参数随后转交，可以显式覆盖。

流程：

1. 持有互斥锁，检查串口、配置 CAN、检查真实反馈并读取主手。
2. 确认目标；启用相机时预热 RGB-D 并验证时间域、打开预览，再启动 SDK 服务。
3. 通过同一 JS 服务分步回零、对齐，然后开始跟随。
4. Ctrl+C 或 SIGTERM 停止命令，释放客户端与主手，尝试 JS 回零，关闭服务。
5. 关闭相机并刷新未完成 raw episode；数采命令随后离线转换已保存数据。

| 按键 | 操作 |
| --- | --- |
| R | 开始关节 episode；相机数采同时开始 RGB 与深度录制 |
| S | 保存当前 episode |
| D | 丢弃当前 episode |
| P / H | 状态 / 帮助 |
| Ctrl+C | 退出；当前未保存 episode 保留为 `.partial` |

必须先按 S 才会得到可转换的正式 episode。`--start-recording` 自动开始第一集，
仍需按 S 保存；`--skip-conversion` 仅保留 raw；`--yes` 跳过运动确认。
标准输入不是终端时，单键操作不可用。退出保持现有 SDK 的 JS 控制方式，
不切换普通 J 模式、不额外 reset，也不自动失能；失能可能造成机械臂下坠。

完整命令与参数见 [CLI 参考](docs/reference/cli.md)。

## 入口二：浏览器数采

### 启动

```bash
uv run agilex-data-collection serve
```

启动前会按 `[robot]` 调用 SDK 的 CAN 配置脚本（默认 `can0`、1000000 bit/s），
需要提权时在启动终端输入 sudo 密码；链路已就绪时复用。配置失败或已有真机会话
持锁时不启动服务。服务只监听本机回环地址，默认端口 8000（可用 `--port` 修改）；
保持终端运行，打开 <http://127.0.0.1:8000>。

先模拟走通流程（不访问机械臂、主手或相机，但会写入数据目录）：

```bash
uv run agilex-data-collection serve --simulate
```

真机启动会 JS 回零并对齐 GELLO，停止时也会尝试回零。操作人员须在场，确认
底座固定、运动空间清空、急停可用，且主手标定正确。运行新流程前先停止旧流程
及其他占用串口、CAN 或相机的程序。两种模式不要同时运行。

### 采集一段数据

1. 填写“任务描述”，例如“将方块放入盒子”；该描述写入本次会话的数据。
2. 真机模式先勾选运动范围确认，“启动跟随”按钮才会启用；模拟模式无需勾选。
   等待状态变为 `following`，检查预览和跟随是否正常；启动期间请勿重复点击。
3. 点击“开始采样”，等待 `recording` 后完成动作。
4. 点击“保存本段”，确认 `saved_episodes` 增加；不满意时使用“丢弃本段”。
5. 重复“开始采样 → 保存本段”，在同一会话中采集多个 episode。
6. 结束前保存需要的数据，再点击“停止跟随”，等待 `completed` 且无错误，
   最后在终端 Ctrl+C 关闭服务。

网页关闭不会停止会话；必须使用“停止跟随”或服务端 Ctrl+C。停止跟随会丢弃
尚未保存的当前段，已保存的 episode 和已落盘的原始输入保留。后端独立检查
运动确认和会话状态，拒绝启动时返回 409，并在网页和终端说明原因。

### 实时预览

跟随开始后，预览区提供 `RGB`、`深度`、`RGB + 深度`（左右并排）和 `3D 点云`。
预览图下方分别显示：

- **预览 FPS**：浏览器实际接收并解码/渲染的速率。
- **采样 FPS / 目标 FPS**：控制进程实际采到的帧率与 `dataset_fps`（默认 30）。
- **分辨率与捕获 FPS**：RGB 与深度分别标注；“捕获”取自启动时逐路实测的接收
  速率，模式为 `auto`/`fast`/`slow`/`manual`。

预览通过 `/api/preview/ws?mode=rgb|depth|rgbd|cloud` 按 `dataset_fps` 推送，
只在有新帧时发送并丢弃过期帧；编码与点云计算在 3.12 网页进程执行，不进入
3.11 控制/写盘线程，也不会阻塞控制与录制。同一服务最多两个同源连接。

点云由深度图按**标定内参**反投影为深度相机坐标系下的 XYZ（米），按距离着色，
不推测 RGB 纹理或 RGB/深度外参；仅接受无畸变的 rectified 深度标定。
`preview_depth_max_m = 3.0` 控制颜色和截断范围，`preview_cloud_stride = 4`
控制抽稀，单帧最多传输 20000 点。鼠标拖动旋转、滚轮缩放、双击复位；
浏览器需启用 WebGL。这些是显示参数，不改变数据集或原始 `.npy`。

### JS 回零与定位误差

`[collection].position_tolerance_deg = 1.1` 用于启动回零、GELLO 对齐和退出
回零的每轴到位校验，沿用原定位函数的 5 秒最终目标等待；超差即停止，不跳过
验收，也不修改实际关节反馈。用户在 2026-10-20 的 J3 定位调查后明确授权将
容差从 1.0° 调整为 **1.1°**。

日志中的 `[position]` / `[position_result]` 标明 `startup_zero`、
`gello_alignment` 或 `exit_zero`，记录六轴目标、起止反馈、有符号残差、
观测运动范围及成功下发次数。启动异常与清理异常分别记录，网页优先显示结构化
主异常。J3 的标称范围是 **-170° ~ 0°**，即零位就是上限。实机曾出现输出反馈
+1.015°、电机反馈 +0.516°、保持力矩约 -7.6 N·m 的状态：电机到达上限后，
输出侧在负载/传动柔度下多偏约 0.5°，因此残差稳定在 1° 附近。不得直接扣除
offset、自动重标定或切换控制模式；再次运动测试须由现场操作人员确认并启动。

### 数据位置

| 默认位置 | 内容 |
| --- | --- |
| `data/lerobot/app/<session>/` | 直接写入的 LeRobot v3 数据集，无需再运行 converter |
| `data/raw/app/<session>/manifest.json` | 配置、设备标定与相机实际 profile / 吞吐诊断 |
| `data/raw/app/<session>/take_*/` | `samples.jsonl` 时间审计、RGB / 原生 Z16 `.npy`、保存或丢弃结果 |
| `data/logs/<session>.log` | 硬件初始化、故障与清理日志 |

RGB 输出为视频；深度为以米计的 float32 图像特征，原始 Z16 和深度单位另行保留。
控制默认 50 Hz，采样默认 30 FPS，写盘通过有界队列与控制分离。采样取最新帧，
以主机 monotonic 时间检查 RGB、深度与机器人反馈的偏差，超过 `max_skew_ms`
（默认 50 ms）即终止会话。原始时间、帧号、时钟偏移/不确定度、命令发送区间和
反馈请求区间写入审计记录。软件时间映射不等于硬件同步；实际抖动请查
`samples.jsonl`。新 raw 格式不是旧 converter 的输入格式，请勿混用转换命令。

### LeLab 数据集管理

首页为本项目采集面板。点击“LeLab 数据集”进入带返回导航的 `/dataset-browser`，
其中嵌入官方 `/edit-dataset` 页面，可浏览已保存的 episode、RGB 视频和关节变化，
顶部可随时返回数据采集；官方前端保持不变。

- **Merge**：把两个及以上本地数据集合并为新的 `local/<名称>`，写入
  `data/lerobot/app/`；源数据集不变，名称只允许字母、数字、`.`、`_`、`-`。
- **Upload**：上传选中的本地数据集到 Hugging Face Hub。上传前需在终端执行
  `hf auth login`（或使用界面提供的登录接口保存 token），可设置 tags 和 private。
  上传会把数据发布到外部服务，必须由用户主动触发。
- **Delete**：删除选中的本地数据集目录，操作前需在弹窗中确认。只删除本地副本，
  不提供 Hub 仓库删除；数据集正被当前会话使用时接口拒绝删除。删除成功后页面
  会重新加载数据集列表，不会残留已删除的名称。

上传页仅保留数据集摘要、tags、private 和上传按钮；合并弹窗不显示内部路径。
其余功能在嵌入页中为禁用状态，包括返回 LeLab 首页、录制/遥操作、训练/推理、
标定、追加录制、新建数据集和引导流程；直接访问 `/training`、`/inference`、
`/calibration` 等路径会重定向回数据集浏览页。训练/模型任务接口（`/jobs`）
仍未开放，侧栏的 “Couldn't load jobs” 是预期的 404，不影响数据集操作。

### 进程边界

Python 3.12 适配器通过 owner-private Unix IPC 连接 3.11 硬件进程；该进程复用
现有低层初始化、GELLO 校准、SDK 客户端和清理函数，不调用旧 `run_workflow`。
两条真机链路共享原有互斥锁。控制停止发送命令后硬件看门狗触发清理；正常退出
先清理硬件，再完成数据集刷新。

## 相机与时间对齐

默认 `[camera].enabled=false`，原有跟随和数采入口不打开相机。相机脚本显式启用
采集与 RGB 弹窗；启用后请求单台相机的 RGB 和深度各 640×480 @30 FPS。先用
`info --profiles` 核对设备支持；多台设备连接时在配置中填写 `serial`。无桌面
运行相机脚本时可加 `--no-camera-preview`；只采 RGB 加 `--no-camera-depth`。

浏览器数采的 `[collection].camera_mode="auto"` 默认优先 640×360@90 高速预设，
逐路测速不足时按 90/60/30 回退；`slow` 直接尝试低速，`manual` 精确使用
`[camera]` 的分辨率和 FPS。高速候选和探测阈值在
`camera-realsense/config/default.toml` 的 `[performance]`。这不提高默认 30 FPS
的数据集时间轴或 50 Hz 控制频率；实际 profile 以启动后的 metadata 为准。

相机独立线程采集，R/S/D 同时管理各路数据。S 等全部写盘后才发布正式关节
episode；未保存数据保留 `.partial`。相机停帧、断开或写盘队列满会报错并进入
既有安全退出流程。相机 global/system 时间映射到主机单调时钟；converter 将
RGB、深度分别匹配到关节建立的输出时间轴，默认每路最大目标匹配误差 50 ms，
超限拒绝转换，实际误差写入质量报告。算法、单位和误差边界见
[相机与同步](docs/cameras.md)。

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

启用相机时使用 `piper_x_gello_raw` v2，RGB 为无损 PNG，深度为无损 Z16 PNG；
关闭相机仍写兼容的 v1。每行保存最终下发的 action、随后返回的 observation、
单调时钟和墙钟时间；录制不会直接导入 LeRobot。原始数据是权威数据源。

```bash
uv run agilex-controller convert data/raw/SESSION data/lerobot/DATASET
```

将 `SESSION` 和 `DATASET` 替换为实际目录。转换器忽略 `.partial`，拒绝覆盖
已存在的输出；成功后生成 `meta/`、`data/`、RGB `videos/` 和
`quality_report.json`，深度以米制浮点图像无损嵌入 Parquet。同步算法和格式
说明见[转换器文档](lerobot-converter/README.md)。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示先运行 setup | 执行 `uv run agilex-data-collection setup` |
| “启动跟随”不可点击 | 填写任务描述并勾选运动确认；已有会话时先停止并等待清理 |
| `POST /api/start ... 409 Conflict` | 查看网页提示；未确认、任务为空或会话未结束时后端会拒绝 |
| 8000 端口被占用 | 停止旧服务，或 `serve --port 8001` 后打开对应端口 |
| 提示 `CAN interface can0 is DOWN` | 执行 `./agilex-sdk-python/scripts/config_can.sh` 后重试 |
| `startup_zero` / `exit_zero`、`JS positioning failed` | 容差为 1.1°；查看日志 `[position_result]` 的六轴反馈与残差，不跳过校验 |
| 相机快速模式不稳定 | 把 `[collection].camera_mode` 改为 `"slow"`，停止会话后重启 |
| 深度或点云预览不可用 | 确认 `depth_enabled = true` 且已进入 `following`；点云要求无畸变 rectified 深度标定 |
| 点云不显示或拖动无响应 | 启用浏览器 WebGL 并刷新；预览最多两个连接，关闭多余标签页 |
| 时间偏差超限或写盘队列满 | 检查相机、USB、磁盘和负载；必要时降低 `dataset_fps`，且不超过 `control_hz` |
| LeLab 看不到本次数据 | 确认至少保存一段、`saved_episodes` 增加，停止跟随后刷新列表 |
| Upload 失败 | 在终端执行 `hf auth login`，确认网络可访问 huggingface.co |
| 删除数据集失败 | 数据集被当前会话占用时先停止跟随；界面只删除本地副本 |
| LeLab 侧栏显示 Couldn't load jobs | 训练任务接口未开放，属预期 404 |

更多故障处理见[排障指南](docs/reference/errors.md)。

## 文档与验证

- [架构与数据流](docs/index.md)
- [安装指南](docs/installation.md)
- [CLI 参考](docs/reference/cli.md)
- [配置参考](docs/reference/config.md)
- [子模块配置](docs/reference/submodule-config.md)
- [故障排查](docs/reference/errors.md)
- [贡献指南](CONTRIBUTING.md)
- [第三方代码声明](THIRD_PARTY_NOTICES.md)

```bash
uv run --frozen pytest
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --project agilex-adapters --extra app pytest agilex-adapters/tests -q
uv build
```

测试使用本地 ZMQ 假服务、模拟主手和 RGB-D 帧，不访问实体硬件。适配包测试还
包括真实 LeRobot 工厂、Unix IPC、模拟 RGB-D 保存/丢弃与回读。转换集成测试
使用真实 converter 环境生成并读回数据集；测试不能替代真机联调。首次真机
验证必须由操作人员在场完成，模拟测试不证明运动、时序或吞吐精度。
