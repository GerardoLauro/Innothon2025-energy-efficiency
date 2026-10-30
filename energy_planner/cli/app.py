"""Interfaccia CLI per energy_planner."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv


logger = logging.getLogger(__name__)
_ENV_PATH = ""

from energy_planner.core.triple_store import TripleStore
from energy_planner.llm.provider import MockProvider, provider_from_env_or_args
from energy_planner.nlu.orchestrator import ConversationConfig, Orchestrator
from energy_planner.price.loader import (
    PriceUnavailableError,
    load_city_hourly,
    parse_user_hourly_series,
    upsample_hourly_to_slots,
)

STATE_FILE = Path("out/session_state.json")
INSTANCE_FILE = Path("out/instance.json")
ASSUMPTIONS_FILE = Path("out/assumptions.txt")
PRICES_DIR = Path("data/prices")
DEFAULT_PROMPTS_DIR = str(Path(__file__).resolve().parents[1] / "prompts")
DEFAULT_PROVIDER = "ollama"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_API_TEMPERATURE = 0.1
DEFAULT_API_TOP_P = 1.0


def _format_value(value: Optional[str]) -> str:
    return value if value not in (None, "") else "(non impostato)"


def _resolve_config_value(cli_value: Optional[str], env_key: str, default_value: Optional[str], cli_flag_label: str):
    if cli_value not in (None, ""):
        return cli_value, f"CLI ({cli_flag_label})"
    env_value = os.environ.get(env_key)
    if env_value not in (None, ""):
        return env_value, f".env ({env_key})"
    return default_value, "default"


def _mask_key(value: Optional[str]) -> str:
    if not value:
        return ""
    visible = value[-4:]
    return f"***{visible}"


_ENV_STATUS_REPORTED = False


def _report_env_status() -> None:
    global _ENV_STATUS_REPORTED
    if _ENV_STATUS_REPORTED:
        return
    _ENV_STATUS_REPORTED = True
    if _ENV_PATH:
        message = f"File .env caricato da {_ENV_PATH}"
        logger.info(message)
        if not logging.getLogger().handlers:
            print(message)
    else:
        message = (
            "Attenzione: file .env non trovato. Duplica .env.example in .env e personalizzalo prima di usare la CLI."
        )
        logger.warning(message)
        if not logging.getLogger().handlers:
            print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energy-planner",
        description="CLI per l'orchestrazione del planning energetico",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="Avvia la chat conversazionale")
    chat.add_argument("--provider", choices=["ollama", "api", "mock"], help="Provider LLM da utilizzare")
    chat.add_argument("--model", help="Nome modello per Ollama/API")
    chat.add_argument("--api-key", help="API key per provider remoto")
    chat.add_argument("--api-base-url", help="Base URL del provider API")
    chat.add_argument("--ollama-host", help="Endpoint del demone Ollama")
    chat.add_argument("--prompts-dir", help="Cartella con system prompt e few-shots")
    chat.add_argument("--stream", action="store_true", help="Abilita streaming token-by-token")
    chat.add_argument("--export-auto", action="store_true", help="Esporta automaticamente quando i dati minimi sono completi")
    chat.add_argument("--debug", action="store_true", help="Abilita log DEBUG e visualizza gli ultimi blocchi SAVE")
    chat.add_argument("--no-log-prompt", action="store_true", help="Non registrare i contenuti dei messaggi nei log")
    chat.add_argument("--mock-responses", help="File JSON di risposte per il provider mock")
    chat.set_defaults(func=_cmd_chat)

    prices = subparsers.add_parser("prices", help="Gestione prezzi orari")
    prices_sub = prices.add_subparsers(dest="subcommand", required=True)

    paste = prices_sub.add_parser("paste", help="Incolla i 24 prezzi orari per una citta")
    paste.add_argument("--city", required=True, help="Citta (Milano, Roma, Napoli)")
    paste.add_argument("--values", help="24 valori separati da spazio/virgola")
    paste.set_defaults(func=_cmd_prices_paste)

    show = prices_sub.add_parser("show", help="Mostra i prezzi salvati")
    show.add_argument("--city", required=True, help="Citta da visualizzare")
    show.set_defaults(func=_cmd_prices_show)

    export = subparsers.add_parser("export", help="Esporta dati elaborati")
    export_sub = export.add_subparsers(dest="subcommand", required=True)
    export_json = export_sub.add_parser("json", help="Salva l'istanza in out/instance.json")
    export_json.set_defaults(func=_cmd_export_json)

    report = subparsers.add_parser("report", help="Genera report")
    report_sub = report.add_subparsers(dest="subcommand", required=True)
    report_assumptions = report_sub.add_parser("assumptions", help="Salva il report delle assunzioni")
    report_assumptions.set_defaults(func=_cmd_report_assumptions)

    config = subparsers.add_parser("config", help="Mostra configurazioni correnti")
    config_sub = config.add_subparsers(dest="subcommand", required=True)
    config_show = config_sub.add_parser("show", help="Mostra provider e percorso prompt")
    config_show.add_argument("--prompts-dir", help="Percorso prompt da forzare nella visualizzazione")
    config_show.add_argument("--provider", choices=["ollama", "api", "mock"], help="Provider da simulare")
    config_show.add_argument("--model", help="Modello da mostrare")
    config_show.add_argument("--api-base-url", help="Endpoint API da mostrare")
    config_show.add_argument("--api-key", help="API key da mostrare (verra mascherata nei log)")
    config_show.add_argument("--ollama-host", help="Endpoint Ollama da mostrare")
    config_show.set_defaults(func=_cmd_config_show)

    optimize = subparsers.add_parser("optimize", help="Ottimizza un'istanza JSON")
    optimize.add_argument("--input", default="out/instance.json")
    optimize.add_argument("--output", default="out/solution.json")
    optimize.add_argument("--objective", choices=["cost", "peak"])
    optimize.add_argument("--report", action="store_true")
    optimize.add_argument("--baseline", default="out/baseline.json")
    optimize.add_argument("--report-path", default="out/report.md")
    optimize.set_defaults(func=_cmd_optimize)

    schedule = report_sub.add_parser("schedule", help="Report di una soluzione esistente")
    schedule.add_argument("--instance", required=True)
    schedule.add_argument("--solution", required=True)
    schedule.add_argument("--baseline", default="out/baseline.json")
    schedule.add_argument("--output", default="out/report.md")
    schedule.set_defaults(func=_cmd_schedule_report)

    demo = subparsers.add_parser("demo", help="Demo sintetica offline, senza LLM")
    demo.add_argument("--output-dir", default="out/demo")
    demo.add_argument("--objective", choices=["cost", "peak"], default="cost")
    demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    global _ENV_PATH
    env_file = Path.cwd() / ".env"
    _ENV_PATH = str(env_file) if env_file.is_file() else ""
    if _ENV_PATH:
        load_dotenv(_ENV_PATH, override=False)
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if not arguments:
        from energy_planner.cli.menu import main as menu_main
        return menu_main()
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.command in {"chat", "config"}:
        _report_env_status()
    try:
        return args.func(args)
    except PriceUnavailableError as exc:
        _print_error(str(exc))
        return 1
    except KeyboardInterrupt:
        _print_error("Interrotto dall'utente")
        return 130
    except Exception as exc:  # pragma: no cover
        _print_error(f"Errore: {exc}")
        return 1


def _cmd_optimize(args: argparse.Namespace) -> int:
    from EnergyBot5.optimization.optimizer_core import solve_instance
    objective = {"cost": "min_cost", "peak": "min_peak"}.get(args.objective)
    result = solve_instance(args.input, args.output, objective)
    print(f"Piano salvato in {result}")
    if args.report:
        from EnergyBot5.reporting.schedule_report import generate
        generate(args.input, args.output, args.baseline, args.report_path)
    return 0


def _cmd_schedule_report(args: argparse.Namespace) -> int:
    from EnergyBot5.reporting.schedule_report import generate
    generate(args.instance, args.solution, args.baseline, args.output)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from energy_planner.cli.demo import run_demo
    run_demo(Path(args.output_dir), args.objective)
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    provider_kwargs = {
        "provider": args.provider,
        "ollama_host": args.ollama_host,
        "ollama_model": args.model,
        "api_base_url": args.api_base_url,
        "api_key": args.api_key,
        "api_model": args.model,
    }

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, force=True)
        os.environ.setdefault("LOG_LEVEL", "DEBUG")
    else:
        if not logging.getLogger().handlers:
            level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
            level = getattr(logging, level_name, logging.INFO)
            logging.basicConfig(level=level)

    prompts_dir = args.prompts_dir or os.environ.get("PROMPTS_DIR") or DEFAULT_PROMPTS_DIR

    effective_provider = args.provider or os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER
    if effective_provider == "mock":
        if not args.mock_responses:
            raise ValueError("Per il provider mock specificare --mock-responses FILE.json")
        responses = json.loads(Path(args.mock_responses).read_text(encoding="utf-8-sig"))
        if not isinstance(responses, list) or not responses or not all(isinstance(x, str) for x in responses):
            raise ValueError("Il file mock deve essere una lista JSON non vuota di stringhe")
        provider = MockProvider(responses=responses)
    else:
        if args.mock_responses:
            raise ValueError("--mock-responses richiede --provider mock")
        provider = provider_from_env_or_args(**provider_kwargs)
    store = TripleStore()
    config = ConversationConfig(
        prompts_path=prompts_dir,
        stream=args.stream,
        token_callback=_stream_output if args.stream else None,
        export_auto=args.export_auto,
        debug=args.debug,
        log_prompts=not args.no_log_prompt,
    )
    orchestrator = Orchestrator(provider=provider, store=store, config=config)

    print(f"Provider: {provider.name()}")
    try:
        reply = orchestrator.start_session()
        _print_assistant(reply, args)
        if _after_assistant_reply(orchestrator, args):
            return 0
        while True:
            try:
                user_text = input("Tu: ")
            except EOFError:
                print()
                break
            normalized = user_text.strip().lower()
            if normalized in {":quit", ":exit", "exit", "quit"}:
                break
            if args.debug and normalized in {"show save", ":show save"}:
                _print_last_save(orchestrator)
                continue
            reply = orchestrator.handle_user_message(user_text)
            _print_assistant(reply, args)
            if _after_assistant_reply(orchestrator, args):
                return 0
    finally:
        _persist_state(orchestrator.current_state())
    return 0


def _cmd_prices_paste(args: argparse.Namespace) -> int:
    city = args.city.strip().lower()
    if city not in {"milano", "roma", "napoli"}:
        raise ValueError("Citta supportate: Milano, Roma, Napoli")
    raw_values = args.values
    if not raw_values:
        print("Incolla i 24 valori orari (termina con linea vuota):")
        lines: List[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line.strip():
                break
            lines.append(line)
        raw_values = "\n".join(lines)
    values = parse_user_hourly_series(raw_values)
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    path = PRICES_DIR / f"{city}.json"
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    print(f"Salvati {len(values)} valori in {path}")
    return 0


def _cmd_prices_show(args: argparse.Namespace) -> int:
    city = args.city.strip().lower()
    hourly = load_city_hourly(city)
    print("Prezzi orari (EUR/kWh):")
    for idx, value in enumerate(hourly):
        print(f"{idx:02d}: {value:.4f}")
    slots = upsample_hourly_to_slots(hourly)
    print("\nSerie per slot (prime 24 voci):")
    for idx, value in enumerate(slots[:24]):
        print(f"slot {idx:02d}: {value:.4f}")
    print(f"Totale slot: {len(slots)}")
    return 0


def _cmd_export_json(args: argparse.Namespace) -> int:
    state = _load_state(require_compiled=True)
    INSTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps(state["compiled_instance"], indent=2), encoding="utf-8")
    print(f"Istanza JSON esportata in {INSTANCE_FILE}")
    return 0


def _cmd_report_assumptions(args: argparse.Namespace) -> int:
    state = _load_state(require_compiled=False)
    report = state.get("assumptions_report")
    if not report:
        _print_error("Nessun report disponibile: completa prima una sessione di chat.")
        return 1
    ASSUMPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASSUMPTIONS_FILE.write_text(report, encoding="utf-8")
    print(f"Report assunzioni salvato in {ASSUMPTIONS_FILE}")
    return 0


def _cmd_config_show(args: argparse.Namespace) -> int:
    provider_value, provider_source = _resolve_config_value(args.provider, "LLM_PROVIDER", DEFAULT_PROVIDER, "--provider")
    prompts_value, prompts_source = _resolve_config_value(args.prompts_dir, "PROMPTS_DIR", DEFAULT_PROMPTS_DIR, "--prompts-dir")
    provider_effective = (provider_value or "").strip().lower()

    print("Configurazione corrente (valore [origine]):")
    print(f"- Provider: {_format_value(provider_value)} [{provider_source}]")

    provider_label: Optional[str] = None
    try:
        provider_instance = provider_from_env_or_args(
            provider=provider_value,
            ollama_host=args.ollama_host,
            ollama_model=args.model,
            api_base_url=args.api_base_url,
            api_key=args.api_key,
            api_model=args.model,
        )
        provider_label = provider_instance.name()
    except Exception as exc:  # pragma: no cover - utile per diagnosticare config mancanti
        provider_label = f"Non determinabile ({exc})"
    if provider_label:
        print(f"  -> Provider effettivo: {provider_label}")

    if provider_effective in ("", "ollama"):
        host_value, host_source = _resolve_config_value(args.ollama_host, "OLLAMA_HOST", DEFAULT_OLLAMA_HOST, "--ollama-host")
        model_value, model_source = _resolve_config_value(args.model, "OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL, "--model")
        print(f"- Ollama host: {_format_value(host_value)} [{host_source}]")
        print(f"- Modello: {_format_value(model_value)} [{model_source}]")
    elif provider_effective == "api":
        base_url_value, base_url_source = _resolve_config_value(args.api_base_url, "API_BASE_URL", None, "--api-base-url")
        api_model_value, api_model_source = _resolve_config_value(args.model, "API_MODEL", None, "--model")
        api_key_value, api_key_source = _resolve_config_value(args.api_key, "API_KEY", None, "--api-key")
        masked_key = _mask_key(api_key_value) if api_key_value else "(non impostato)"
        print(f"- API base URL: {_format_value(base_url_value)} [{base_url_source}]")
        print(f"- Modello API: {_format_value(api_model_value)} [{api_model_source}]")
        print(f"- API key: {masked_key} [{api_key_source}]")
    else:
        print(f"- Configurazione specifica per provider '{provider_effective}' non gestita.")

    print(f"- Prompt directory: {_format_value(prompts_value)} [{prompts_source}]")
    return 0


def _print_assistant(text: str, args: argparse.Namespace) -> None:
    print("Assistente:")
    print(text)


def _persist_state(state) -> None:
    if not state.compiled_instance:
        return
    data = {
        "compiled_instance": state.compiled_instance,
        "validation_issues": state.validation_issues,
        "assumptions_report": state.assumptions_report,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_state(*, require_compiled: bool) -> Dict[str, Any]:
    if not STATE_FILE.exists():
        raise FileNotFoundError("Nessuno stato disponibile: eseguire prima 'energy-planner chat'.")
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if require_compiled and not data.get("compiled_instance"):
        raise RuntimeError("L'istanza non e pronta: completare la raccolta dati nella chat.")
    return data


def _maybe_print_status(state) -> None:
    if state.validation_issues:
        print("\nAvvisi/Problemi:")
        for issue in state.validation_issues:
            print(f"- [{issue['severity']}] {issue['message']} (Suggerimento: {issue['suggestion']})")
    if state.ready_for_export and state.compiled_instance:
        print("\nI dati minimi sono pronti. Usa 'energy-planner export json' per salvare l'istanza oppure 'energy-planner report assumptions' per il riepilogo.")


def _after_assistant_reply(orchestrator: Orchestrator, args: argparse.Namespace) -> bool:
    state = orchestrator.current_state()
    _persist_state(state)
    _maybe_print_status(state)
    if args.debug:
        _print_last_save(orchestrator)
    if state.export_completed:
        return True
    if args.export_auto:
        return _handle_auto_export(orchestrator, args)
    return False


def _handle_auto_export(orchestrator: Orchestrator, args: argparse.Namespace) -> bool:
    state = orchestrator.current_state()
    if state.export_completed:
        return True
    if state.ready_for_export and not state.export_completed:
        auto_reply = orchestrator.handle_user_message("")
        _print_assistant(auto_reply, args)
        _persist_state(orchestrator.current_state())
        _maybe_print_status(orchestrator.current_state())
        if args.debug:
            _print_last_save(orchestrator)
        return orchestrator.current_state().export_completed
    return False


def _print_last_save(orchestrator: Orchestrator) -> None:
    snapshot = orchestrator.last_save_snapshot()
    if not snapshot:
        print("[DEBUG] Nessun blocco SAVE disponibile.")
        return
    try:
        parsed = json.loads(snapshot)
        pretty = json.dumps(parsed, indent=2)
    except Exception:  # pragma: no cover
        pretty = snapshot
    print("[DEBUG] Ultimo SAVE registrato:")
    print(pretty)


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def _stream_output(chunk: str) -> None:
    print(chunk, end="", flush=True)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
