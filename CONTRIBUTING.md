# 贡献指南

## 开发环境

controller 使用 Python 3.11 和 uv，依赖由 `pyproject.toml` 与 `uv.lock` 管理。GELLO 通过本地 editable 依赖安装；不要在 controller 环境中安装 SDK 硬件依赖、LeRobot 或 PyTorch。

```bash
./scripts/setup.sh --skip-system --skip-submodules
uv sync --frozen
uv run agilex-controller --help
```

SDK 与 GELLO 的独立环境使用 Python 3.11，converter 使用 Python 3.12。各子项目的环境用于其独立工具和开发；一个子项目的 `.venv` 不会自动成为另一个解释器的导入路径。

## 模块分工

| 文件 | 责任 |
| --- | --- |
| `cli.py` | 参数解析、命令分派、退出码 |
| `configuration.py` | TOML、命令行覆盖、校验与路径解析 |
| `robot_client.py` | 对接现有 SDK 的 ZMQ 协议、超时、错误响应与资源关闭 |
| `gello.py` | 显式传入主手校准、主从方向与启动相对映射 |
| `control.py` | JS 定位、启动检查、频率控制、跟随循环、录制按键 |
| `recording.py` | raw v1 session/episode、有界异步队列、保存/丢弃/`.partial` |
| `workflow.py` | 设备预检、进程、信号、客户端组合、安全退出、转换器子进程 |

主手库保持上游读取接口；controller 不导入 GELLO 的应用命令模块。CAN 与硬件保护属于 SDK；时间戳对齐和数据转换属于 converter。新增图像库接入不在本次范围内。

## 修改原则

- Python 使用四空格缩进、公开接口类型标注、`snake_case` 函数/模块和 `PascalCase` 类名，使用 Ruff 检查与格式化。
- 设备实例在 workflow 中创建并统一释放；新步骤失败时仍需完成之前已获取资源的清理。
- 使用单调时钟安排控制周期和记录相对时序；墙钟用于诊断。当前 raw 的 observation 是 action 下发后的反馈，修改配对语义必须同时评估转换与训练用途。
- 保持 RPC 等待有界。REQ 请求超时或被中断后关闭该 socket，退出回零使用独立客户端。
- 录制使用有界队列，写盘或队列错误必须显式上报；失败数据保持 `.partial`。保存中断不能遗留等待 sentinel 的线程。
- 退出时先结束硬件控制，再做耗时刷新与转换。不要跳过 JS 退出流程或在退出期间切换普通 J 模式。
- `scripts/` 保留三个 Shell 入口：一个负责安装，两个只调用 controller CLI。不要在两个启动脚本中分别复制运行流程。
- 校准写在配置文件中，通过 `DynamixelRobotConfig` 传给 GELLO；不要为当前串口修改库中的全局端口表。

## 检查与测试

从 controller 根目录运行：

```bash
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest
bash -n scripts/setup.sh scripts/start_gello_follow.sh scripts/start_data_record.sh
uv build
```

pytest 的 `tests/test_*.py` 覆盖配置优先级、SDK wire protocol、启动检查、JS 步长、录制、信号与清理顺序。测试不访问硬件。

完整测试还会调用 `lerobot-converter/.venv/bin/python` 执行真实转换与数据集读回；未安装该环境时跳过这项测试。安装环境后可单独执行：

```bash
uv run --frozen pytest -m integration
uv run --frozen pytest -m "not integration"
```

没有全仓覆盖率门槛。为行为变化增加针对性测试，尤其是异常、取消和数据兼容；避免只复述实现的测试。

修改 GELLO 后，在其目录执行 `uv run --frozen pytest`。本地适配仅修改 `src/`，原生 `gello/`、脚本和配置由哈希清单约束，检查方式为：

```bash
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen ruff check gello experiments scripts --select E9,F63,F7,F82
uv run --frozen python -m agilex_gello_software.upstream
```

不要格式化原始上游文件；必要行为适配写入本地 src。GELLO 与 controller 环境都通过 uv 安装固定的 `third_party/DynamixelSDK/python`；依赖变化同步更新两份 uv.lock。SDK 服务项目本次保持原样；如后续单独修改，使用其 README 中的检查流程。

## Submodule 与多仓库工作流

`../agilex-gello-software/` 是独立工作副本，controller 内的同名目录是另一个 Git 工作副本。它们不会自动同步文件。

发布版本时，先在 GELLO 仓库提交、测试并推送，再让 controller submodule 检出该提交，最后在 controller 提交 gitlink。不要提交无法从远端获取的子项目提交。

```bash
git -C agilex-gello-software status --short
git submodule status
git diff --submodule
```

开发期间子模块有未提交修改时，使用 `scripts/setup.sh --skip-submodules`。默认 setup 会拒绝脏子模块，避免把正在审阅的内容切回锁定版本。为普通使用者更新版本后，应验证一次干净检出的安装流程。

## 提交与 PR

使用简洁、祈使式主题，可采用 `feat:`、`fix:`、`refactor:`、`docs:`、`chore:` 前缀。将行为修改、必要测试和对应文档放在同一可审阅变更中。

PR 描述应说明问题与最终行为、涉及仓库及版本、运行过的检查、真实硬件是否验证，以及相关 issue。终端工具通常不需要截图。不得把模拟测试描述为真实机械臂验收。

## 数据与文档

`data/raw/` 是不可变输入，`data/lerobot/` 是可重新生成的输出。不要提交采集数据、虚拟环境、构建产物和缓存。路径相对于仓库计算，不写死个人 home 目录。

参数或默认行为变化时同步更新 README、`config/default.toml`、`docs/reference/`、CHANGELOG 和必要测试。保留 `docs/assets/` 中的硬件资料。第三方代码的来源和许可文本记录在 `THIRD_PARTY_NOTICES.md`。
