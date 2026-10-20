# 架构与数据流

项目有两个并列入口，共用设备配置、硬件互斥锁和底层客户端：命令行 controller
负责跟随与 raw 录制，浏览器数采负责按键采集并直接写入 LeRobot。

## 边界

controller 是命令行入口。它决定使用哪些客户端、何时启动或关闭服务，以及何时
开始、保存或丢弃 episode。浏览器数采以另一个进程编排同一套硬件。

```mermaid
flowchart LR
    G[GELLO 库：读取与校准] --> C[controller：映射与跟随]
    A[RealSense 库：RGB-D 帧与时钟] --> C
    C -->|ZMQ action| S[SDK 服务：CAN 与机械臂]
    S -->|ZMQ observation| C
    C --> R[data/raw：JSONL、图像与 manifest]
    R --> L[converter：校验和时间对齐]
    L --> D[data/lerobot：Dataset v3]

    W[agilex-data-collection：3.12 网页] -->|Unix IPC| H[硬件 worker：3.11]
    H --> G
    H --> A
    H --> S
    H --> R2[data/raw/app：RGB/Z16、时间审计]
    H --> D2[data/lerobot/app：Dataset v3]
    W -->|同源代理| B[LeLab：浏览、合并、上传、删除]
```

| 运行单元 | 环境 | 数据/设备所有权 |
| --- | --- | --- |
| controller + GELLO 基础包 + camera | 根目录 `.venv`，3.11 | GELLO 串口、相机、机器人客户端、应用状态、raw |
| SDK server | SDK 自己的 `.venv`，3.11 | CAN、机械臂反馈与命令 |
| converter | converter 自己的 `.venv`，3.12 | 只读 raw，写新 LeRobot 数据集 |
| agilex-data-collection 网页 | `agilex-adapters/.venv`，3.12 | 浏览器 UI、预览编码、LeLab 集成 |
| 硬件 worker + 适配器 | 根环境与 adapters 环境，3.11/3.12 | 复用 controller 的设备初始化与清理 |

controller 的 `RobotClient` 是现有 SDK wire protocol 的应用侧适配器。本次未修改 SDK；协议仍为 ZMQ REQ/REP 和 pickle 的 `method/args` 请求。服务默认监听本机，部署时保持在可信网络范围内。

GELLO 的原始实现位于 `gello/`；controller 导入兼容的 `agilex_gello_software` src 适配，其 `GelloAgent.act()`、校准映射和滤波复用上游，实现显式 close 与真实读取保护。设备校准显式传入，PiPER-X 专用的方向映射、客户端与录制留在 controller。

## 生命周期

原有无相机入口和新增相机入口的 `follow` 与 `record` 共用 workflow：

1. 校验配置，获取与旧启动入口共用的互斥锁。
2. 检查串口权限与 SDK endpoint，配置 CAN，验证反馈。
3. 读取 GELLO，显示主从目标，等待运动确认。
4. 启用相机时先启动并预热 RGB-D、确认两路对齐时间域；相机脚本同时启用预览。再启动独立 session 的 SDK 子进程，等待七自由度 RPC 就绪。
5. JS 分步回零并对齐，创建主手，再执行带启动误差检查的跟随。
6. 收到 Ctrl+C/SIGTERM 或异常时，停止循环，关闭主手与原客户端，使用新客户端尝试 JS 回零并停止所拥有的服务。
7. 关闭相机并刷新图像与 raw；只有前面流程正常退出且有正式 episode 时才自动转换。

SDK 子进程不会随终端 Ctrl+C 先于回零退出。初始化中的停止请求会延迟到资源引用取得后处理；清理阶段屏蔽重复停止信号。RPC 失败、回零失败和写盘失败会报告错误，已保存 raw 可单独转换。

`--existing-server` 跳过本地 CAN/SDK 预检及服务启停。它仍会执行确认、启动回零、对齐和退出回零，因此要按同样的真实运动流程使用。

## 浏览器数采生命周期

`agilex-data-collection` 是独立的浏览器入口，与命令行 controller 并列，不替代
也不调用旧 `run_workflow`：

1. `serve` 在启动网页进程前，按 `[robot]` 调用 SDK 的 CAN 配置脚本；模拟模式跳过。
2. 网页进程校验运动确认和任务描述，通过后拉起 3.11 硬件 worker。
3. worker 获取共享互斥锁，复用 controller 的设备预检、GELLO 校准、SDK 服务和清理函数，
   完成相机预热、JS 回零与 GELLO 对齐。
4. 适配器通过 owner-private Unix IPC 收发动作；网页按 `dataset_fps` 发布预览，
   编码在 3.12 进程完成，不阻塞控制线程。
5. 采样帧、原始 RGB/Z16 与审计记录落盘；控制停止后看门狗触发清理。
   正常退出先清理硬件，再刷新数据集。
6. 数据集由官方 `LeRobotDataset` 直接写成 v3；LeLab 通过同源路由浏览、合并、
   上传和删除本地副本。

两条真机链路共享原有互斥锁，不能同时运行。进程间不暴露 pickle over TCP。

## 控制样本

默认控制频率为 50 Hz。controller 读取主手、映射六轴目标、限制六轴单步变化，发送最终 action，再读取 observation；夹爪单独直接传递。

raw v1/v2 的关节行包含：

- `sequence`：episode 内从 0 连续递增。
- `command_time_ns`、`observation_time_ns`：主机单调时钟，分别在发送前和反馈返回后打点。
- `wall_time_ns`、`control_period_ns`：墙钟与相邻命令周期。
- `action`、`joint_positions`、`joint_velocities`、`ee_pos_quat`：各 7 维。
- `gripper_position`：归一化反馈标量。

六轴单位 rad，速度 rad/s，位置 m，四元数 xyzw。第七维为夹爪，不是额外的机械臂转轴。observation 时间是客户端收取反馈的近似时刻；同步与重采样由 converter 决定。

## 原始数据完整性

队列写盘与控制循环分离。R 创建 `.jsonl.partial`；S 等待落盘后原子改名为 `.jsonl`；D 删除当前 partial。退出时活动 episode 刷新为 partial，转换器忽略它。

一次 session 生成一份数据集；目标目录已存在时转换失败。相机使用 raw v2，图像与关节各自异步写盘；S 刷新全部写线程，先发布图像目录，最后发布正式关节 JSONL。正式关节文件是转换入口；异常集保持 partial，极端中断留下的孤立图像目录不单独转换。无相机继续写 v1。详见[相机与同步](cameras.md)。

浏览器数采使用独立的 `data/raw/app/<session>/` 审计格式和
`data/lerobot/app/<session>/` 输出，不经过 converter，也不要与旧 raw 混用转换命令。
该格式保留原始 RGB uint8、原生 Z16、相机标定、钟差和每帧时间戳。

## 子项目独立文档

各 submodule 的 README 提供独立快速开始，`docs/` 提供安装、CLI、配置与排障，CONTRIBUTING 说明开发检查与提交要求。

| 项目 | 使用与架构 | 贡献指南 |
| --- | --- | --- |
| GELLO | [README](../agilex-gello-software/README.md) / [架构](../agilex-gello-software/docs/index.md) | [CONTRIBUTING](../agilex-gello-software/CONTRIBUTING.md) |
| SDK | [README](../agilex-sdk-python/README.md) / [协议](../agilex-sdk-python/docs/index.md) | [CONTRIBUTING](../agilex-sdk-python/CONTRIBUTING.md) |
| Camera | [README](../camera-realsense/README.md) / [采集 API](../camera-realsense/docs/stream.md) | [CONTRIBUTING](../camera-realsense/CONTRIBUTING.md) |
| Converter | [README](../lerobot-converter/README.md) / [数据流](../lerobot-converter/docs/index.md) | [CONTRIBUTING](../lerobot-converter/CONTRIBUTING.md) |
| Adapters | [README](../agilex-adapters/README.md) | [CONTRIBUTING](../agilex-adapters/CONTRIBUTING.md) |
