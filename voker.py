#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voker — тулкит-проводник для начинающих в кибербезопасности.

ВАЖНО: Voker НЕ содержит инструментов внутри себя. Он работает как
"оркестратор": проверяет, установлен ли нужный инструмент, помогает его
поставить, а затем собирает за тебя правильную команду и запускает уже
существующую программу (nmap, sherlock и т.д.).

Запуск:  python3 voker.py
Список:  python3 voker.py --list
"""

import os
import sys
import shlex
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field

# ============================ ЦВЕТА (ANSI) ============================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    # фиолетовая палитра
    PURPLE = "\033[38;5;135m"
    PURPLE_BRIGHT = "\033[38;5;177m"
    PURPLE_DEEP = "\033[38;5;99m"
    LILAC = "\033[38;5;183m"
    GREY = "\033[38;5;245m"
    GREEN = "\033[38;5;114m"
    RED = "\033[38;5;203m"
    YELLOW = "\033[38;5;221m"


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


USE_COLOR = _supports_color()


def col(text: str, color: str) -> str:
    return f"{color}{text}{C.RESET}" if USE_COLOR else text


# ============================ БАННЕР ============================

BANNER = r"""
 __     __    _
 \ \   / /__ | | _____ _ __
  \ \ / / _ \| |/ / _ \ '__|
   \ V / (_) |   <  __/ |
    \_/ \___/|_|\_\___|_|
"""


def print_banner():
    for line in BANNER.strip("\n").splitlines():
        print(col(line, C.PURPLE_BRIGHT + C.BOLD))
    print(col("  тулкит-проводник для начинающих  ·  v0.1", C.LILAC))
    print(col("  Voker вызывает инструменты, а не заменяет их знание", C.GREY))
    print()


# ============================ МОДЕЛЬ ДАННЫХ ============================

@dataclass
class Action:
    name: str                 # человеко-понятное название
    desc: str                 # что делает
    binary: str               # что проверяем через which
    install: dict             # {"apt": "...", "pipx": "...", ...}
    args_template: str        # шаблон аргументов, {target} подставится
    prompt: str               # что спросить у пользователя ("" = ничего не спрашивать)
    requires_auth: bool = False   # активно воздействует на цель -> нужно подтверждение
    needs_root: bool = False      # нужен root/sudo
    note: str = ""            # краткая инструкция/предупреждение


@dataclass
class Category:
    name: str
    desc: str
    actions: list = field(default_factory=list)


# ============================ РЕЕСТР ИНСТРУМЕНТОВ ============================
# Чтобы добавить инструмент — просто допиши Action в нужную категорию.

TOOLKIT = [
    Category("OSINT", "Разведка по открытым источникам", [
        Action(
            name="Поиск по нику в соцсетях и на сайтах",
            desc="Проверяет сотни сайтов: где занят такой же username.",
            binary="sherlock",
            install={"pipx": "pipx install sherlock-project"},
            args_template="{target}",
            prompt="Введи никнейм для поиска",
            note="Возможны ложные совпадения — проверяй результаты вручную.",
        ),
        Action(
            name="Почты и поддомены по домену",
            desc="Собирает e-mail адреса и поддомены из открытых источников.",
            binary="theHarvester",
            install={"pipx": "pipx install theHarvester"},
            args_template="-d {target} -b duckduckgo,bing,crtsh",
            prompt="Введи домен (например example.com)",
        ),
        Action(
            name="WHOIS — кому принадлежит домен или IP",
            desc="Регистрационные данные домена или диапазона IP.",
            binary="whois",
            install={
                "apt": "sudo apt install whois",
                "pacman": "sudo pacman -S whois",
                "dnf": "sudo dnf install whois",
            },
            args_template="{target}",
            prompt="Введи домен или IP",
        ),
    ]),

    Category("Сканирование сети", "Изучение хостов и открытых портов", [
        Action(
            name="Быстрое сканирование портов",
            desc="Показывает самые частые открытые порты цели.",
            binary="nmap",
            install={
                "apt": "sudo apt install nmap",
                "pacman": "sudo pacman -S nmap",
                "dnf": "sudo dnf install nmap",
            },
            args_template="-F {target}",
            prompt="Введи IP или домен цели",
            requires_auth=True,
        ),
        Action(
            name="Сервисы и версии на портах",
            desc="Определяет, какие программы и версии слушают на портах.",
            binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-sV {target}",
            prompt="Введи IP или домен цели",
            requires_auth=True,
        ),
        Action(
            name="Определение операционной системы",
            desc="Пытается угадать ОС цели по сетевым отпечаткам.",
            binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-O {target}",
            prompt="Введи IP цели",
            requires_auth=True,
            needs_root=True,
        ),
    ]),

    Category("Веб-разведка", "Изучение веб-сайтов", [
        Action(
            name="Определить технологии сайта",
            desc="Показывает CMS, веб-сервер и библиотеки, которые использует сайт.",
            binary="whatweb",
            install={
                "apt": "sudo apt install whatweb",
                "pacman": "sudo pacman -S whatweb",
            },
            args_template="{target}",
            prompt="Введи URL или домен (например https://example.com)",
            requires_auth=True,
        ),
    ]),

    Category("Wi-Fi", "Аудит беспроводных сетей (только с разрешения!)", [
        Action(
            name="Аудит Wi-Fi сетей рядом",
            desc="Ищет ближайшие сети и проверяет их защищённость.",
            binary="wifite",
            install={
                "apt": "sudo apt install wifite",
                "pacman": "sudo pacman -S wifite",
            },
            args_template="",
            prompt="",
            requires_auth=True,
            needs_root=True,
            note="Нужен Wi-Fi адаптер с режимом мониторинга и root-права.",
        ),
    ]),
]


# ============================ ДИСКЛЕЙМЕР ============================

CONFIG_DIR = Path.home() / ".voker"
ACCEPT_FILE = CONFIG_DIR / "accepted"

DISCLAIMER = """
╔══════════════════════════════════════════════════════════════════╗
║                    ПРАВОВОЕ ПРЕДУПРЕЖДЕНИЕ                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Voker — инструмент для ОБУЧЕНИЯ и ЛЕГАЛЬНОГО тестирования.       ║
║                                                                    ║
║  Сканирование сетей, сайтов и Wi-Fi без письменного разрешения    ║
║  владельца во многих странах является уголовным преступлением.    ║
║                                                                    ║
║  Используй Voker только на:                                        ║
║    • своих собственных системах;                                   ║
║    • системах, где у тебя есть письменное разрешение;              ║
║    • специальных учебных площадках (HackTheBox, TryHackMe и т.п.). ║
║                                                                    ║
║  Всю ответственность за свои действия несёшь только ты.            ║
╚══════════════════════════════════════════════════════════════════╝
"""


def ensure_disclaimer():
    if ACCEPT_FILE.exists():
        return
    print(col(DISCLAIMER, C.PURPLE))
    ans = input(col("Введи 'СОГЛАСЕН' чтобы продолжить: ", C.YELLOW)).strip().lower()
    if ans not in ("согласен", "agree", "yes", "y"):
        print(col("Без согласия работать нельзя. Выход.", C.RED))
        sys.exit(0)
    CONFIG_DIR.mkdir(exist_ok=True)
    ACCEPT_FILE.write_text("accepted\n", encoding="utf-8")


# ============================ УТИЛИТЫ ============================

def detect_pkg_manager():
    for pm in ("apt", "pacman", "dnf", "yum", "brew"):
        if shutil.which(pm):
            return pm
    return None


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def show_install_help(action: Action):
    print(col(f"\n  ✗ Инструмент '{action.binary}' не установлен.", C.RED))
    pm = detect_pkg_manager()
    chosen = None
    if pm and pm in action.install:
        chosen = action.install[pm]
    elif "pipx" in action.install:
        chosen = action.install["pipx"]
        if not shutil.which("pipx"):
            chosen += col("   (сначала: sudo apt install pipx)", C.GREY)
    if not chosen:
        chosen = next(iter(action.install.values()))

    print(col("  Установи его командой:", C.LILAC))
    print(col(f"      {chosen}", C.GREEN + C.BOLD))
    if len(action.install) > 1:
        others = ", ".join(f"{k}: {v}" for k, v in action.install.items())
        print(col(f"  Другие варианты: {others}", C.GREY))
    print(col("  После установки вернись в меню и выбери пункт снова.\n", C.GREY))


def confirm_authorization(target: str) -> bool:
    print(col("\n  ⚠  Эта команда активно обращается к цели.", C.YELLOW))
    if target:
        print(col(f"     Цель: {target}", C.YELLOW))
    print(col("     Убедись, что у тебя есть РАЗРЕШЕНИЕ её тестировать.", C.YELLOW))
    ans = input(col("     Есть разрешение? Введи 'ДА': ", C.YELLOW)).strip().lower()
    return ans in ("да", "yes", "y")


def build_command(action: Action, target: str):
    arg_str = action.args_template.format(target=target) if action.args_template else ""
    parts = [action.binary] + (shlex.split(arg_str) if arg_str else [])
    if action.needs_root and not is_root() and shutil.which("sudo"):
        parts = ["sudo"] + parts
    return parts


def run_action(action: Action):
    # 1. Проверяем, установлен ли инструмент
    if not shutil.which(action.binary):
        show_install_help(action)
        return

    # 2. Спрашиваем цель, если нужно
    target = ""
    if action.prompt:
        target = input(col(f"\n  {action.prompt}: ", C.LILAC)).strip()
        if not target:
            print(col("  Пусто — отмена.", C.GREY))
            return

    # 3. Подтверждение для активных действий
    if action.requires_auth and not confirm_authorization(target):
        print(col("  Отменено.", C.GREY))
        return

    # 4. Собираем и показываем команду
    parts = build_command(action, target)
    cmd_str = " ".join(shlex.quote(p) for p in parts)
    print(col("\n  Собранная команда:", C.LILAC))
    print(col(f"      {cmd_str}", C.GREEN + C.BOLD))
    if action.note:
        print(col(f"  ℹ  {action.note}", C.GREY))
    if action.needs_root and not is_root():
        print(col("  ℹ  Потребуются root-права (sudo).", C.GREY))

    # 5. Запускаем или просто показываем
    ans = input(col("  Запустить сейчас? [Y/n]: ", C.YELLOW)).strip().lower()
    if ans in ("", "y", "yes", "да"):
        print(col("  ─" * 30, C.PURPLE_DEEP))
        try:
            subprocess.run(parts)
        except FileNotFoundError:
            print(col("  Не удалось запустить — проверь установку.", C.RED))
        except KeyboardInterrupt:
            print(col("\n  Прервано пользователем.", C.GREY))
        print(col("  ─" * 30, C.PURPLE_DEEP))
    else:
        print(col("  Ок, команду можешь скопировать и запустить сам.", C.GREY))


# ============================ МЕНЮ ============================

def box_title(text: str):
    line = "═" * (len(text) + 2)
    print(col(f"╔{line}╗", C.PURPLE_DEEP))
    print(col(f"║ {text} ║", C.PURPLE_BRIGHT + C.BOLD))
    print(col(f"╚{line}╝", C.PURPLE_DEEP))


def category_menu(cat: Category):
    while True:
        print()
        box_title(cat.name)
        print(col(f"  {cat.desc}\n", C.GREY))
        for i, act in enumerate(cat.actions, 1):
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(act.name, C.LILAC))
            print(col(f"       {act.desc}", C.GREY))
        print(col("\n  [0] Назад", C.GREY))
        choice = input(col("\n  Выбор: ", C.YELLOW)).strip()
        if choice == "0":
            return
        if choice.isdigit() and 1 <= int(choice) <= len(cat.actions):
            run_action(cat.actions[int(choice) - 1])
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
        else:
            print(col("  Нет такого пункта.", C.RED))


def main_menu():
    while True:
        print()
        box_title("Главное меню")
        for i, cat in enumerate(TOOLKIT, 1):
            n = len(cat.actions)
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT)
                  + col(cat.name, C.LILAC)
                  + col(f"  ({n})", C.GREY))
            print(col(f"       {cat.desc}", C.GREY))
        print(col("\n  [q] Выход", C.GREY))
        choice = input(col("\n  Выбор: ", C.YELLOW)).strip().lower()
        if choice in ("q", "quit", "exit"):
            print(col("\n  До встречи. Учись легально. 💜\n", C.PURPLE_BRIGHT))
            return
        if choice.isdigit() and 1 <= int(choice) <= len(TOOLKIT):
            category_menu(TOOLKIT[int(choice) - 1])
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ CLI ============================

def print_tree():
    """Печатает всё дерево инструментов без запуска (для --list)."""
    print_banner()
    for cat in TOOLKIT:
        print(col(f"▸ {cat.name}", C.PURPLE_BRIGHT + C.BOLD)
              + col(f" — {cat.desc}", C.GREY))
        for act in cat.actions:
            installed = "✓" if shutil.which(act.binary) else "✗"
            mark = col(installed, C.GREEN if installed == "✓" else C.RED)
            flags = " [auth]" if act.requires_auth else ""
            print(f"    {mark} {act.name} "
                  + col(f"→ {act.binary}{flags}", C.GREY))
        print()


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args and args[0] in ("-l", "--list"):
        print_tree()
        return

    try:
        print_banner()
        ensure_disclaimer()
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(col("\n\n  Выход.\n", C.GREY))


if __name__ == "__main__":
    main()
