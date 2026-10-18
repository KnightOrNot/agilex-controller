# 子模块默认配置

五个一级子模块均提供 `config/default.toml`。主项目配置由主项目解析，
并通过显式 CLI/API 参数传给子模块；子模块不隐式读取父项目文件。
SDK 的硬件驱动、CAN 脚本以及 GELLO 的原生 YAML/第三方代码保持原行为。

| 子模块 | 配置范围 | 覆盖方式 |
| --- | --- | --- |
| camera-realsense | 采集、输出、各实验和 performance 预设 | `camera-realsense --config PATH rgbd` |
| agilex-gello-software | 本地 read 参数与可选六轴/夹爪标定 | `agilex-gello-software read --config PATH` |
| agilex-sdk-python | connection、cli、server 默认值 | 诊断 CLI / `agilex-sdk-python-server --config PATH` |
| lerobot-converter | conversion 路径、FPS、可选特征、匹配容差 | `lerobot-converter --config PATH INPUT OUTPUT` |
| agilex-adapters | piperx / gello 的 endpoint、timeout_s | CLI 查看；`PiperXConfig.from_toml(path, **overrides)` |

显式参数优先。新增的四个子模块支持部分自定义 TOML 覆盖仓库默认值；
相机库沿用原有“选择完整配置”的规则，旧文件没有 performance 时保持 manual。
未知字段、错误类型和非有限配置数值会报错。相对数据路径沿用各 CLI 的
当前工作目录规则；默认配置文件本身的查找不依赖工作目录。

每个源码包的 `default.toml` 是指向仓库配置的链接；构建后在 wheel 中
物化为独立文件，保证安装后的包能找到默认值。不要手工维护第二份配置。
各库低层 Python API 的显式参数约定继续有效，不把 CLI 配置隐式灌入硬件驱动。

## 快速相机策略

相机库和新数采应用默认优先 640×360@90 FPS，每路实际接收帧率至少达到
目标的 85% 才接受；按 90/60/30 回退，最终 30 FPS 保留普通 profile 的分辨率。
原生 Z16、深度尺度和最终 profile 的标定信息完整保留。模式切换只发生在
首帧交付前，不在录制中途重置帧号和时钟。测速验证采集吞吐，不验证磁盘吞吐。

新应用在 `config/data_collection.toml` 中设置 `camera_mode`，默认 auto；
slow 直接测速低档，manual 使用主项目安装配置中的相机分辨率和 FPS。
旧 controller 的显式 profile 继续使用原帧率，不被库的 auto 默认值覆盖。
数据集 FPS 仍由应用独立配置，90 FPS 相机不会自动生成 90 FPS 数据集。

细节见[相机配置参考](../../camera-realsense/docs/reference/config.md)与
[新数采流程](../data-collection.md)。本轮未进行相机或机械臂实测。
