from __future__ import annotations

import argparse
import os
from pathlib import Path

from memory_claw.adapters.claude_adapter import ClaudeTranscriptAdapter
from memory_claw.adapters.pi_adapter import PiTranscriptAdapter
from memory_claw.config.loader import dump_config_yaml, load_config
from memory_claw.config.models import AppConfig
from memory_claw.domain.memory_doc import default_global_memory_markdown
from memory_claw.eval.harness import EvaluationHarness
from memory_claw.io.cost_ledger import append_cost_entry, summarize_costs
from memory_claw.io.fs_paths import Paths
from memory_claw.io.git_ops import commit_if_dirty, ensure_repo_initialized
from memory_claw.pipeline.extractor_runner import ExtractorRunner
from memory_claw.pipeline.reflector import Reflector, ReflectorRunResult
from memory_claw.pipeline.scheduler import Scheduler
from memory_claw.pipeline.watcher import Watcher
from memory_claw.store.db import init_schema, open_db
from memory_claw.store.repositories import StateRepository


def _default_memory_root() -> Path:
    env_value = os.getenv("MEMORY_CLAW_ROOT")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return Path("~/.memory-claw").expanduser().resolve()


def _resolve_root(memory_root_arg: str | None) -> Path:
    if memory_root_arg:
        return Path(memory_root_arg).expanduser().resolve()
    return _default_memory_root()


def _ensure_bootstrap_files(paths: Paths, config: AppConfig) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.prompts_dir.mkdir(parents=True, exist_ok=True)
    paths.observations_dir.mkdir(parents=True, exist_ok=True)

    if not paths.config.exists():
        paths.config.write_text(dump_config_yaml(config))

    if not paths.global_memory.exists():
        paths.global_memory.write_text(default_global_memory_markdown())

    if not paths.gitignore.exists():
        paths.gitignore.write_text("state.db\n")

    pairwise_prompt = paths.prompts_dir / "pairwise-v2.md"
    if not pairwise_prompt.exists():
        pairwise_prompt.write_text(
            "Observer guidance override:\n"
            "- Prioritize durable behavior signals over task-progress chatter.\n"
            "- Prefer repeated preferences, corrections, and redirections that will matter in future sessions.\n"
            "- Keep each observation specific and grounded in the provided messages and context.\n"
            "\n"
            "Signal taxonomy starter set:\n"
            "- preference:reinforced\n"
            "- correction\n"
            "- redirection\n"
            "- elaboration\n"
            "- approval_with_caveat\n"
            "- focus_shift\n"
            "\n"
            "Importance rubric:\n"
            "- 🔴 high-signal and likely durable across future sessions\n"
            "- 🟡 useful but less stable or more local to current work\n"
            "- 🟢 weak/local signal worth keeping as low-confidence context\n"
            "\n"
            "Formatting contract:\n"
            "- Output one line per observation: - <importance> [signal_type] summary | why: reason\n"
            "- You may emit multiple observations for a single user message when distinct signals exist\n"
            "- No bullets without tags, no prose preamble, no JSON\n"
            "- If no meaningful signal exists, return exactly: (none)\n"
            "\n"
            "Good examples:\n"
            "- 🔴 [preference:reinforced] User repeatedly asks for behavior-first specs and separate implementation design docs. | why: values stable separation between behavior expectations and implementation details.\n"
            "- 🟡 [correction] User asks to read existing files before proposing edits. | why: wants changes grounded in current code reality.\n"
            "\n"
            "Bad examples:\n"
            "- user seems smart and careful\n"
            "- [task] assistant ran commands\n"
            "- 🔴 [guess] user is probably frustrated\n"
        )

    reflector_prompt = paths.prompts_dir / "reflector-v1.md"
    if not reflector_prompt.exists():
        reflector_prompt.write_text(
            "Reflector guidance override:\n"
            "- Consolidate recent observations conservatively into global memory.\n"
            "- Promote to Durable Preferences only when evidence appears repeated and stable.\n"
            "- Keep Active Context current without overclaiming confidence.\n"
            "\n"
            "Formatting contract:\n"
            "- Return full markdown only (no JSON, no code fences, no preamble).\n"
            "- First non-empty line must be '# Global Memory'.\n"
            "- Keep required sections exactly: Durable Preferences and Patterns, Active Context, Recent Observations.\n"
            "\n"
            "Quality guardrails:\n"
            "- Preserve useful continuity from prior memory when still valid.\n"
            "- Avoid generic fluff and avoid dropping concrete, source-grounded details.\n"
            "- If evidence is weak, keep it in active/recent context rather than durable memory.\n"
        )


def _load_runtime(memory_root_arg: str | None):
    root = _resolve_root(memory_root_arg)
    paths = Paths(root)

    if not paths.config.exists():
        raise SystemExit(f"config not found: {paths.config}. Run `memory-claw init` first.")

    config = load_config(paths.config)
    config.memory_root = str(root)

    conn = open_db(paths.state_db)
    init_schema(conn, paths.schema)
    repo = StateRepository(conn)

    adapters = {
        "pi": PiTranscriptAdapter(),
        "claude": ClaudeTranscriptAdapter(),
    }
    watcher = Watcher(config=config, repo=repo, adapters=adapters)
    extractors = ExtractorRunner(config=config, repo=repo, memory_root=root)
    reflector = Reflector(config=config, repo=repo, memory_root=root)

    return root, paths, config, repo, watcher, extractors, reflector


def _cmd_init(args: argparse.Namespace) -> int:
    root = _resolve_root(args.memory_root)
    config = AppConfig.default(memory_root=str(root))
    paths = Paths(root)

    _ensure_bootstrap_files(paths, config)
    ensure_repo_initialized(root)

    committed = commit_if_dirty(root, "init: bootstrap memory-claw workspace")
    print(f"initialized: {root}")
    if committed:
        print("created initial git commit")
    return 0


def _cmd_watcher_run(args: argparse.Namespace) -> int:
    _, _, _, _, watcher, _, _ = _load_runtime(args.memory_root)
    result = watcher.run_once()
    print(f"watcher: sessions={result.sessions_seen} messages={result.messages_ingested} errors={result.errors}")
    return 0 if result.errors == 0 else 1


def _cmd_extractors_run(args: argparse.Namespace) -> int:
    root, _, _, _, _, extractors, _ = _load_runtime(args.memory_root)
    result = extractors.run_once(only_extractor=args.extractor)
    append_cost_entry(
        root=root,
        stage="extractors",
        calls=result.llm_calls,
        prompt_tokens=result.llm_prompt_tokens,
        completion_tokens=result.llm_completion_tokens,
        total_tokens=result.llm_total_tokens,
        cost_usd=result.llm_cost_usd,
    )
    print(
        "extractors: "
        f"run={result.extractors_run} blocks={result.blocks_written} errors={result.errors} "
        f"llm_calls={result.llm_calls} llm_cost_usd={result.llm_cost_usd:.6f} "
        f"budget_hit={result.llm_budget_hit}"
    )
    return 0 if result.errors == 0 else 1


def _cmd_reflector_run(args: argparse.Namespace) -> int:
    root, _, _, _, _, _, reflector = _load_runtime(args.memory_root)
    result = reflector.run_once()
    append_cost_entry(
        root=root,
        stage="reflector",
        calls=result.llm_calls,
        prompt_tokens=result.llm_prompt_tokens,
        completion_tokens=result.llm_completion_tokens,
        total_tokens=result.llm_total_tokens,
        cost_usd=result.llm_cost_usd,
    )
    print(
        "reflector: "
        f"links={result.links_included} updated={result.updated} errors={result.errors} "
        f"llm_calls={result.llm_calls} llm_cost_usd={result.llm_cost_usd:.6f}"
    )
    return 0 if result.errors == 0 else 1


def _cmd_run_once(args: argparse.Namespace) -> int:
    root, _, _, _, watcher, extractors, reflector = _load_runtime(args.memory_root)
    w = watcher.run_once()
    e = extractors.run_once()

    reflector_skipped = e.errors > 0
    r = ReflectorRunResult()
    if not reflector_skipped:
        r = reflector.run_once()

    total_calls = e.llm_calls + r.llm_calls
    total_prompt = e.llm_prompt_tokens + r.llm_prompt_tokens
    total_completion = e.llm_completion_tokens + r.llm_completion_tokens
    total_tokens = e.llm_total_tokens + r.llm_total_tokens
    total_cost = e.llm_cost_usd + r.llm_cost_usd

    append_cost_entry(
        root=root,
        stage="run_once",
        calls=total_calls,
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        total_tokens=total_tokens,
        cost_usd=total_cost,
    )

    print(
        "run-once: "
        f"watcher(messages={w.messages_ingested}, errors={w.errors}) "
        f"extractors(blocks={e.blocks_written}, errors={e.errors}, llm_cost_usd={e.llm_cost_usd:.6f}) "
        f"reflector(updated={r.updated}, errors={r.errors}, skipped={reflector_skipped}, llm_cost_usd={r.llm_cost_usd:.6f}) "
        f"total_llm_cost_usd={total_cost:.6f}"
    )
    return 0 if (w.errors + e.errors + r.errors) == 0 else 1


def _cmd_run_daemon(args: argparse.Namespace) -> int:
    _, _, config, _, watcher, extractors, reflector = _load_runtime(args.memory_root)
    scheduler = Scheduler(watcher=watcher, extractors=extractors, reflector=reflector, cfg=config)
    scheduler.run_forever()
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    root, paths, _, repo, _, _, _ = _load_runtime(args.memory_root)
    counts = repo.fetch_counts()
    costs = summarize_costs(root)
    gm_exists = paths.global_memory.exists()
    gm_mtime = paths.global_memory.stat().st_mtime if gm_exists else 0
    print(f"memory_root: {root}")
    print(f"db: {paths.state_db}")
    print(f"sessions: {counts['sessions']}")
    print(f"messages: {counts['messages']}")
    print(f"extractor_progress: {counts['extractor_progress']}")
    print(f"global_memory_exists: {gm_exists}")
    print(f"global_memory_mtime: {gm_mtime}")
    print(f"cost_entries: {costs['entries']}")
    print(f"llm_calls_total: {costs['calls']}")
    print(f"llm_tokens_total: {costs['total_tokens']}")
    print(f"llm_cost_total_usd: {costs['cost_usd']:.6f}")
    return 0


def _cmd_eval_run(args: argparse.Namespace) -> int:
    root, _, config, repo, watcher, _, _ = _load_runtime(args.memory_root)
    watcher_result = watcher.run_once()

    harness = EvaluationHarness(config=config, repo=repo, memory_root=root)
    result = harness.run_sample(
        sample_size=args.sample_size,
        seed=args.seed,
        extractor_name=args.extractor,
        workers=args.workers,
    )

    append_cost_entry(
        root=root,
        stage="eval",
        calls=result.llm_calls,
        prompt_tokens=result.llm_prompt_tokens,
        completion_tokens=result.llm_completion_tokens,
        total_tokens=result.llm_total_tokens,
        cost_usd=result.llm_cost_usd,
    )

    print(
        "eval-run: "
        f"watcher(messages={watcher_result.messages_ingested}, errors={watcher_result.errors}) "
        f"observer_cases={result.observer_cases} observer_success={result.observer_success} "
        f"observer_errors={result.observer_errors} reflector_errors={result.reflector_errors} "
        f"llm_calls={result.llm_calls} llm_cost_usd={result.llm_cost_usd:.6f} "
        f"run_dir={result.run_dir}"
    )
    return 0 if (watcher_result.errors + result.observer_errors + result.reflector_errors) == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory-claw")
    parser.add_argument("--memory-root", help="Override memory root path")

    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Initialize ~/.memory-claw layout")
    init_cmd.set_defaults(func=_cmd_init)

    run_cmd = sub.add_parser("run", help="Run scheduled stages")
    run_sub = run_cmd.add_subparsers(dest="run_command", required=True)

    run_once_cmd = run_sub.add_parser("once", help="Run watcher + extractors + reflector once")
    run_once_cmd.set_defaults(func=_cmd_run_once)

    run_daemon_cmd = run_sub.add_parser("daemon", help="Run scheduler loop")
    run_daemon_cmd.set_defaults(func=_cmd_run_daemon)

    watcher_cmd = sub.add_parser("watcher", help="Watcher stage commands")
    watcher_sub = watcher_cmd.add_subparsers(dest="watcher_command", required=True)
    watcher_run_cmd = watcher_sub.add_parser("run", help="Run watcher once")
    watcher_run_cmd.set_defaults(func=_cmd_watcher_run)

    extractors_cmd = sub.add_parser("extractors", help="Extractor stage commands")
    extractors_sub = extractors_cmd.add_subparsers(dest="extractor_command", required=True)
    extractors_run_cmd = extractors_sub.add_parser("run", help="Run extractors")
    extractors_run_cmd.add_argument("--extractor", help="Run only one extractor by name")
    extractors_run_cmd.set_defaults(func=_cmd_extractors_run)

    reflector_cmd = sub.add_parser("reflector", help="Reflector stage commands")
    reflector_sub = reflector_cmd.add_subparsers(dest="reflector_command", required=True)
    reflector_run_cmd = reflector_sub.add_parser("run", help="Run reflector once")
    reflector_run_cmd.set_defaults(func=_cmd_reflector_run)

    status_cmd = sub.add_parser("status", help="Show pipeline state")
    status_cmd.set_defaults(func=_cmd_status)

    eval_cmd = sub.add_parser("eval", help="Evaluation commands")
    eval_sub = eval_cmd.add_subparsers(dest="eval_command", required=True)
    eval_run_cmd = eval_sub.add_parser("run", help="Run a sampled quality evaluation")
    eval_run_cmd.add_argument("--sample-size", type=int, default=12, help="Number of sampled observer cases")
    eval_run_cmd.add_argument("--seed", type=int, default=42, help="Sampling seed")
    eval_run_cmd.add_argument("--extractor", help="Extractor name to evaluate")
    eval_run_cmd.add_argument("--workers", type=int, default=8, help="Parallel worker threads across sessions")
    eval_run_cmd.set_defaults(func=_cmd_eval_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
