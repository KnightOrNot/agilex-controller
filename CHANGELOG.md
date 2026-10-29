# Changelog

按版本简要记录主要变更。用法、配置和排障见 [README](README.md)。

## 0.1.0（未发布，2026-10-29）

### 子模块版本同步

- 以五个可获取的远端 main 为基线重新锁定引用，补齐 IPC 设备适配、RGB-D 转换与相机模式接口，并重新验证独立解释器间的采集与数据集读回。
- 当前 GELLO 使用 PyPI DynamixelSDK 4.0.5；安装脚本兼容这一布局，真机初始化禁止假驱动回退。
- camera/converter 的默认 TOML 随 wheel 分发。当前 SDK/GELLO/adapters 的参数通过公开 CLI/API 显式传入；历史统一子模块 TOML 的说明由此替代。

### 新增

- 两个并列入口：命令行 `agilex-controller` 负责跟随、raw 录制和离线转换；
  `agilex-data-collection` 提供浏览器按键数采，直接写入 LeRobot Dataset v3。
- 浏览器面板支持启动/停止跟随、采样、保存、丢弃，并显示状态、错误和已保存集数。
- RGB、深度、RGB + 深度和交互式 3D 点云预览，按数据集 FPS 推送，显示浏览器
  预览 FPS、采样/目标 FPS、两路分辨率和实测捕获 FPS。
- LeLab 数据集浏览、本地合并、Hugging Face 上传和本地删除；未实现功能禁用，
  `/jobs` 保持预期 404。
- 相机 640×360@90 优先，逐路测速后按 90/60/30 回退；保留原生 Z16、标定和时间戳。
- 新增独立 `agilex-adapters` 子模块，提供 LeRobot 设备适配和私有 Unix IPC。

### 变更

- 配置统一到 `config/default.toml`：controller 使用原有表，浏览器数采使用
  `[collection]`；删除独立的 `config/data_collection.toml`。
- 文档精简：删除两份数采专文，合并进 README、架构、安装、配置、CLI 和排障文档。
- JS 定位容差从 1.0° 调整为 1.1°。J3 零位即机械上限，输出侧约 0.5° 柔度导致
  启动/退出回零残差约 1.0°；不扣 offset、不自动重标定、不切换运动模式。
- 数采前端移除原始状态 JSON、Repository ID、HuggingFace 说明和内部路径提示，
  保留预览统计、数据集元数据和未实现功能的禁用状态。

### 修复

- 删除本地数据集后重新加载 LeLab 数据集列表，已删除名称不再残留。
- 相机预热期间帧号回退时重建基线，运行期仍严格报错。
- CAN 未启用或波特率不符时给出明确诊断，网页显示 worker 最终错误。
- 图像写盘改用固定行过滤的无损 PNG，避免编码积压；保留逐文件 fsync。

## 0.0.0（初始开发，2026-09 至 2026-10）

- 将 GELLO 读取、PiPER-X 客户端组合、设备预检、JS 对齐、跟随和 raw 录制迁入
  Python 3.11 controller，提供 `config`、`read`、`status`、`follow`、`record`、
  `movejs`、`convert` 命令和 Shell 包装脚本。
- 新增 raw v1 和相机 raw v2：无损 RGB/Z16、独立 SDK 时间戳、标定和 manifest。
- `lerobot-converter` 在独立 Python 3.12 环境完成时间匹配、LeRobot 数据集和
  质量报告。
- 引入 `camera-realsense` 子模块和相机跟随/数采脚本；原有脚本保持无相机流程。
- GELLO 恢复上游目录结构，本地适配留在 `src/`，固定嵌套 DynamixelSDK。
- 补充 RPC 超时、端口占用、信号清理、初始化失败、写盘失败和保存中断回归。
