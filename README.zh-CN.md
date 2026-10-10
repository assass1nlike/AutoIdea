# AutoResearchClaw

[English](README.md)

输入一个研究方向，经过问题拆解、文献检索、筛选和综合，生成有文献背景的研究假说。这个仓库保留了 AutoResearchClaw 的前 8 个阶段，运行到 idea 生成为止；产物包括候选方案、研究缺口、可检验的预测和失败条件，不执行实验或撰写论文。

[首次运行](#安装与首次运行) · [流程与结果](#流程与结果) · [配置说明](#配置说明) · [提示词](#自定义提示词) · [续跑与人工参与](#分段运行续跑与人工参与) · [其它配置](#其它配置与当前接入范围) · [常见问题](#常见问题)

## 安装与首次运行

需要 Python 3.11+，以及可用的模型 API 和学术检索网络连接。使用远程模型时不需要本地 GPU。以下命令在仓库根目录执行，使用 Windows PowerShell。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

后面的命令统一使用这个虚拟环境的 Python，无需激活环境。Linux / macOS 将 `.\.venv\Scripts\python.exe` 换成 `./.venv/bin/python`，环境变量使用 `export NAME="value"` 设置。

下面的命令从仓库示例生成 `config.arc.yaml`，交互终端中会询问模型服务商。已有配置不会被覆盖，`init --force` 才会覆盖。

```powershell
.\.venv\Scripts\python.exe -m researchclaw init
```

也可以直接将下面这份完整配置保存为 `config.arc.yaml`。修改 `research.topic`、`llm.base_url` 和 `llm.primary_model`，再设置对应的 API Key。`YOUR_MODEL_ID` 必须替换为服务商实际提供的模型 ID。

```yaml
project:
  name: "agent-memory"
  mode: "full-auto"
  profile: "ml_nlp"

research:
  topic: |
    研究 LLM agent 在长期任务中的记忆失效。
    寻找尚未解决且有研究价值的具体问题，提出可证伪的研究假说。
    优先考虑能够明确区分现有方法、且能用公开数据验证的方案。
  domains: ["machine-learning", "LLM agents"]
  quality_threshold: 0.7

runtime:
  timezone: "Asia/Shanghai"

notifications:
  channel: "console"

knowledge_base:
  backend: "markdown"
  root: "artifacts/idea-01/kb"

llm:
  provider: "openai-compatible"
  base_url: "https://api.openai.com/v1"
  wire_api: "chat_completions"
  stream: false
  api_key_env: "OPENAI_API_KEY"
  api_key: ""
  primary_model: "YOUR_MODEL_ID"
  fallback_models: []
  timeout_sec: 600

literature_search:
  sources: ["openalex", "semantic_scholar", "arxiv"]
  max_results_per_query: 40
  inter_query_delay_sec: 1.5
  openalex_email: ""
  openalex_api_key_env: "OPENALEX_API_KEY"
  openalex_api_key: ""
  s2_api_key_env: "S2_API_KEY"
  s2_api_key: ""

web_search:
  enabled: false

security:
  hitl_required_stages: [5]

prompts:
  custom_file: ""
  extra_prompts: {}

hitl:
  enabled: false

metaclaw_bridge:
  enabled: false
```

这份配置启用学术 API 检索，关闭额外网页检索和人工交互；可选能力见下文。仓库的 [示例配置](config.researchclaw.example.yaml) 使用另一组示例值，`init` 会复制它，并不生成上面这份配置。

```powershell
$env:OPENAI_API_KEY = "你的模型 API Key"
$env:PYTHONUTF8 = "1"

.\.venv\Scripts\python.exe -m researchclaw validate --config config.arc.yaml --no-check-paths
.\.venv\Scripts\python.exe -m researchclaw info --config config.arc.yaml
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve
```

`validate` 检查配置，不调用模型；首次运行前加 `--no-check-paths`，因为知识库目录尚未创建。`info` 显示解析后的领域、提示词库和附加提示。`run` 先发送一次模型连通性检查请求，再依次执行 8 个阶段。`--auto-approve` 自动通过常规审批关卡；文献筛选为空等情况仍可能使流程暂停。

如果使用 SudoRelay，可将 `base_url` 设为 `https://api.sudorelay.com/v1`，填入该服务支持的模型 ID；对于支持 Chat Completions 流式响应的网关，可设置 `stream: true` 来减少长请求被网关断开的情况。

## 流程与结果

每个阶段的完整结果保存在 `--output` 指定目录下。阶段名可用于 `--from-stage` 和 `--to-stage`，大小写均可，不能用数字代替。

| 阶段 | 阶段名 | 内容与主要产物 |
| --- | --- | --- |
| 1 | `TOPIC_INIT` | 明确研究目标和约束：`stage-01/goal.md` |
| 2 | `PROBLEM_DECOMPOSE` | 拆分和排序子问题：`stage-02/problem_tree.md` |
| 3 | `SEARCH_STRATEGY` | 制定检索计划：`stage-03/search_plan.yaml`、`sources.json`、`queries.json` |
| 4 | `LITERATURE_COLLECT` | 收集文献：`stage-04/candidates.jsonl`、`search_meta.json`，有引用时生成 `references.bib` |
| 5 | `LITERATURE_SCREEN` | 筛选相关文献：`stage-05/shortlist.jsonl`；常规审批关卡 |
| 6 | `KNOWLEDGE_EXTRACT` | 提取问题、方法、发现和局限：`stage-06/cards/` |
| 7 | `SYNTHESIS` | 综合文献、识别研究缺口：`stage-07/synthesis.md` |
| 8 | `HYPOTHESIS_GEN` | 生成研究假说：`stage-08/hypotheses.md` |

优先阅读 `stage-08/hypotheses.md` 和 `stage-07/synthesis.md`，再追溯到文献卡片与原文。第 8 阶段默认由同一个模型分别扮演创新者、务实者和质疑者，再综合各方方案；原始结果在 `stage-08/perspectives/`。高能物理提示词库使用相应的领域角色。

启用候选方案竞选时，候选和评审记录在 `stage-08/tournament/`。新颖性检查成功时生成 `stage-08/novelty_report.json`：它结合额外检索、关键词重合和标题相似度给出参考意见，不验证 idea 的学术新颖性，也不会按报告建议自动停止流程。

运行目录还包含：

- `checkpoint.json`：最后完成的阶段，供断点续跑使用。
- `pipeline_summary.json`：本次执行的阶段数、最终阶段和状态；分段运行或续跑后会更新。
- `stage-XX/decision.json`、`stage_health.json`：阶段状态、错误和耗时。
- `heartbeat.json`：最近更新的阶段和进程信息，并非定时心跳。
- `config.yaml`：输入 YAML 的原样副本；重复运行时新增 `config.resumed-*.yaml`。命令行覆盖的 topic、profile 不会写回这个副本。

学术检索失败时程序可能使用缓存、内置经典论文、模型生成的条目，甚至占位条目。检查 `stage-04/search_meta.json` 的 `real_search`、候选条目的 `source` 和 `is_placeholder`；`real_search: true` 只表示学术 API 或其缓存返回过文献，不代表每条候选都已核实。完成状态也不保证产物质量，筛选结果中的 `keep_reason` 会标明部分补入或模板生成的条目。

## 配置说明

配置文件默认按当前目录下的 `config.arc.yaml`、`config.yaml` 顺序查找，`--config` 显式指定时优先。下文“默认”指省略字段时的代码默认值，可能与示例文件不同。可选配置应合并到已有的同名 YAML 节点中，不要重复写两个 `llm:` 或 `prompts:`。

建议始终从仓库根目录运行：`--output`、知识库路径和提示词路径在运行时都相对于当前工作目录。`validate` 的知识库路径检查则以配置文件所在目录为基准；配置放在其它目录时，使用绝对路径可避免两者不一致。程序不会自动加载 `.env` 文件。

### 研究目标、领域与归档

- `project.name`：必填，项目名称，会进入研究目标提示词；不决定输出目录。
- `project.mode`：默认 `docs-first`，可选 `full-auto`、`semi-auto`、`docs-first`。未启用 HITL 时，`full-auto` 自动通过关卡，另两种模式都在关卡阻塞后结束当前进程。它们不会改变这 8 个阶段的范围。
- `project.profile`：默认空字符串，自动判断领域；填写 `ml_nlp`、`ml_vision`、`ml_generic`、`hep_ph` 等 ID 可固定领域。可用 ID 是 [领域配置目录](researchclaw/domains/profiles) 中 YAML 的文件名去掉扩展名。当前 CLI 为 `hep_ph` 选择高能物理提示词库，其余显式 profile 使用 ML 提示词库；有领域配置不等于有独立提示词库。
- `research.topic`：必填，研究方向与需求。可以用 YAML 的 `|` 写多行，把研究对象、问题、已有想法和约束写在这里。产物语言受提示词影响，没有独立的 `language` 配置。
- `research.domains`：默认 `[]`，领域提示列表，参与目标描述、领域识别和文献筛选；不决定检索来源。
- `research.quality_threshold`：默认 `0.0`，传给目标描述和文献筛选提示词的质量要求，程序不做数值阈值过滤。ML 筛选提示词要求输出 0–1 分数，上面的示例使用 `0.7`；仓库模板中的 `4.0` 没有对应的程序化换算。
- `research.daily_paper_count`：默认 `0`。不设置每日调度、不限制真实检索篇数；当前仅用于无模型目标文本和最终占位文献的数量。真实检索规模由 `literature_search` 控制。
- `knowledge_base.backend`：默认 `markdown`；`obsidian` 额外生成兼容 Obsidian 的标签、元数据和双向链接。
- `knowledge_base.root`：必填，归档目录，运行时自动创建，无需预先准备知识库。按 `questions`、`literature`、`findings`、`decisions` 分类写入完成阶段的摘录；每个文件最多摘录 5000 字符，目录型产物只记录文件列表。它不是检索输入库，完整内容仍在 `stage-XX/`。
- `knowledge_base.obsidian_vault`：默认空字符串，当前 CLI 未使用。使用 Obsidian 时直接将 `root` 指向所需目录。

### 模型接口

- `llm.provider`：默认 `openai-compatible`，决定协议适配。普通兼容接口可直接使用这个值；其它内置服务商见下表。
- `llm.base_url`：API 根地址，例如 `https://api.openai.com/v1`，不要追加 `/chat/completions` 或 `/responses`。除 ACP 外，配置校验要求该字段非空；显式填写的地址优先于服务商预设。
- `llm.proxy_url`：可选 HTTP 代理地址，例如 HTTP 或 mixed 端口可填写 `http://127.0.0.1:7890`。默认留空，沿用已有系统或环境代理设置。用于主模型和评审模型的 OpenAI 兼容接口及 Anthropic Messages 接口；文献检索与 ACP 使用各自的网络设置。OpenAI 兼容请求也遵循 `NO_PROXY` 中的绕过规则。
- `llm.wire_api`：默认 `chat_completions`；仅提供 Responses 接口的服务设为 `responses`。Anthropic 服务使用单独的 Messages 适配器。
- `llm.stream`：默认 `false`，仅控制 Chat Completions 的网络流式传输，程序收到完整响应后才交给阶段处理；不表示终端实时显示生成文本，也不启用 Responses 流式传输。
- `llm.api_key_env`：模型密钥所在的环境变量名称。除 `acp`、`ollama` 外，校验要求非空，即使已填写 `api_key`。
- `llm.api_key`：默认空字符串，直接填写的密钥优先于环境变量。建议留空使用环境变量，因为配置会被原样复制到输出目录。
- `llm.primary_model`：主模型 ID；留空时客户端使用 `gpt-4o`，建议显式填写。
- `llm.reasoning_effort`：默认空字符串，不发送该参数，使用服务端默认值。可选 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`，具体取决于模型支持。GPT-6 Astra 支持 `low` 至 `max`，例如填写 `reasoning_effort: "xhigh"`。该设置用于主模型、备用模型和评审模型的 OpenAI 兼容请求：Responses 发送 `reasoning.effort`，Chat Completions 发送 `reasoning_effort`。显式设置为非 `none` 的推理档位时不发送 `temperature`。Anthropic Messages 和 ACP 不使用此设置。
- `llm.fallback_models`：默认 `[]`，主模型调用失败后依次尝试的模型 ID，均使用主接口和密钥。开启多模型功能后还会参与生成角色的分配。
- `llm.timeout_sec`：默认 `600`，单次 HTTP 请求的超时秒数，不是整轮任务时限；重试和候选模型可能使总耗时更长。
- `llm.s2_api_key`：默认空字符串，Semantic Scholar 密钥。作为第 4 阶段的兼容配置，并单独传给第 8 阶段的新颖性检查；只配置 `literature_search.s2_api_key` 或 `S2_API_KEY` 不会自动传给第 8 阶段。
- `llm.notes`：默认空字符串，当前流程未使用。

OpenAI 兼容调用在阶段或调用方未显式指定输出预算时，不发送输出 token 上限参数。Anthropic Messages 要求提供预算，未指定时使用 4096 tokens。

以下是代码内置的服务商地址映射，不表示已验证当前模型可用性。模型 ID 和密钥需与所选服务匹配。

| `provider` | `base_url` | 协议 |
| --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | OpenAI 兼容 |
| `openrouter` | `https://openrouter.ai/api/v1` | OpenAI 兼容 |
| `deepseek` | `https://api.deepseek.com/v1` | OpenAI 兼容 |
| `atlascloud` | `https://api.atlascloud.ai/v1` | OpenAI 兼容 |
| `novita` | `https://api.novita.ai/openai` | OpenAI 兼容 |
| `minimax` | `https://api.minimaxi.com/v1` | OpenAI 兼容 |
| `minimax-global` | `https://api.minimax.io/v1` | OpenAI 兼容 |
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages |
| `kimi-anthropic` | `https://api.kimi.com/coding/` | Anthropic Messages |
| `minimax-anthropic` | `https://api.minimax.io/anthropic` | Anthropic Messages |
| `minimax-anthropic-cn` | `https://api.minimaxi.com/anthropic` | Anthropic Messages |
| `ollama` | `http://localhost:11434/v1` | OpenAI 兼容 |

Anthropic 兼容服务需要额外安装适配器依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[anthropic]"
```

使用 Ollama 时，先启动服务并下载模型，再将 `provider` 设为 `ollama`、`base_url` 设为上表地址、`api_key_env` 设为 `""`、`api_key` 设为 `"ollama"`，并填写本地模型 ID。这里的非空占位 key 用于让阶段执行器创建模型客户端。

也支持通过 ACP 调用本地 agent。需先安装 Node.js、`acpx`（`npm install -g acpx`）和目标 agent，并完成目标 agent 的认证。将主配置中的 `llm` 替换为：

```yaml
llm:
  provider: "acp"
  base_url: ""
  api_key_env: ""
  acp:
    agent: "claude"
    cwd: "."
    acpx_command: ""
    session_name: "researchclaw"
    timeout_sec: 1800
    max_turns: 1
```

`agent` 是交给 acpx 的 agent 名称；`cwd` 是它的工作目录；`acpx_command` 为空时自动寻找 acpx，也可填写可执行文件路径；`session_name` 是会话名；`timeout_sec` 是单次提示调用时限；`max_turns` 是每次调用允许的 agent 轮数。上面即这些字段的默认值。ACP 使用 agent 自身的模型配置，不使用普通 HTTP 模型的 `primary_model` 和模型回退链，也不创建独立的多模型评审面板。

### 文献与网页检索

`literature_search` 控制第 4 阶段的学术检索：

- `sources`：默认 `[openalex, semantic_scholar, arxiv]`，按顺序查询所有列出的来源并合并去重，并非前一个成功就停止。空列表会恢复默认来源，不能用来关闭检索。
- `max_results_per_query`：默认 `40`，每个查询、每个来源最多返回的数量，最小为 `1`。查询会扩展，因此它不是总文献数上限。
- `inter_query_delay_sec`：默认 `1.5`，不同查询之间的等待秒数，最小为 `0`；各来源还有各自的限速和重试。
- `openalex_email`：OpenAlex 请求附带的联系邮箱；代码默认为 `researchclaw@users.noreply.github.com`，可填自己的邮箱或留空。
- `openalex_api_key` / `openalex_api_key_env`：直接填写 OpenAlex 密钥，或从指定环境变量读取；默认分别为 `""` / `"OPENALEX_API_KEY"`，直接填写优先。
- `s2_api_key` / `s2_api_key_env`：Semantic Scholar 密钥和环境变量名，默认分别为 `""` / `"S2_API_KEY"`。读取优先级为此处的直接密钥 → `llm.s2_api_key` → 此处指定的环境变量。

这些学术 API 密钥不是本地配置校验的必填项；实际访问仍受服务端认证和限额约束。可在当前终端设置 `$env:OPENALEX_API_KEY` 和 `$env:S2_API_KEY`。检索缓存位于当前目录的 `.researchclaw_cache/literature/`，供来源调用失败时回读。

查询词和年份下限来自 `stage-03/queries.json`，不是 `research.domains` 或 `daily_paper_count`。若要精确控制，可先运行到 `SEARCH_STRATEGY`，编辑其中的 `queries` 和 `year_min`，再从 `LITERATURE_COLLECT` 开始。

`web_search` 是第 4 阶段的额外网页搜索、Google Scholar 搜索、网页正文抓取和 PDF 文本提取。安装可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,pdf]"
```

```yaml
web_search:
  enabled: true
  tavily_api_key: ""
  tavily_api_key_env: "TAVILY_API_KEY"
  enable_scholar: true
  enable_crawling: true
  enable_pdf_extraction: true
  max_web_results: 10
  max_scholar_results: 10
  max_crawl_urls: 5
```

上面是该节点的默认值。`enabled` 控制整项增强；三个 `enable_*` 分别控制 Scholar、网页抓取和 PDF 提取。`max_web_results` 控制每个网页查询的返回规模，`max_scholar_results` 控制 Scholar 查询规模，`max_crawl_urls` 控制抓取 URL 数量。Tavily 的直接密钥优先于环境变量；无可用 Tavily 时网页搜索尝试 DuckDuckGo。缺少可选库时，相应组件会尝试简单 HTTP 等回退或跳过。

成功取得的网页背景写入 `stage-04/web_context.md`，并给知识提取阶段补充上下文；这不是对所有候选论文逐篇阅读全文。当前文献综合最多读取按文件名排序的前 24 张卡片，增加检索数量不代表全部结果都进入最终推理。

### 第 8 阶段的多模型与候选竞选

默认 `debate_enabled: false`、`tournament_enabled: false`：主模型从多个角色提出方案，再综合。可在现有 `llm` 节点中加入：

```yaml
llm:
  reviewer_model: "YOUR_REVIEWER_MODEL_ID"
  reviewer_provider: ""
  reviewer_base_url: ""
  reviewer_api_key_env: ""
  reviewer_api_key: ""
  debate_enabled: true
  debate_rounds: 1
  tournament_enabled: false
  tournament_candidates: 3
```

- `reviewer_model`：评审模型，默认空字符串，空时用主模型评审。只有辩论或竞选路径会使用它；单独填写不改变默认多角色生成。
- `reviewer_provider`、`reviewer_base_url`：默认空字符串，继承主接口设置。若更换评审服务商，二者都应填写，因为主 `base_url` 的优先级高于评审服务商的预设地址。独立 Anthropic 评审可用 `anthropic` / `kimi-anthropic`；评审构造器目前没有为 MiniMax 的 Anthropic 预设建立 Messages 适配器。
- `reviewer_api_key`、`reviewer_api_key_env`：默认空字符串，依次尝试直接密钥、评审环境变量、主模型密钥。评审不使用 `fallback_models`；`wire_api`、`stream`、`timeout_sec` 继承主模型。
- `debate_enabled`：开启后，将主模型、评审模型 ID 和 `fallback_models` 去重后分配给角色，经历提案、相互反驳、评审和综合。**角色生成客户端都使用主接口和密钥**，因此这些 ID 必须能在主接口调用；评审客户端才使用独立评审接口。只有一个模型 ID 时仍是同模型辩论。
- `debate_rounds`：默认 `1`，额外反驳轮数；`0` 表示保留初始提案和评审，但不反驳。
- `tournament_enabled`：默认 `false`。启用且 `tournament_candidates >= 2` 时生成多份完整候选假说集合，由评审选出一份作为最终结果。它优先于辩论，不再执行反驳轮次；若同时开启 `debate_enabled`，仅复用其多模型列表生成候选。
- `tournament_candidates`：默认 `3`，候选假说集合数量，不是最终假说条数。

这些选项会增加模型调用。`ARC_DEBATE_ROUNDS`、`ARC_TOURNAMENT_CANDIDATES` 环境变量可覆盖相应数量；`ARC_ABL_DISABLE_DEBATE=1`、`ARC_ABL_DISABLE_TOURNAMENT=1` 分别将对应路径缩减为单角色、单候选。普通使用不需要设置这些变量。

### 自定义提示词

给阶段补充要求时，用 `prompts.extra_prompts`：键是小写阶段名，值是内联文本或一个已存在的 UTF-8 文件路径。文件不存在时会把路径字符串当作指令文本，所以先用 `info` 检查解析结果。

```yaml
prompts:
  custom_file: ""
  extra_prompts:
    search_strategy: "重点覆盖最近两年的直接相关工作，同时保留必要的奠基工作。"
    literature_screen: "只保留直接讨论长期 agent 记忆机制或记忆失效的工作。"
    synthesis: "说明每个研究缺口为什么尚未被现有方法解决。"
```

`custom_file` 默认 `""`，使用代码内置提示词；非空时读取指定 YAML，对已有模板按字段覆盖。第 1–7 阶段可覆盖 `stages.<小写阶段名>` 下的 `system`、`user`，保留 `{topic}` 等需要的模板变量，以及结构化输出要求。部分阶段还读取 `json_mode`、`max_tokens`；第 1、2 阶段并不将这两个设置传给模型。主配置不支持通用的 `llm.temperature` 或 `llm.max_tokens`，添加这些字段不会生效。

第 8 阶段走角色生成和子提示词，**不会使用 `stages.hypothesis_gen` 或 `extra_prompts.hypothesis_gen`**。例如，要调整默认路径的最终综合，将以下内容保存为 `idea-prompts.yaml`，并设置 `prompts.custom_file: "idea-prompts.yaml"`：

```yaml
sub_prompts:
  hypothesis_synthesize:
    user: |
      综合以下候选，保留最有价值的 2–4 个研究假说。
      用中文说明：要解决的问题、与已有工作的差异、方法机制、
      可检验的预测和失败条件。保留重要分歧，不要仅拼接候选。

      {perspectives}
```

辩论可覆盖 `sub_prompts.debate_rebuttal`，竞选可覆盖 `sub_prompts.tournament_rank`；修改竞选提示词时须保留内置要求的 JSON 排名输出格式。角色提案提示词在 [ML 提示词库](researchclaw/prompts/ml.py) 和 [高能物理提示词库](researchclaw/prompts/hep.py) 中，当前 YAML 覆盖器不提供角色定义入口。

## 分段运行、续跑与人工参与

新任务使用新的输出目录，并相应更改 `knowledge_base.root`。`--topic "..."` 可以临时覆盖 topic；不会修改 YAML。未指定 `--output` 时，会在 `artifacts/rc-<UTC 时间>-<topic 哈希>/` 创建运行目录，知识库目录仍由配置单独决定。

`--profile <ID>` 覆盖 `project.profile`。`--config`、`--topic`、`--output`、`--mode`、`--profile` 的简写分别为 `-c`、`-t`、`-o`、`-m`、`-p`。安装后也可直接使用 `researchclaw` 命令；`python -m researchclaw run --help` 可查看运行参数。

中断后，保持配置、工作目录和输出目录一致：

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --resume
```

续跑从最后完成阶段的下一阶段开始，不恢复某个阶段内部的模型调用。**不要对已经完成第 8 阶段的目录使用 `--resume`：当前实现会从第 1 阶段重新开始。** 显式 `--from-stage` 优先于 `--resume`；未指定输出目录时，程序只会按 topic 哈希寻找默认命名的已有运行，手动命名的目录应显式传入。

先审阅文献，再继续生成 idea：

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --to-stage LITERATURE_SCREEN
# 查看或编辑 stage-05/shortlist.jsonl 后继续
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --from-stage KNOWLEDGE_EXTRACT
```

`--to-stage` 包含指定阶段；`--from-stage` 要求输出目录里已有前置产物。重跑会覆盖同名产物，但不清理旧卡片或其它中间文件；要做独立对比时使用新目录。

给第 8 阶段加入具体反馈并重跑：

```powershell
.\.venv\Scripts\python.exe -m researchclaw guide ./artifacts/idea-01 --stage 8 --message "优先研究记忆更新导致的错误累积，并明确可区分的竞争解释。"
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --from-stage HYPOTHESIS_GEN
```

`guide` 写入阶段指导文件，不立即调用模型。当前第 8 阶段会读取它，在生成后额外调用模型修订假说；第 1–7 阶段的长期附加要求请使用 `prompts.extra_prompts`。

需要运行中交互时，使用 HITL（human in the loop）。先将 `security.hitl_required_stages` 设为 `[]`，让 HITL 单独处理审批，避免常规关卡留下 `blocked_approval` 状态；再运行：

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --mode gate-only
```

`--mode` 是 HITL 模式，覆盖 YAML 的 `hitl` 设置；启用 HITL 后会接管 `--auto-approve`。正常暂停时在运行终端按提示选择操作，需要保持交互式输入可用。

| `--mode` | 正常运行时的人工参与点 |
| --- | --- |
| `full-auto` | 禁用 HITL；常规关卡仍由 `project.mode` / `--auto-approve` 决定 |
| `gate-only` | 第 5 阶段后审批 |
| `checkpoint` / `thorough` | 第 2、6、8 阶段后审阅 |
| `step-by-step` / `learning` | 每个阶段后审阅 |
| `co-pilot` | 第 1、2、3 阶段后暂停，第 5、8 阶段审批，第 7、8 阶段可协作讨论 |
| `express` | 第 8 阶段后审批 |

也可在 YAML 中自定义需要暂停的阶段；使用此配置时不要再传 `--mode`，否则会被预设覆盖：

```yaml
security:
  hitl_required_stages: []
hitl:
  enabled: true
  mode: "custom"
  stage_policies:
    5:
      require_approval: true
    8:
      pause_before: true
      pause_after: true
      enable_collaboration: true
```

`hitl.enabled` 默认 `false`；`hitl.mode` 默认 `full-auto`，YAML 支持 `full-auto`、`gate-only`、`checkpoint`、`step-by-step`、`co-pilot`、`custom`。`stage_policies` 默认 `{}`，以阶段编号为键；显式策略替换该阶段的模式默认策略。`pause_before`、`pause_after`、`require_approval`、`enable_collaboration` 默认都为 `false`，分别控制执行前、执行后暂停、审批和协作入口。

`status` 可查看运行状态：

```powershell
.\.venv\Scripts\python.exe -m researchclaw status ./artifacts/idea-01
```

`approve <目录> --message "..."` 和 `reject <目录> --reason "..."` 写入 `hitl/response.json`，只供正在使用文件轮询的 HITL 会话读取；不能代替终端里正在等待的 `Action >` 输入，也不会重启已退出的进程。拒绝会停止当前流程，需要自行选择起始阶段重跑，不会自动回退执行。

脚本化干预使用 `--interventions interventions.json`，同时启用相应 HITL 模式或阶段策略。文件格式如下，键是阶段编号；仅在该阶段实际暂停时读取，未指定干预的暂停默认通过。环境变量 `HITL_INTERVENTIONS_FILE` 的优先级高于该命令行参数。

```json
{
  "interventions": {
    "5": {"action": "approve", "message": "保留这批文献"},
    "8": {"action": "inject", "guidance": "要求每个假说给出明确的失败条件"}
  }
}
```

执行后的 `inject` 只保存指导，不自动重新生成产物；要在第 8 阶段当次运行使用指导，应配置 `pause_before: true`，或事先执行 `guide`。

## 其它配置与当前接入范围

以下字段保留在配置结构中。说明它们的实际使用范围，可以避免把配置名误当成功能承诺。

- `runtime.timezone` 必填，但运行 ID 和时间戳仍使用 UTC。`runtime.max_parallel_tasks`（默认 `1`）、`approval_timeout_hours`（`12`）、`retry_limit`（`0`）均未控制当前 runner；阶段按顺序执行，阶段失败后停止，HTTP 请求自身的重试另行处理。
- `notifications.channel` 必填。`target`（默认 `""`）、`on_stage_start`（`false`）、`on_stage_fail`（`false`）、`on_gate_required`（`true`）是通知配置；CLI 使用记录型适配器，不会据此发送外部通知。终端阶段进度照常显示。
- `openclaw_bridge.use_cron`、`use_message`、`use_memory`、`use_sessions_spawn`、`use_web_fetch`、`use_browser` 默认均为 `false`。当前 CLI 未接入真实 OpenClaw 服务，开启这些字段不会建立真实调度、消息、持久记忆或浏览器连接；保持关闭即可。学术和网页检索不依赖这些开关。
- `security.hitl_required_stages` 默认 `[5]`，只筛选内置常规关卡，目前仅第 5 阶段有效；填入 `8` 不会新增关卡。`security.redact_sensitive_logs` 默认 `true`，当前没有自动脱敏实现，配置快照仍是原样复制。
- `skills.enabled`（默认 `true`）、`builtin_dir`（`""`）、`custom_dirs` / `external_dirs`（`[]`）、`auto_match`（`true`）、`max_skills_per_stage`（`3`）、`fallback_matching`（`true`）描述技能目录和匹配设置，但当前 8 阶段执行器未接入这个动态技能库。
- HITL 的 `notifications.on_pause` / `on_quality_drop` / `on_error`（默认 `true`）、`notifications.channels`（`[terminal]`）和 `collaboration.llm_model`（`""`）、`max_chat_turns`（`50`）、`save_chat_history`（`true`）目前没有驱动 CLI 的通知发送、协作模型选择或轮数限制；CLI 协作使用主模型。
- HITL 的 `timeouts.default_human_timeout_sec`（默认 `86400`）和 `timeouts.auto_proceed_on_timeout`（`false`）用于文件轮询等待，超时默认中止、设为 `true` 则通过；不为终端 `input()` 设置时限。单阶段策略中的 `human_timeout_sec` / `auto_proceed_on_timeout` 不控制这条文件等待路径。
- 其它 HITL 阶段策略字段 `auto_execute`、`stream_output`、`show_llm_calls`、`allow_edit_output`、`allow_inject_prompt`、`max_auto_retries` 未作为当前 CLI 的执行、流式显示、权限或自动重试开关。`min_quality_score` 只在已有 PRM 报告时参与暂停原因判断，不会自动创建评分模型。
- `hitl.cost_budget_usd` 默认 `0`，表示不设预算提示；非零时检查费用记录。当前主流程没有完整的自动费用采集，不能将它当作 API 花费的硬上限。

### 可选 MetaClaw 桥接

不使用 MetaClaw 时保留 `metaclaw_bridge.enabled: false`。开启需要另外运行兼容的 MetaClaw 代理，不会由本仓库自动安装或启动。

- `enabled`：默认 `false`，开启桥接。
- `proxy_url`：默认 `http://localhost:30000`，主 OpenAI 兼容请求改发到此代理。Anthropic Messages 适配器仍直接连接原服务。
- `fallback_url` / `fallback_api_key`：默认空字符串；代理连接失败时使用的直连接口和密钥，未填写时沿用主模型原配置。
- `skills_dir`：默认 `~/.metaclaw/skills`，失败经验转成技能后的保存目录。
- `prm.enabled`：默认 `false`，启用独立模型质量评估；还需桥接总开关开启。`prm.api_base` 是支持 Chat Completions 的评审 API 根地址，`api_key` / `api_key_env` 指定密钥，直接密钥优先；三者代码默认均为空字符串。缺少地址或密钥时不创建评估器。
- `prm.model`：默认 `gpt-5.4`，评估模型 ID；`votes` 默认 `3`，重复评估的投票数；`temperature` 默认 `0.6`，评估采样温度；`gate_stages` 默认 `[5]`，需要评估的阶段编号。结果写入对应阶段的 `prm_score.json`，负面多数票会标记失败；评估调用出错时可能跳过。
- `lesson_to_skill.enabled`：默认 `true`，运行结束后将符合严重程度的经验交给模型转成技能；`min_severity` 默认 `warning`，可选 `info`、`warning`、`error`、`critical`；`max_skills_per_run` 默认 `3`，每轮最多生成的技能数。这部分也会调用模型。

## 常见问题

- **找不到配置或提示缺少字段**：先指定 `--config`；使用完整配置保留 `project.name`、`research.topic`、`runtime.timezone`、`notifications.channel`、`knowledge_base.root` 和模型接口必填项。校验不是严格 schema 检查，拼错的可选字段可能被忽略。
- **首次校验报知识库目录不存在**：加 `--no-check-paths`。`run` 会自动创建目录。
- **模型预检失败**：检查终端环境变量、模型 ID、接口根地址和 `wire_api`。401 / 403 通常需检查认证，404 需检查路径或模型，429 需检查限额。`--skip-preflight` 只跳过检查，不修复模型连接；缺少 key 时还可能进入模板生成路径。
- **文献检索慢或结果很少**：查看 `search_meta.json` 和候选来源，配置学术 API 密钥、调整 `sources`、查询词或 `inter_query_delay_sec`。关闭 `web_search.enabled` 可跳过额外网页访问，但第 8 阶段仍有单独的新颖性检索。
- **第 5 阶段暂停且 `screen_meta.json` 显示 `model_rejected_all`**：模型认为全部候选不相关。修改检索要求后用 `--from-stage SEARCH_STRATEGY` 重跑；仅再次自动审批不会产生合格文献。若第 6 阶段提示 `upstream_empty_shortlist`，同样先处理文献筛选。
- **阶段失败后没有按 `retry_limit` 自动重跑**：该字段未接入 runner。处理阶段元数据中的错误后，使用同一目录 `--resume` 或显式 `--from-stage`。
- **改了提示词却未生效**：检查文件路径和 `info` 输出；第 8 阶段使用上文的子提示词或 `guide`。已经完成的阶段需要显式重跑，编辑 YAML 不会自动重新生成历史结果。

配置加载在 [researchclaw/config.py](researchclaw/config.py)，命令入口在 [researchclaw/cli.py](researchclaw/cli.py)，阶段实现在 [researchclaw/pipeline/stage_impls](researchclaw/pipeline/stage_impls)。本仓库使用 [MIT License](LICENSE)。
