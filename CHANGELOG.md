# Changelog

## Unreleased

- 统一三个 submodule 的 README、贡献/agent 指南、版本记录和 docs 结构，更新独立使用与 controller 联调说明；保留已有许可并记录未选定许可的项目状态。
- 将 PiPER-X/GELLO 的客户端组合、设备预检、JS 对齐、跟随、原始录制和退出流程迁入 Python 3.11 controller。
- 增加 `uv run agilex-controller` 的 config、read、status、follow、record、movejs、convert 命令及 follow-record 别名。
- 将设备校准和应用默认值集中到 `config/default.toml`，支持配置文件与命令行覆盖。
- 保留 raw v1 格式和 converter 的独立 Python 3.12 进程，新增真实转换与读回测试。
- 将两个运行脚本简化为 CLI 包装，修正三个脚本迁入 scripts 后的项目根目录。
- 从 GELLO 库移除 PiPER-X 专用命令、录制器及旧实验包装，恢复库自身的上游 YAM 配置；保留主手 API 和通用上游工作流。
- 补充 RPC 超时、端口占用检查、信号清理、初始化失败和保存中断回归。
- 更新安装、命令、配置、架构和多仓库开发文档。SDK 与 converter 的源代码保持原样。
