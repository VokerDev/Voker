#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voker — тулкит-проводник для начинающих в кибербезопасности.

Voker НЕ содержит инструменты внутри себя. Он "оркестратор": проверяет,
установлен ли нужный инструмент, помогает его поставить и запускает.
Часть пунктов — встроенные функции на чистом Python (работают всегда).

Запуск:  python3 voker.py
Список:  python3 voker.py --list
"""

import os
import sys
import time
import shlex
import shutil
import base64
import hashlib
import textwrap
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

# ============================ ЦВЕТА (ANSI) ============================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    PURPLE = "\033[38;5;135m"
    PURPLE_BRIGHT = "\033[38;5;177m"
    PURPLE_DEEP = "\033[38;5;99m"
    LILAC = "\033[38;5;183m"
    GREY = "\033[38;5;245m"
    GREEN = "\033[38;5;114m"
    RED = "\033[38;5;203m"
    YELLOW = "\033[38;5;221m"


def _supports_color() -> bool:
    return not os.environ.get("NO_COLOR") and sys.stdout.isatty()


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
    print(col("  тулкит-проводник для начинающих  ·  v0.2", C.LILAC))
    print(col("  Voker вызывает инструменты, а не заменяет их знание", C.GREY))
    print()


# ============================ ПАНЕЛИ (красивый вывод) ============================

def term_width() -> int:
    try:
        w = shutil.get_terminal_size().columns
    except Exception:
        w = 80
    return max(48, min(w, 100))


def _pad(s: str, width: int) -> str:
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s + " " * (width - len(s))


def panel_card(text: str, color: str):
    """Одиночная закрытая карточка (для заголовка и статуса)."""
    w = term_width()
    inner = w - 4
    print(col("╭" + "─" * (w - 2) + "╮", C.PURPLE_DEEP))
    print(col("│ ", C.PURPLE_DEEP) + col(_pad(text, inner), color) + col(" │", C.PURPLE_DEEP))
    print(col("╰" + "─" * (w - 2) + "╯", C.PURPLE_DEEP))


def panel_open(title: str):
    panel_card("▸ " + title, C.PURPLE_BRIGHT + C.BOLD)


def panel_close(ok: bool, elapsed: float):
    status = ("✓ готово" if ok else "✗ завершилось с ошибкой") + f"   ·   {elapsed:.1f}s"
    panel_card(status, C.GREEN if ok else C.RED)


def rail(lines):
    """Вывод встроенной функции — с фиолетовой боковой рейкой."""
    w = term_width()
    inner = w - 2
    if isinstance(lines, str):
        lines = lines.splitlines() or [""]
    for ln in lines:
        for wl in (textwrap.wrap(ln, inner) or [""]):
            print(col("│ ", C.PURPLE_DEEP) + col(wl, C.LILAC))


# ============================ МОДЕЛЬ ДАННЫХ ============================

@dataclass
class Action:
    name: str                 # человеко-понятное название
    desc: str                 # короткое описание для меню
    explain: str              # понятное объяснение (показывается перед запуском)
    prompt: str               # что спросить ("" — ничего)
    binary: str = ""          # что проверять/запускать (пусто для встроенных функций)
    install: dict = field(default_factory=dict)
    args_template: str = ""   # шаблон аргументов, {target} подставится
    func: Optional[Callable] = None  # встроенная функция(target) -> список строк
    requires_auth: bool = False
    needs_root: bool = False
    note: str = ""


@dataclass
class Category:
    name: str
    desc: str
    actions: list = field(default_factory=list)


# ============================ ВСТРОЕННЫЕ ФУНКЦИИ ============================

def fn_b64_encode(s: str):
    return [base64.b64encode(s.encode()).decode()]


def fn_b64_decode(s: str):
    try:
        return [base64.b64decode(s.encode()).decode(errors="replace")]
    except Exception as e:
        return [f"Не удалось декодировать: {e}"]


def fn_hashes(s: str):
    data = s.encode()
    return [
        f"MD5     : {hashlib.md5(data).hexdigest()}",
        f"SHA1    : {hashlib.sha1(data).hexdigest()}",
        f"SHA256  : {hashlib.sha256(data).hexdigest()}",
    ]


# ============================ РЕЕСТР ИНСТРУМЕНТОВ ============================
# Чтобы добавить пункт — допиши Action в нужную категорию.

APT = "apt"
TOOLKIT = [
    Category("Разведка (OSINT)", "Сбор информации из открытых источников", [
        Action(
            name="Поиск по нику в соцсетях и на сайтах",
            desc="Где занят такой же username (сотни сайтов).",
            explain="Берёт один никнейм и проверяет сотни сайтов, где он зарегистрирован. Помогает связать аккаунты одного человека.",
            prompt="Введи никнейм", binary="sherlock",
            install={"pipx": "pipx install sherlock-project"},
            args_template="{target}",
            note="Бывают ложные совпадения — проверяй вручную.",
        ),
        Action(
            name="Почты и поддомены по домену",
            desc="Собирает e-mail и поддомены из открытых баз.",
            explain="По домену компании ищет её почтовые адреса и поддомены в поисковиках и публичных базах. Классика первого этапа разведки.",
            prompt="Введи домен (например example.com)", binary="theHarvester",
            install={"pipx": "pipx install theHarvester"},
            args_template="-d {target} -b duckduckgo,bing,crtsh",
        ),
        Action(
            name="Все поддомены сайта",
            desc="Перебирает и находит поддомены домена.",
            explain="Ищет скрытые поддомены вида mail.site.com, dev.site.com. Часто именно на забытых поддоменах и находят проблемы.",
            prompt="Введи домен", binary="sublist3r",
            install={"pipx": "pipx install sublist3r", "apt": "sudo apt install sublist3r"},
            args_template="-d {target}",
        ),
        Action(
            name="Кому принадлежит домен или IP (WHOIS)",
            desc="Регистрационные данные домена/IP.",
            explain="Показывает, кто зарегистрировал домен или владеет диапазоном IP: организация, даты, контакты (если не скрыты).",
            prompt="Введи домен или IP", binary="whois",
            install={"apt": "sudo apt install whois", "pacman": "sudo pacman -S whois", "dnf": "sudo dnf install whois"},
            args_template="{target}",
        ),
        Action(
            name="DNS-записи домена",
            desc="Показывает A, MX, NS и другие записи.",
            explain="Достаёт «адресную книгу» домена: где хостится сайт (A), куда идёт почта (MX), какие серверы имён (NS).",
            prompt="Введи домен", binary="dig",
            install={"apt": "sudo apt install dnsutils", "pacman": "sudo pacman -S bind", "dnf": "sudo dnf install bind-utils"},
            args_template="{target} ANY",
        ),
        Action(
            name="Информация и гео по IP-адресу",
            desc="Страна, город, провайдер по IP.",
            explain="Отправляет запрос в публичный сервис ipinfo.io и показывает примерное местоположение и провайдера IP-адреса.",
            prompt="Введи IP-адрес", binary="curl",
            install={"apt": "sudo apt install curl"},
            args_template="-s https://ipinfo.io/{target}",
        ),
        Action(
            name="Метаданные и GPS из фото/файла",
            desc="Достаёт скрытые данные из файла (EXIF).",
            explain="Читает скрытые метаданные файла: модель камеры, дату и — часто — GPS-координаты, где было снято фото. Это и есть простой GEOINT.",
            prompt="Введи путь к файлу (например photo.jpg)", binary="exiftool",
            install={"apt": "sudo apt install libimage-exiftool-perl", "pacman": "sudo pacman -S perl-image-exiftool"},
            args_template="{target}",
        ),
    ]),

    Category("Сеть", "Изучение хостов и открытых портов", [
        Action(
            name="Проверить, доступен ли хост (ping)",
            desc="Жив ли компьютер и как быстро отвечает.",
            explain="Отправляет 4 коротких сигнала и смотрит, отвечает ли машина. Самый первый вопрос: «эта цель вообще онлайн?».",
            prompt="Введи IP или домен", binary="ping",
            install={"apt": "sudo apt install iputils-ping"},
            args_template="-c 4 {target}",
        ),
        Action(
            name="Найти живые устройства в сети",
            desc="Сканирует подсеть и показывает активные хосты.",
            explain="По диапазону адресов (например 192.168.1.0/24) находит все включённые устройства. Так составляют карту локальной сети.",
            prompt="Введи подсеть (например 192.168.1.0/24)", binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-sn {target}", requires_auth=True,
        ),
        Action(
            name="Быстрое сканирование портов",
            desc="Самые частые открытые порты цели.",
            explain="Проверяет 100 самых популярных портов: какие «двери» у цели открыты (сайт, почта, SSH и т.д.).",
            prompt="Введи IP или домен цели", binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-F {target}", requires_auth=True,
        ),
        Action(
            name="Сервисы и их версии на портах",
            desc="Что за программы слушают на портах и версии.",
            explain="Не просто «порт открыт», а какая программа и какой версии за ним. По версии можно понять, есть ли известные уязвимости.",
            prompt="Введи IP или домен цели", binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-sV {target}", requires_auth=True,
        ),
        Action(
            name="Определить операционную систему",
            desc="Угадывает ОС цели по сетевым отпечаткам.",
            explain="По особенностям ответов сети пытается понять, Windows это, Linux или что-то ещё. Требует root-прав.",
            prompt="Введи IP цели", binary="nmap",
            install={"apt": "sudo apt install nmap"},
            args_template="-O {target}", requires_auth=True, needs_root=True,
        ),
        Action(
            name="Маршрут до хоста (traceroute)",
            desc="Через какие узлы идёт путь до цели.",
            explain="Показывает цепочку промежуточных серверов между тобой и целью. Полезно, чтобы понять, где теряется связь.",
            prompt="Введи IP или домен", binary="traceroute",
            install={"apt": "sudo apt install traceroute"},
            args_template="{target}",
        ),
    ]),

    Category("Веб", "Изучение веб-сайтов", [
        Action(
            name="HTTP-заголовки сайта",
            desc="Служебные заголовки ответа сервера.",
            explain="Показывает, что сервер сообщает о себе: тип сервера, редиректы, cookies. Быстрый способ прощупать сайт, ничего не ломая.",
            prompt="Введи URL (например https://example.com)", binary="curl",
            install={"apt": "sudo apt install curl"},
            args_template="-I {target}", requires_auth=True,
        ),
        Action(
            name="Определить технологии сайта",
            desc="CMS, сервер, библиотеки сайта.",
            explain="Определяет, на чём сделан сайт: WordPress, какой веб-сервер, какие библиотеки. С этого начинают, выбирая, что проверять дальше.",
            prompt="Введи URL или домен", binary="whatweb",
            install={"apt": "sudo apt install whatweb", "pacman": "sudo pacman -S whatweb"},
            args_template="{target}", requires_auth=True,
        ),
        Action(
            name="Поиск скрытых страниц и папок",
            desc="Перебирает пути и находит скрытые страницы.",
            explain="По словарю проверяет тысячи возможных адресов (/admin, /backup) и показывает те, что реально существуют на сайте.",
            prompt="Введи URL сайта", binary="gobuster",
            install={"apt": "sudo apt install gobuster"},
            args_template="dir -u {target} -w /usr/share/wordlists/dirb/common.txt",
            requires_auth=True,
            note="Нужен файл-словарь. На Kali он уже лежит по указанному пути.",
        ),
        Action(
            name="Базовая проверка сайта на проблемы",
            desc="Ищет типовые уязвимости и мисконфиги.",
            explain="Быстро проверяет сайт по большому списку известных проблем и устаревших файлов. Хороший обзорный первый скан.",
            prompt="Введи URL сайта", binary="nikto",
            install={"apt": "sudo apt install nikto"},
            args_template="-h {target}", requires_auth=True,
        ),
        Action(
            name="Сканер WordPress-сайтов",
            desc="Плагины, темы и их известные проблемы.",
            explain="Если сайт на WordPress — находит версии темы и плагинов и сверяет с базой известных уязвимостей.",
            prompt="Введи URL WordPress-сайта", binary="wpscan",
            install={"apt": "sudo apt install wpscan", "gem": "sudo gem install wpscan"},
            args_template="--url {target}", requires_auth=True,
        ),
    ]),

    Category("Wi-Fi", "Аудит беспроводных сетей (только с разрешения!)", [
        Action(
            name="Показать Wi-Fi сети рядом",
            desc="Список доступных беспроводных сетей.",
            explain="Сканирует эфир и показывает сети вокруг: имена, каналы, тип защиты. Просто осмотреться, ничего не трогая.",
            prompt="", binary="iwlist",
            install={"apt": "sudo apt install wireless-tools"},
            args_template="scanning", needs_root=True,
        ),
        Action(
            name="Аудит защищённости Wi-Fi сети",
            desc="Проверяет стойкость ближайших сетей.",
            explain="Комбайн для проверки Wi-Fi: находит сети и тестирует их защиту. Запускать можно ТОЛЬКО на своей сети.",
            prompt="", binary="wifite",
            install={"apt": "sudo apt install wifite", "pacman": "sudo pacman -S wifite"},
            args_template="", requires_auth=True, needs_root=True,
            note="Нужен Wi-Fi адаптер с режимом мониторинга и root-права.",
        ),
    ]),

    Category("Хеши и пароли", "Работа с хешами (легально: свои/CTF)", [
        Action(
            name="Определить тип хеша",
            desc="Подсказывает, что это за хеш.",
            explain="По виду строки угадывает алгоритм (MD5, SHA1, bcrypt…). Нужно, чтобы понять, чем такой хеш вообще подбирать.",
            prompt="Введи хеш", binary="hashid",
            install={"pipx": "pipx install hashid", "apt": "sudo apt install hashid"},
            args_template="{target}",
        ),
        Action(
            name="Подобрать пароль к хешу по словарю",
            desc="Перебор пароля из файла-словаря.",
            explain="Берёт файл с хешами и словарь паролей, ищет совпадения. Легально — только для своих хешей и CTF-задач.",
            prompt="Введи путь к файлу с хешами", binary="john",
            install={"apt": "sudo apt install john"},
            args_template="--wordlist=/usr/share/wordlists/rockyou.txt {target}",
            requires_auth=True,
            note="На Kali словарь rockyou.txt лежит по указанному пути (иногда .gz — распакуй).",
        ),
    ]),

    Category("Утилиты", "Встроенные функции — работают без установки", [
        Action(
            name="Base64: закодировать",
            desc="Текст → строка Base64.",
            explain="Превращает обычный текст в формат Base64. Часто нужно при работе с токенами и веб-запросами.",
            prompt="Введи текст", func=fn_b64_encode,
        ),
        Action(
            name="Base64: раскодировать",
            desc="Строка Base64 → обычный текст.",
            explain="Обратное действие: превращает Base64 назад в читаемый текст.",
            prompt="Введи строку Base64", func=fn_b64_decode,
        ),
        Action(
            name="Посчитать хеши строки",
            desc="MD5, SHA1 и SHA256 от текста.",
            explain="Считает три популярных хеша от введённого текста. Удобно сверять пароли и проверять целостность данных.",
            prompt="Введи текст", func=fn_hashes,
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
║  Voker — для ОБУЧЕНИЯ и ЛЕГАЛЬНОГО тестирования.                  ║
║  Проверять чужие сети, сайты и Wi-Fi без письменного разрешения   ║
║  владельца во многих странах — уголовное преступление.            ║
║  Используй только на своих системах, с разрешения или на учебных  ║
║  площадках (HackTheBox, TryHackMe). Ответственность — только твоя. ║
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
    print(col(f"\n  ✗ Инструмент «{action.binary}» не установлен.", C.RED))
    pm = detect_pkg_manager()
    chosen = None
    if pm and pm in action.install:
        chosen = action.install[pm]
    elif "pipx" in action.install:
        chosen = action.install["pipx"]
        if not shutil.which("pipx"):
            chosen += "   (сначала: sudo apt install pipx)"
    if not chosen and action.install:
        chosen = next(iter(action.install.values()))
    print(col("  Установи его так:", C.LILAC))
    print(col(f"      {chosen}", C.GREEN + C.BOLD))
    if len(action.install) > 1:
        others = ", ".join(f"{k}: {v}" for k, v in action.install.items())
        print(col(f"  Другие варианты: {others}", C.GREY))
    print(col("  После установки выбери пункт снова.\n", C.GREY))


def build_command(action: Action, target: str):
    arg_str = action.args_template.format(target=target) if action.args_template else ""
    parts = [action.binary] + (shlex.split(arg_str) if arg_str else [])
    if action.needs_root and not is_root() and shutil.which("sudo"):
        parts = ["sudo"] + parts
    return parts


def run_action(action: Action):
    # Понятное объяснение перед запуском
    print(col(f"\n  {action.explain}", C.GREY))
    if action.requires_auth:
        print(col("  • активно обращается к цели — только с разрешения", C.GREY))
    if action.note:
        print(col(f"  ℹ  {action.note}", C.GREY))

    # Встроенная функция
    if action.func is not None:
        target = input(col(f"\n  {action.prompt}: ", C.LILAC)).strip() if action.prompt else ""
        print()
        panel_open(action.name)
        t = time.perf_counter()
        ok = True
        try:
            rail(action.func(target))
        except Exception as e:
            ok = False
            rail([f"Ошибка: {e}"])
        panel_close(ok, time.perf_counter() - t)
        return

    # Внешний инструмент
    if not shutil.which(action.binary):
        show_install_help(action)
        return

    target = ""
    if action.prompt:
        target = input(col(f"\n  {action.prompt}: ", C.LILAC)).strip()
        if not target:
            print(col("  Пусто — отмена.", C.GREY))
            return

    parts = build_command(action, target)
    title = f"{action.name}" + (f"  ·  {target}" if target else "")
    print()
    panel_open(title)
    t = time.perf_counter()
    ok = True
    try:
        r = subprocess.run(parts)
        ok = (r.returncode == 0)
    except FileNotFoundError:
        ok = False
        print(col("  Не удалось запустить — проверь установку.", C.RED))
    except KeyboardInterrupt:
        ok = False
        print(col("\n  Прервано.", C.GREY))
    panel_close(ok, time.perf_counter() - t)


# ============================ МЕНЮ ============================

def show_installed():
    print()
    panel_open("Что установлено")
    for cat in TOOLKIT:
        for act in cat.actions:
            if act.func is not None:
                mark = col("✓", C.GREEN)
                tail = "встроенное"
            elif shutil.which(act.binary):
                mark = col("✓", C.GREEN)
                tail = act.binary
            else:
                mark = col("✗", C.RED)
                tail = act.binary + " — не установлен"
            print(col("│ ", C.PURPLE_DEEP) + f"{mark} " + col(act.name, C.LILAC)
                  + col(f"  ({tail})", C.GREY))
    panel_close(True, 0.0)


def category_menu(cat: Category):
    while True:
        print()
        panel_open(cat.name)
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
    total = sum(len(c.actions) for c in TOOLKIT)
    while True:
        print()
        panel_open(f"Главное меню  ·  {total} команд")
        for i, cat in enumerate(TOOLKIT, 1):
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(cat.name, C.LILAC)
                  + col(f"  ({len(cat.actions)})", C.GREY))
            print(col(f"       {cat.desc}", C.GREY))
        print(col("\n  [i] Проверить установленные инструменты", C.GREY))
        print(col("  [q] Выход", C.GREY))
        choice = input(col("\n  Выбор: ", C.YELLOW)).strip().lower()
        if choice in ("q", "quit", "exit"):
            print(col("\n  До встречи. Учись легально. 💜\n", C.PURPLE_BRIGHT))
            return
        if choice == "i":
            show_installed()
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(TOOLKIT):
            category_menu(TOOLKIT[int(choice) - 1])
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ CLI ============================

def print_tree():
    print_banner()
    for cat in TOOLKIT:
        print(col(f"▸ {cat.name}", C.PURPLE_BRIGHT + C.BOLD) + col(f" — {cat.desc}", C.GREY))
        for act in cat.actions:
            if act.func is not None:
                mark, tgt = col("✓", C.GREEN), "встроенное"
            else:
                ok = bool(shutil.which(act.binary))
                mark = col("✓" if ok else "✗", C.GREEN if ok else C.RED)
                tgt = act.binary
            flags = " [auth]" if act.requires_auth else ""
            print(f"    {mark} {act.name} " + col(f"→ {tgt}{flags}", C.GREY))
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
