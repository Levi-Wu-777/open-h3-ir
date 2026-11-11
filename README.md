# OpenH3-IR

面向 MiniMax H3 的提示词优化器，本 Fork 关闭作者附加的内容拦截，支持 DeepSeek 与可指定语言的提示词正文。

- `h3ir/`：素材分析、模型调用、语言设置、官方格式校验及 API。
- `tests/`：格式、策略关闭、语言传递与模型协议回归。
- `h3ir/policies.py`：每条诊断规则的来源与是否启用；来源不明的新增内容策略默认关闭。
- [完整分类与本轮实测报告](https://github.com/Levi-Wu-777/xiaosongshu-benchmark-data/blob/main/261112-xiaosongshu-OpenH3-IR修正版-DeepSeek实测.md)：规则逐项分类、十组输入与输出、序列长度、调用与耗时、中文用例。

安装源码后，可使用原有模型接口配置运行 `h3ir`。本机 DeepSeek 入口从已登录的 Infisical 读取密钥，普通配置与密钥值不写进仓库：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install -e /Users/levi/Workspace/xiaosongshu/src/share/infisical
.venv/bin/h3ir-deepseek compile '雨夜车站，一名旅客等候列车' --prompt-language zh-CN
```

`prompt_language` 默认 `English`，可传 `zh-CN`、`中文`、其他语言名称或 `auto`。正文按指定语言生成，H3 章节键、标签和标记保持原格式；用户对白和屏幕文字保留原文。

API 示例：

```json
{"intent":"雨夜车站，一名旅客等候列车","prompt_language":"zh-CN"}
```

保留有直接官方依据的格式、用户明确指定的约束，以及文件、协议、实际运行时容量等工程检查。镜头最低时长、默认镜头数量上限、扩写权限词表、强制风格覆盖、正文裁剪等作者策略已关闭。官方写作指南仍随模型请求提供，其中的英文写作要求可由用户显式语言参数覆盖。

默认路径不预存模板稿。校验只提供诊断与最多一轮反馈修正，即首次生成后最多再改一次；仍含 ERROR 时保留最新完整模型稿，以正常响应和 `needs_review` 状态交付。后续修正调用失败也保留已有模型稿；尚无任何完整模型输出时，返回真实接口错误。

独立素材最多四路并发分析，写作与修正按依赖顺序执行。DeepSeek 每次调用最多尝试三次，失败重试前固定等待一秒，单次尝试的总 deadline 为三十秒。

验证：

```bash
.venv/bin/h3ir controls
.venv/bin/pytest -q
```

上游为 [ruashots/open-h3-ir](https://github.com/ruashots/open-h3-ir)，基线 `fd031e1`。保留 Apache-2.0 许可证与原始 NOTICE；本项目为非官方实现。
