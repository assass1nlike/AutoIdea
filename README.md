# AutoResearchClaw

[中文说明](README.zh-CN.md)

Turn a research direction into literature-grounded research hypotheses. This repository retains the first 8 stages of AutoResearchClaw: problem framing, literature discovery, screening, synthesis, and idea generation. Its outputs include candidate proposals, research gaps, testable predictions, and failure conditions. The pipeline ends at hypothesis generation; it does not execute experiments or write a paper.

[Quick start](#install-and-run) · [Outputs](#pipeline-and-outputs) · [Configuration](#configuration-reference) · [Prompts](#customize-prompts) · [Resuming and review](#partial-runs-resuming-and-human-review) · [Other settings](#other-settings-and-integration-limits) · [Troubleshooting](#troubleshooting)

## Install and run

Requires Python 3.11+, access to a model API, and network access to academic search services. Remote models do not require a local GPU. Run the following commands from the repository root in Windows PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Commands below use the virtual environment's Python directly, so activation is unnecessary. On Linux / macOS, replace `.\.venv\Scripts\python.exe` with `./.venv/bin/python` and set environment variables with `export NAME="value"`.

Generate `config.arc.yaml` from the repository template:

```powershell
.\.venv\Scripts\python.exe -m researchclaw init
```

In an interactive terminal, `init` asks for a provider. It preserves an existing configuration unless you pass `--force`.

Alternatively, save this complete configuration as `config.arc.yaml`. Edit `research.topic`, `llm.base_url`, and `llm.primary_model`, then set your API key. Replace `YOUR_MODEL_ID` with a model ID available through your provider.

```yaml
project:
  name: "agent-memory"
  mode: "full-auto"
  profile: "ml_nlp"

research:
  topic: |
    Investigate memory failures in long-running LLM agents.
    Identify specific, valuable, unresolved problems and falsifiable hypotheses.
    Prefer proposals that distinguish existing methods and can be tested with public data.
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

This configuration enables academic API search and disables additional web search and human interaction. Optional capabilities are described below. The repository's [example configuration](config.researchclaw.example.yaml) uses different example values; `init` copies that file, not the configuration above.

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY"
$env:PYTHONUTF8 = "1"

.\.venv\Scripts\python.exe -m researchclaw validate --config config.arc.yaml --no-check-paths
.\.venv\Scripts\python.exe -m researchclaw info --config config.arc.yaml
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve
```

`validate` checks configuration without calling a model. Before the first run, use `--no-check-paths` because the knowledge-base directory does not exist yet. `info` shows the resolved domain, prompt bank, and additional guidance. `run` makes a model preflight request, then executes the 8 stages in order. `--auto-approve` passes ordinary approval gates; conditions such as an empty literature shortlist can still pause the pipeline.

For SudoRelay, set `base_url` to `https://api.sudorelay.com/v1` and choose a model supported by that service. For gateways supporting streamed Chat Completions, `stream: true` can help keep long requests from being disconnected by the gateway.

## Pipeline and outputs

Complete artifacts are written under `--output`. Use the stage names below with `--from-stage` and `--to-stage`; names are case-insensitive, but numeric stage IDs are not accepted by these two options.

| Stage | Name | Purpose and primary output |
| --- | --- | --- |
| 1 | `TOPIC_INIT` | Research goal and constraints: `stage-01/goal.md` |
| 2 | `PROBLEM_DECOMPOSE` | Prioritized subproblems: `stage-02/problem_tree.md` |
| 3 | `SEARCH_STRATEGY` | Search plan: `stage-03/search_plan.yaml`, `sources.json`, `queries.json` |
| 4 | `LITERATURE_COLLECT` | Papers: `stage-04/candidates.jsonl`, `search_meta.json`, and `references.bib` when references are available |
| 5 | `LITERATURE_SCREEN` | Selected papers: `stage-05/shortlist.jsonl`; ordinary approval gate |
| 6 | `KNOWLEDGE_EXTRACT` | Evidence cards describing problems, methods, findings, and limitations: `stage-06/cards/` |
| 7 | `SYNTHESIS` | Literature synthesis and research gaps: `stage-07/synthesis.md` |
| 8 | `HYPOTHESIS_GEN` | Research hypotheses: `stage-08/hypotheses.md` |

Start with `stage-08/hypotheses.md` and `stage-07/synthesis.md`, then trace claims back to the cards and original papers. By default, Stage 8 uses one model as an innovator, pragmatist, and contrarian, then synthesizes their proposals. Individual proposals are saved in `stage-08/perspectives/`. The high-energy physics prompt bank uses domain-specific roles.

When tournament selection is enabled, candidates and judging records are saved in `stage-08/tournament/`. A successful novelty check produces `stage-08/novelty_report.json`. This report uses additional search, keyword overlap, and title similarity as a heuristic; it does not establish scientific novelty or automatically stop the pipeline based on its recommendation.

Other run files include:

- `checkpoint.json`: the last completed stage, used to resume an interrupted run.
- `pipeline_summary.json`: stages executed and final status for the current invocation; updated after partial runs and resumes.
- `stage-XX/decision.json` and `stage_health.json`: stage status, errors, and timing.
- `heartbeat.json`: recently updated stage and process information, not a periodic heartbeat.
- `config.yaml`: a verbatim copy of the input YAML. Later invocations add `config.resumed-*.yaml`. CLI topic and profile overrides are not written into this copy.

If academic search fails, the pipeline may use cached papers, built-in seminal papers, model-generated entries, or placeholders. Inspect `real_search` in `stage-04/search_meta.json`, along with candidate `source` and `is_placeholder` fields. `real_search: true` only means academic APIs or their caches returned papers; it does not verify every candidate. Completion also does not establish output quality: shortlist `keep_reason` values identify some supplemented or template-generated entries.

## Configuration reference

Without `--config`, configuration is searched for in the current directory, first `config.arc.yaml`, then `config.yaml`. Defaults below are the values used when fields are omitted, which may differ from the example file. Merge optional snippets into existing YAML sections rather than adding duplicate `llm:` or `prompts:` keys.

Run from the repository root consistently. At runtime, relative output, knowledge-base, and prompt paths resolve from the current working directory. The `validate` knowledge-base path check instead resolves from the configuration file's directory. Use absolute paths when keeping configuration elsewhere to avoid this discrepancy. `.env` files are not loaded automatically.

### Research scope and archiving

- `project.name`: required project label, included in the goal prompt. It does not determine the output directory.
- `project.mode`: defaults to `docs-first`; accepts `full-auto`, `semi-auto`, or `docs-first`. Without HITL, `full-auto` automatically passes ordinary gates; both other modes block at a gate and end the current process. These modes do not change the 8-stage scope.
- `project.profile`: defaults to `""` for automatic domain detection. Set an ID such as `ml_nlp`, `ml_vision`, `ml_generic`, or `hep_ph` to fix the domain. IDs are YAML filenames without the extension in [domain profiles](researchclaw/domains/profiles). The current CLI selects the HEP prompt bank for `hep_ph` and the ML bank for other explicit profiles; a profile does not imply a separate prompt bank.
- `research.topic`: required research direction and instructions. Use YAML `|` for multiple lines describing the research object, question, existing ideas, and constraints. Output language depends on prompts; there is no separate `language` setting.
- `research.domains`: defaults to `[]`; domain hints used in goal framing, domain detection, and screening. These do not select search backends.
- `research.quality_threshold`: defaults to `0.0`; a value passed to goal and screening prompts, not a numeric filter enforced by code. ML screening asks for scores in 0–1, so the configuration above uses `0.7`. The repository template's `4.0` has no corresponding conversion in code.
- `research.daily_paper_count`: defaults to `0`. It does not schedule daily runs or limit real search results. It only affects the no-model goal text and final placeholder-paper count. Use `literature_search` to control real search volume.
- `knowledge_base.backend`: defaults to `markdown`; `obsidian` adds Obsidian-compatible tags, metadata, and wiki links.
- `knowledge_base.root`: required archive directory, created automatically. Completed-stage excerpts are grouped into `questions`, `literature`, `findings`, and `decisions`. Each file contributes at most 5000 characters; directory artifacts contribute a file listing. No existing knowledge base is needed. This archive is not retrieved as research input; full artifacts remain in `stage-XX/`.
- `knowledge_base.obsidian_vault`: defaults to `""`; unused by the current CLI. Point `root` at the desired vault directory instead.

### Model connections

- `llm.provider`: defaults to `openai-compatible`; selects the protocol adapter. Use this value for a custom compatible service, or a built-in provider below.
- `llm.base_url`: API root, such as `https://api.openai.com/v1`, without `/chat/completions` or `/responses`. Validation requires a nonempty value except for ACP. An explicit URL overrides the provider preset.
- `llm.proxy_url`: optional HTTP proxy URL, such as `http://127.0.0.1:7890` for an HTTP or mixed proxy port. Defaults to `""`, using the existing system/environment proxy settings. Applies to the main and reviewer models via OpenAI-compatible and Anthropic Messages clients; literature search and ACP keep their own network settings. OpenAI-compatible requests also respect `NO_PROXY` exclusions.
- `llm.wire_api`: defaults to `chat_completions`; use `responses` for a Responses-only service. Anthropic providers use a separate Messages adapter.
- `llm.stream`: defaults to `false`; enables Chat Completions network streaming. The client assembles the complete response before returning it to a stage. This does not stream generated text to the terminal or enable Responses streaming.
- `llm.api_key_env`: the environment variable containing the model key. Required by validation except for `acp` and `ollama`, even when `api_key` is populated.
- `llm.api_key`: defaults to `""`. A direct key takes precedence over the environment variable. Prefer the environment variable because configuration is copied verbatim into the run directory.
- `llm.primary_model`: the main model ID. The client uses `gpt-4o` if empty; set it explicitly.
- `llm.reasoning_effort`: defaults to `""`, which omits the parameter and uses the server default. Accepts `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`, subject to model support. GPT-6 Astra supports `low` through `max`; for example, set `reasoning_effort: "xhigh"`. Applies to the main, fallback, and reviewer models using OpenAI-compatible requests: `reasoning.effort` for Responses and `reasoning_effort` for Chat Completions. Explicit reasoning levels other than `none` omit `temperature`. Anthropic Messages and ACP do not use this setting.
- `llm.fallback_models`: defaults to `[]`; model IDs tried in order after the primary fails, all using the main endpoint and key. These IDs also participate in role assignment when multi-model generation is enabled.
- `llm.timeout_sec`: defaults to `600`; timeout in seconds for an individual HTTP request, not the entire run. Retries and fallback models can extend total elapsed time.
- `llm.s2_api_key`: defaults to `""`; a compatibility setting for Semantic Scholar in Stage 4, also passed separately to Stage 8 novelty checking. Setting only `literature_search.s2_api_key` or `S2_API_KEY` does not pass that key to Stage 8.
- `llm.notes`: defaults to `""`; unused by this pipeline.

OpenAI-compatible calls omit the output token limit unless a stage or caller explicitly supplies a budget. Anthropic Messages requires a budget and defaults to 4096 tokens when none is supplied.

These are endpoint mappings built into the repository, not a statement that particular models have been tested against the services. Match the model ID and key to the chosen service.

| `provider` | `base_url` | Protocol |
| --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | OpenAI-compatible |
| `openrouter` | `https://openrouter.ai/api/v1` | OpenAI-compatible |
| `deepseek` | `https://api.deepseek.com/v1` | OpenAI-compatible |
| `atlascloud` | `https://api.atlascloud.ai/v1` | OpenAI-compatible |
| `novita` | `https://api.novita.ai/openai` | OpenAI-compatible |
| `minimax` | `https://api.minimaxi.com/v1` | OpenAI-compatible |
| `minimax-global` | `https://api.minimax.io/v1` | OpenAI-compatible |
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages |
| `kimi-anthropic` | `https://api.kimi.com/coding/` | Anthropic Messages |
| `minimax-anthropic` | `https://api.minimax.io/anthropic` | Anthropic Messages |
| `minimax-anthropic-cn` | `https://api.minimaxi.com/anthropic` | Anthropic Messages |
| `ollama` | `http://localhost:11434/v1` | OpenAI-compatible |

Install the optional adapter dependency for Anthropic-compatible services:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[anthropic]"
```

For Ollama, start the server and pull your model first. Set `provider: ollama`, use the local URL above, set `api_key_env: ""` and `api_key: "ollama"`, and supply the installed model ID. The nonempty placeholder key lets the stage executor create the model client.

ACP can call a local agent instead. Install Node.js, `acpx` (`npm install -g acpx`), and your target agent, and complete the agent's authentication. Replace the main `llm` section with:

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

`agent` is the agent name passed to acpx; `cwd` is its working directory; `acpx_command` is an optional executable path, otherwise discovered automatically; `session_name` names the session; `timeout_sec` is the per-prompt timeout; `max_turns` limits agent turns per call. Values shown are the defaults. ACP uses the agent's own model configuration, not the HTTP `primary_model` and fallback chain, and does not create an independent multi-model reviewer panel.

### Academic and web search

`literature_search` controls academic search in Stage 4:

- `sources`: defaults to `[openalex, semantic_scholar, arxiv]`. All listed sources are queried in order, then results are merged and deduplicated. Success from one source does not skip the rest. An empty list restores the defaults rather than disabling search.
- `max_results_per_query`: defaults to `40`, minimum `1`; maximum results per query per source. Queries are expanded, so this is not a limit on the total paper count.
- `inter_query_delay_sec`: defaults to `1.5`, minimum `0`; delay between queries. Individual sources also have their own rate limits and retries.
- `openalex_email`: contact email attached to OpenAlex requests. The code default is `researchclaw@users.noreply.github.com`; use your own email or leave it empty.
- `openalex_api_key` / `openalex_api_key_env`: direct OpenAlex key or the environment variable to read. Defaults are `""` / `"OPENALEX_API_KEY"`; a direct key takes precedence.
- `s2_api_key` / `s2_api_key_env`: Semantic Scholar key and environment variable. Defaults are `""` / `"S2_API_KEY"`. Precedence is the direct key here, then `llm.s2_api_key`, then the configured environment variable.

These academic API keys are optional for local configuration validation; actual access remains subject to service authentication and quotas. Set `$env:OPENALEX_API_KEY` and `$env:S2_API_KEY` as needed. The academic cache is stored at `.researchclaw_cache/literature/` under the working directory and consulted when a source call fails.

Queries and the minimum year come from `stage-03/queries.json`, not `research.domains` or `daily_paper_count`. For precise control, stop after `SEARCH_STRATEGY`, edit `queries` and `year_min` in that file, then start from `LITERATURE_COLLECT`.

`web_search` adds web search, Google Scholar, web-page crawling, and PDF text extraction to Stage 4. Install the optional dependencies:

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

These are the section defaults. `enabled` controls all augmentation; the three `enable_*` fields control Scholar, crawling, and PDF extraction respectively. `max_web_results` sets the result count per web query, `max_scholar_results` the Scholar query count, and `max_crawl_urls` the number of URLs to crawl. A direct Tavily key takes precedence over its environment variable. Without usable Tavily search, web search attempts DuckDuckGo. Missing optional libraries cause components to use simpler HTTP fallbacks or skip the capability.

Retrieved web context is saved to `stage-04/web_context.md` and supplements knowledge extraction. This is not a full-text read of every candidate paper. Synthesis currently reads at most the first 24 cards sorted by filename, so increasing search volume does not put every result into the final reasoning context.

### Multi-model debate and candidate selection

By default, `debate_enabled` and `tournament_enabled` are both `false`: one model generates multiple role perspectives, then synthesizes them. Merge the following into your existing `llm` section to enable debate:

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

- `reviewer_model`: judge model, default `""`, which reuses the main model. Only debate and tournament paths use it; setting it alone does not change the default multi-perspective path.
- `reviewer_provider` / `reviewer_base_url`: default `""`, inheriting the main connection. Set both when switching reviewer providers because the main URL takes precedence over the reviewer provider's preset. Independent Anthropic reviewing supports `anthropic` / `kimi-anthropic`; the reviewer constructor does not currently attach a Messages adapter for MiniMax Anthropic presets.
- `reviewer_api_key` / `reviewer_api_key_env`: default `""`. Keys are resolved from the direct reviewer key, then its environment variable, then the main model key. The reviewer has no fallback models and inherits the main `wire_api`, `stream`, and `timeout_sec`.
- `debate_enabled`: assigns roles across deduplicated IDs from `primary_model`, `reviewer_model`, and `fallback_models`, then runs proposals, rebuttals, judging, and synthesis. **All role-generation clients use the main endpoint and key.** Every panel ID must be callable there; only the judging client uses an independent reviewer connection. A single available ID still produces a single-model debate.
- `debate_rounds`: defaults to `1`; additional rebuttal rounds. `0` keeps proposals and judging but omits rebuttals.
- `tournament_enabled`: defaults to `false`. When enabled with `tournament_candidates >= 2`, generates several complete hypothesis sets and selects one through judging. This takes precedence over debate and does not run rebuttals. If `debate_enabled` is also true, it only supplies the multi-model generator list to the tournament.
- `tournament_candidates`: defaults to `3`; number of candidate hypothesis sets, not the number of final hypotheses.

These options increase model calls. Environment variables `ARC_DEBATE_ROUNDS` and `ARC_TOURNAMENT_CANDIDATES` override the respective counts. `ARC_ABL_DISABLE_DEBATE=1` and `ARC_ABL_DISABLE_TOURNAMENT=1` collapse their paths to a single role or candidate. Normal use does not require these variables.

### Customize prompts

Use `prompts.extra_prompts` to append instructions. Keys are lowercase stage names; values are inline text or paths to existing UTF-8 files. If a file does not exist, its path string is treated as literal guidance, so check resolution with `info`.

```yaml
prompts:
  custom_file: ""
  extra_prompts:
    search_strategy: "Prioritize directly related work from the last two years, retaining essential foundational work."
    literature_screen: "Keep work directly addressing long-running agent memory mechanisms or memory failures."
    synthesis: "Explain why each research gap remains unresolved by existing methods."
```

`custom_file` defaults to `""`, using code-defined prompts. A nonempty path loads a YAML file and overrides existing templates field by field. For Stages 1–7, override `system` and `user` under `stages.<lowercase_stage_name>`, retaining necessary variables such as `{topic}` and required structured output formats. Some stages also honor `json_mode` and `max_tokens`; Stages 1 and 2 do not pass these two settings to the model. The main configuration does not support general `llm.temperature` or `llm.max_tokens` settings; adding them has no effect.

Stage 8 uses role generation and sub-prompts, **not `stages.hypothesis_gen` or `extra_prompts.hypothesis_gen`**. To change final synthesis in the default path, save this as `idea-prompts.yaml` and set `prompts.custom_file: "idea-prompts.yaml"`:

```yaml
sub_prompts:
  hypothesis_synthesize:
    user: |
      Synthesize the candidates into the 2-4 most valuable research hypotheses.
      For each, explain the problem, difference from existing work, mechanism,
      testable prediction, and failure condition. Preserve important disagreements.

      {perspectives}
```

Debate supports `sub_prompts.debate_rebuttal`; tournaments support `sub_prompts.tournament_rank`. Preserve the required JSON ranking format when editing the tournament prompt. Role proposal prompts live in the [ML prompt bank](researchclaw/prompts/ml.py) and [HEP prompt bank](researchclaw/prompts/hep.py); the YAML override loader does not expose role definitions.

## Partial runs, resuming, and human review

Use a new output directory for each new task, and update `knowledge_base.root` accordingly. `--topic "..."` overrides the topic without modifying YAML. Without `--output`, a directory named `artifacts/rc-<UTC timestamp>-<topic hash>/` is created. The knowledge-base path is still configured separately.

`--profile <ID>` overrides `project.profile`. Short forms for `--config`, `--topic`, `--output`, `--mode`, and `--profile` are `-c`, `-t`, `-o`, `-m`, and `-p`. The installed package also exposes the `researchclaw` command; use `python -m researchclaw run --help` to inspect run options.

After an interruption, keep the same configuration, working directory, and output directory:

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --resume
```

Resume starts after the last completed stage, not in the middle of a stage's model calls. **Do not use `--resume` on a run that has already completed Stage 8: the current implementation restarts from Stage 1.** An explicit `--from-stage` takes precedence over `--resume`. Without an output path, discovery only finds default-named runs matching the topic hash; specify manually named directories explicitly.

To inspect the literature before continuing:

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --to-stage LITERATURE_SCREEN
# Inspect or edit stage-05/shortlist.jsonl, then continue
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --from-stage KNOWLEDGE_EXTRACT
```

`--to-stage` includes the named stage. `--from-stage` requires its upstream artifacts in the output directory. Reruns overwrite matching files but do not remove old cards or other intermediate files; use new directories for independent comparisons.

To apply feedback to Stage 8 and rerun it:

```powershell
.\.venv\Scripts\python.exe -m researchclaw guide ./artifacts/idea-01 --stage 8 --message "Prioritize error accumulation caused by memory updates and distinguish competing explanations."
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --auto-approve --from-stage HYPOTHESIS_GEN
```

`guide` writes stage guidance without calling a model. Stage 8 reads it and makes an additional refinement call after generation. For persistent instructions in Stages 1–7, use `prompts.extra_prompts`.

For interactive review, use HITL (human in the loop). First set `security.hitl_required_stages: []` so HITL alone handles approval, avoiding an ordinary gate leaving a `blocked_approval` status. Then run:

```powershell
.\.venv\Scripts\python.exe -m researchclaw run --config config.arc.yaml --output ./artifacts/idea-01 --mode gate-only
```

`--mode` selects a HITL mode and overrides YAML `hitl` settings. Enabled HITL takes over approval even if `--auto-approve` is supplied. Respond at prompts in the running terminal; interactive input must remain available.

| `--mode` | Human review points during normal execution |
| --- | --- |
| `full-auto` | Disables HITL; ordinary gates still follow `project.mode` / `--auto-approve` |
| `gate-only` | Approval after Stage 5 |
| `checkpoint` / `thorough` | Review after Stages 2, 6, and 8 |
| `step-by-step` / `learning` | Review after every stage |
| `co-pilot` | Pause after Stages 1, 2, and 3; approval at 5 and 8; collaboration available at 7 and 8 |
| `express` | Approval after Stage 8 |

Alternatively, configure custom review points in YAML. Omit `--mode` when using this configuration, or the CLI preset will replace it:

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

`hitl.enabled` defaults to `false`; `hitl.mode` defaults to `full-auto`. YAML accepts `full-auto`, `gate-only`, `checkpoint`, `step-by-step`, `co-pilot`, and `custom`. `stage_policies` defaults to `{}` and uses numeric stage keys. An explicit policy replaces that stage's mode defaults. `pause_before`, `pause_after`, `require_approval`, and `enable_collaboration` all default to `false`, controlling pre-stage pauses, post-stage pauses, approval, and collaboration access.

Check run status with:

```powershell
.\.venv\Scripts\python.exe -m researchclaw status ./artifacts/idea-01
```

`approve <run_dir> --message "..."` and `reject <run_dir> --reason "..."` write `hitl/response.json` for a HITL session using file polling. They do not answer a terminal blocked at `Action >` or restart an exited process. Rejection stops the current pipeline; choose a stage to rerun yourself, as automatic rollback execution is not implemented.

For scripted input, pass `--interventions interventions.json` and enable the corresponding HITL mode or stage policy. Keys below are stage numbers. Entries are read only when a stage actually pauses; unspecified pauses are approved by default. The `HITL_INTERVENTIONS_FILE` environment variable takes precedence over the CLI argument.

```json
{
  "interventions": {
    "5": {"action": "approve", "message": "Keep this literature selection"},
    "8": {"action": "inject", "guidance": "Give each hypothesis an explicit failure condition"}
  }
}
```

Post-stage `inject` only saves guidance; it does not regenerate the output. For Stage 8 to use guidance in the same run, configure `pause_before: true` or run `guide` beforehand.

## Other settings and integration limits

The following settings remain in the configuration structure. Their actual use matters when deciding what to configure.

- `runtime.timezone` is required, but run IDs and timestamps still use UTC. `runtime.max_parallel_tasks` (default `1`), `approval_timeout_hours` (`12`), and `retry_limit` (`0`) do not control this runner. Stages execute sequentially and stop on failure; HTTP request retries are separate.
- `notifications.channel` is required. `target` (default `""`), `on_stage_start` (`false`), `on_stage_fail` (`false`), and `on_gate_required` (`true`) are notification settings, but the CLI uses recording adapters rather than sending external notifications. Terminal stage progress is still printed.
- `openclaw_bridge.use_cron`, `use_message`, `use_memory`, `use_sessions_spawn`, `use_web_fetch`, and `use_browser` all default to `false`. The CLI does not connect real OpenClaw services; these flags do not establish scheduling, messaging, persistent memory, or browser connections. Leave them off. Academic and web search do not depend on these switches.
- `security.hitl_required_stages` defaults to `[5]` and only filters built-in ordinary gates. Only Stage 5 is a gate; adding `8` does not create one. `security.redact_sensitive_logs` defaults to `true`, but automatic redaction is not implemented and configuration snapshots remain verbatim copies.
- `skills.enabled` (default `true`), `builtin_dir` (`""`), `custom_dirs` / `external_dirs` (`[]`), `auto_match` (`true`), `max_skills_per_stage` (`3`), and `fallback_matching` (`true`) describe skill directories and matching, but this dynamic skill library is not wired into the 8-stage executor.
- HITL `notifications.on_pause` / `on_quality_drop` / `on_error` (default `true`), `notifications.channels` (`[terminal]`), and `collaboration.llm_model` (`""`), `max_chat_turns` (`50`), and `save_chat_history` (`true`) do not drive CLI notification delivery, collaboration model selection, or turn limits. CLI collaboration uses the main model.
- HITL `timeouts.default_human_timeout_sec` (default `86400`) and `timeouts.auto_proceed_on_timeout` (`false`) control file-polling waits: timeout aborts by default, or approves when auto-proceed is enabled. They do not time out terminal `input()`. Per-stage `human_timeout_sec` / `auto_proceed_on_timeout` do not control this file-wait path.
- Other HITL policy fields `auto_execute`, `stream_output`, `show_llm_calls`, `allow_edit_output`, `allow_inject_prompt`, and `max_auto_retries` are not enforced as CLI execution, streaming, permission, or automatic retry switches. `min_quality_score` only helps label the pause reason when a PRM report exists; it does not create a scoring model.
- `hitl.cost_budget_usd` defaults to `0`, disabling budget alerts. Nonzero values check cost records, but the main pipeline does not provide complete automatic cost collection. This is not a hard API spending cap.

### Optional MetaClaw bridge

Leave `metaclaw_bridge.enabled: false` unless using a separately running compatible MetaClaw proxy. This repository does not install or start that service.

- `enabled`: defaults to `false`; enables the bridge.
- `proxy_url`: defaults to `http://localhost:30000`; redirects main OpenAI-compatible requests to the proxy. Anthropic Messages adapters continue to use the original service directly.
- `fallback_url` / `fallback_api_key`: default `""`; direct connection and key used if the proxy connection fails. Empty values reuse the original main-model settings.
- `skills_dir`: defaults to `~/.metaclaw/skills`; destination for skills generated from failure lessons.
- `prm.enabled`: defaults to `false`; enables independent model quality evaluation and also requires the bridge to be enabled. `prm.api_base` is a Chat Completions API root; `api_key` / `api_key_env` supply the key, direct value first. These three fields default to `""`. No evaluator is created without a URL and key.
- `prm.model`: defaults to `gpt-5.4`, the judge model ID. `votes` defaults to `3` repeated evaluations; `temperature` to `0.6`; `gate_stages` to `[5]`, the stage numbers to evaluate. Reports are written to each stage's `prm_score.json`. A negative majority marks failure; evaluation errors may be skipped.
- `lesson_to_skill.enabled`: defaults to `true`; converts eligible lessons to skills through a model after the run. `min_severity` defaults to `warning` and accepts `info`, `warning`, `error`, or `critical`. `max_skills_per_run` defaults to `3`. This also consumes model calls.

## Troubleshooting

- **Missing configuration or required fields:** specify `--config` and retain `project.name`, `research.topic`, `runtime.timezone`, `notifications.channel`, `knowledge_base.root`, and required model connection settings. Validation is not a strict schema check; misspelled optional keys may be ignored.
- **Knowledge-base directory missing during initial validation:** use `--no-check-paths`. `run` creates the directory automatically.
- **Model preflight fails:** check environment variables, model ID, API root, and `wire_api`. Check authentication for 401 / 403, path or model availability for 404, and quotas for 429. `--skip-preflight` only skips the check; it does not fix connectivity and can allow template generation when a key is missing.
- **Slow or sparse literature search:** inspect `search_meta.json` and candidate sources; configure academic API keys or adjust sources, queries, and query delay. Disabling `web_search.enabled` skips web augmentation, but Stage 8 still performs its own novelty search.
- **Stage 5 pauses with `model_rejected_all` in `screen_meta.json`:** the model rejected every candidate. Refine search instructions and rerun with `--from-stage SEARCH_STRATEGY`. Automatic approval alone does not produce suitable literature. A Stage 6 `upstream_empty_shortlist` report likewise requires resolving screening first.
- **Failed stages do not retry according to `retry_limit`:** that setting is not wired into the runner. Resolve the error in stage decision metadata, then use `--resume` or an explicit `--from-stage` in the same directory.
- **Prompt changes have no effect:** check paths and `info` output. Stage 8 uses the sub-prompts or `guide` described above. Completed stages must be rerun explicitly; editing YAML does not regenerate existing outputs.

Configuration loading is in [researchclaw/config.py](researchclaw/config.py), CLI commands in [researchclaw/cli.py](researchclaw/cli.py), and stage implementations in [researchclaw/pipeline/stage_impls](researchclaw/pipeline/stage_impls). Licensed under the [MIT License](LICENSE).
