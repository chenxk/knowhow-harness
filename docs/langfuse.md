Langfuse 是一个专为大语言模型（LLM）应用设计的开源 [LLMOps 工程平台与可观测性工具](https://langfuse.com/cn)，常被称为开源的 [LangSmith 替代品](https://www.reddit.com/r/LangChain/comments/1l36tte/all_langfuse_product_features_now_free_opensource/?tl=zh-hans)。它帮助开发者和团队在生产环境中监控、调试、评估和迭代 AI 应用。 [1, 2, 3, 4] 
## 核心功能

* 链路追踪（Tracing）：记录每一次 LLM 调用、向量检索（RAG）、工具使用及代理（Agent）交互的输入、输出、延迟、Token 消耗和成本。 [3, 5, 6] 
* 提示词管理（Prompt Management）：集中管理、版本控制和远程部署 Prompt，支持在后台进行 Playground 调试。 [3] 
* 评估系统（Evaluations）：支持通过 LLM-as-a-Judge（大模型作为裁判）、用户反馈和人工标注对模型输出质量进行打分和持续监控。 [3] 
* 数据集与实验（Datasets & Experiments）：构建标准测试集，在部署新版本前对 AI 应用进行回归测试和效果对比。 [3] 

## 部署与集成

* 开源自托管：采用 MIT 协议开源，支持通过 Docker、Kubernetes 在本地或私有云快速部署（数据存储后端结合了 PostgreSQL 和 ClickHouse）。 [3, 7] 
* 生态兼容：原生集成 Python/JS SDK，并与 [LangChain](https://www.langchain.com/)、LlamaIndex、[Dify](https://dify.ai/)、[LiteLLM](https://litellm.ai/) 以及 OpenTelemetry 等主流 AI 框架和工具链广泛兼容。 [4, 5, 7] 

如果你正在开发 LLM 或 Agent 应用，想了解如何将 Langfuse 接入你的项目（如 Python 代码或 Dify 工作流），还是想了解它的 自托管部署方式？

[1] [https://github.com](https://github.com/langfuse/langfuse/blob/main/README.cn.md)
[2] [https://www.reddit.com](https://www.reddit.com/r/LangChain/comments/1l36tte/all_langfuse_product_features_now_free_opensource/?tl=zh-hans)
[3] [https://zhuanlan.zhihu.com](https://zhuanlan.zhihu.com/p/1963597057790027686)
[4] [https://zhuanlan.zhihu.com](https://zhuanlan.zhihu.com/p/1900318017461663654)
[5] [https://wiki.hiwepy.com](https://wiki.hiwepy.com/docs/langfuse)
[6] [https://zhuanlan.zhihu.com](https://zhuanlan.zhihu.com/p/30334812389)
[7] https://langfuse.com
