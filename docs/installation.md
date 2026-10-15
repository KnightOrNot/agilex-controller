# 安装与环境

## 要求

使用支持 SocketCAN 的 Linux、PiPER-X/AGX 夹爪、USB-CAN 与 GELLO Dynamixel 主手。软件工具为 Git、pyenv、uv、iproute2、FFmpeg、编译工具和 lsof。系统包与转换依赖在 converter 环境中验证，不进入实时控制环境。

controller/GELLO/SDK 的开发解释器是 Python 3.11；converter 是 3.12。根目录的 `requires-python` 当前限制为 `>=3.11,<3.12`，与 GELLO 包一致。

## 一键配置

```bash
git clone git@github.com:KnightOrNot/agilex-controller.git
cd agilex-controller
./scripts/setup.sh
```

setup 从脚本位置找到仓库，初始化三个一级 submodule 以及 GELLO 内必需的 DynamixelSDK，通过 pyenv 选择各自 Python，再用 uv 的锁文件同步环境。它会安装 Ubuntu 系统包、按需安装 pyenv/uv，并检查 dialout。配置过程不访问 CAN/串口，不发送运动命令。

常用参数：

| 参数 | 用途 |
| --- | --- |
| `--skip-system` | 已装好系统依赖时跳过 apt 与用户组修改 |
| `--skip-submodules` | 保留本地子项目修改，不重新检出锁定提交 |
| `--check-only` | 只检查已安装环境与命令 |
| `--gello-extra NAME` | 仅为 GELLO 独立环境安装可选 camera/simulation/robots/full |
| `--with-simulation-assets` | 显式下载 GELLO 的 MuJoCo Menagerie |

控制与当前数值采集只需要 GELLO 基础依赖。默认安装不下载仿真模型。

## 手工同步

已有 pyenv 与 uv 时：

```bash
git submodule update --init
git -C agilex-gello-software submodule update --init third_party/DynamixelSDK
pyenv install -s "$(pyenv latest -k 3.11)"
pyenv install -s "$(pyenv latest -k 3.12)"
python311="$(PYENV_VERSION="$(pyenv latest -k 3.11)" pyenv which python)"
python312="$(PYENV_VERSION="$(pyenv latest -k 3.12)" pyenv which python)"

UV_NO_MANAGED_PYTHON=1 uv sync --project agilex-sdk-python --frozen --python "$python311"
UV_NO_MANAGED_PYTHON=1 uv sync --project agilex-gello-software --frozen --python "$python311"
UV_NO_MANAGED_PYTHON=1 uv sync --project lerobot-converter --frozen --extra dataset --python "$python312"
UV_NO_MANAGED_PYTHON=1 uv sync --frozen --python "$python311"
mkdir -p data/raw data/lerobot
```

GELLO 包通过根目录 `tool.uv.sources` 中的本地 editable 路径安装。controller 与 GELLO 独立 CLI 各自安装相同代码的基础依赖，这是两个独立环境；无需将多个虚拟环境加入 PYTHONPATH。

GELLO 的原生 `gello` 与本地适配由同一个分发包提供，DynamixelSDK 使用其固定 checkout 的 Python 源（3.7.51），不再从 PyPI 安装 4.0.5。开发期间使用 `--skip-submodules` 保留本地改动，前提是嵌套 SDK 已初始化。

## 安装验证

```bash
./scripts/setup.sh --check-only
uv run --frozen agilex-controller --help
uv run --frozen agilex-controller config
uv run --frozen pytest
```

脚本会检查 CLI、FFmpeg 与 converter 的 TorchCodec 加载。真实转换回归可通过 `uv run --frozen pytest -m integration` 单独运行。

## 串口与 CAN

```bash
sudo usermod -aG dialout "$USER"
```

注销并重新登录后检查 `/dev/serial/by-id/`，修改 `config/default.toml` 中的 port 与标定参数。不要只凭串口名沿用另一台主手的校准。

```bash
./agilex-sdk-python/scripts/config_can.sh can0 1000000 100
uv run agilex-controller read --json
uv run agilex-controller status
```

确认状态完整、CAN 收包正常后按 README 启动。安装路径改变时重新创建对应 `.venv`，不要修补旧 console-script shebang。
