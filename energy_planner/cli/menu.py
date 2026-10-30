"""Small interactive front end to the same documented CLI commands."""
from pathlib import Path

def main() -> int:
    from energy_planner.cli.app import main as cli
    print("Energy Planner - Innothon2025")
    print("La chat richiede Ollama o un provider API configurato nel file .env.")
    while True:
        print("\n[1] Chat guidata  [2] Ottimizza out/instance.json  [3] Demo offline  [4] Esci")
        try:
            choice = input("Scelta: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "4":
            return 0
        if choice == "1":
            cli(["chat"])
            if Path("out/instance.json").is_file():
                answer = input("Ottimizzare l'istanza in out/instance.json? [s/N]: ").strip().lower()
                if answer in {"s", "si"}:
                    cli(["optimize", "--report"])
        elif choice == "2":
            cli(["optimize", "--report"])
        elif choice == "3":
            cli(["demo"])
        else:
            print("Scelta non valida")
