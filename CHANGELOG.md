# Changelog

## Unreleased

- 相机库新增 640×360@90 FPS 优先、逐流吞吐探测和 90/60/30 启动回退；
  新数采应用默认 camera_mode=auto，保留旧 controller 的显式 profile。
- 五个一级子模块全部提供 config/default.toml，补齐 SDK、GELLO 本地读取、
  converter 和 adapters 的配置加载、覆盖校验、包内默认值和文档。SDK 硬件驱动、
  原生 GELLO 及既有 controller 运行源码保持不变；USB3 相机实测待完成。

- 新增独立 `agilex-data-collection` 入口与 Python 3.12 应用环境，引入
  `agilex-adapters` 子模块，为 PiPER-X/GELLO 提供 LeRobot 设备接口。
- 新增浏览器跟随/采样/保存/丢弃/停止面板，直接写入 LeRobot RGB-D 数据集，
  保留原始 Z16、校准与时间审计信息，接入 LeLab 官方只读数据浏览功能。
  原 controller 源码、配置和 Shell 入口保持不变；真机联调待操作人员验证。

- 图像写盘改用固定行过滤的快速无损 PNG，默认 png_compress_level=0，保留逐文件 fsync 和原始 RGB/Z16；新增 TOML/CLI 压缩等级配置、队列满吞吐诊断和无损读回测试，避免自适应 PNG 编码导致持续积压。

- 修复相机预热期间帧号回退直接中断启动：双流就绪前重新建立基线，运行期仍严格报错；补充相机就绪提示和启动超时诊断。

- 引入 camera-realsense submodule，新增 start_camera_follow.sh / start_camera_record.sh，分别提供跟随预览和 RGB-D 数采；原有脚本与默认配置恢复无相机流程。
- 新增 raw v2 无损 RGB/Z16 图像、独立 SDK 时间戳与标定；保留无相机 raw v1。
- converter 按同一目标轴独立匹配关节/RGB/深度，超限拒绝，输出 RGB MP4 与无损米制深度图像，并报告匹配质量。
- 新增 RGB-D 录制失败清理、缺帧/队列满和真实 LeRobot 视频/深度读回回归；实体相机与机械臂联调待验证。

- GELLO 恢复原始上游目录，将本地 API/生命周期适配留在 src；安装流程初始化固定 DynamixelSDK，两个 uv.lock 同步依赖来源，保留现有 controller 调用与 raw 格式。
- 统一三个 submodule 的 README、贡献/agent 指南、版本记录和 docs 结构，更新独立使用与 controller 联调说明；保留已有许可并记录未选定许可的项目状态。
- 将 PiPER-X/GELLO 的客户端组合、设备预检、JS 对齐、跟随、原始录制和退出流程迁入 Python 3.11 controller。
- 增加 `uv run agilex-controller` 的 config、read、status、follow、record、movejs、convert 命令及 follow-record 别名。
- 将设备校准和应用默认值集中到 `config/default.toml`，支持配置文件与命令行覆盖。
- 保留 raw v1 格式和 converter 的独立 Python 3.12 进程，新增真实转换与读回测试。
- 将两个运行脚本简化为 CLI 包装，修正三个脚本迁入 scripts 后的项目根目录。
- 从 GELLO 库移除 PiPER-X 专用命令、录制器及旧实验包装，恢复库自身的上游 YAM 配置；保留主手 API 和通用上游工作流。
- 补充 RPC 超时、端口占用检查、信号清理、初始化失败和保存中断回归。
- 更新安装、命令、配置、架构和多仓库开发文档。SDK 与 converter 的源代码保持原样。
