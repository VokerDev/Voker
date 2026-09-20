#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voker — тулкит-проводник для начинающих в кибербезопасности.

Voker НЕ содержит инструменты внутри себя. Он "оркестратор": проверяет,
установлен ли инструмент, помогает его поставить и запускает. Часть пунктов —
встроенные функции на чистом Python (работают без установки).

Результаты каждой команды сохраняются в ~/.voker/results/ (txt + json,
а у перехвата трафика — .pcap для Wireshark) и показываются сводной табличкой.

Запуск:  python3 voker.py
Список:  python3 voker.py --list
"""

import os
import re
import sys
import json
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
    print(col("  тулкит-проводник для начинающих  ·  v0.3", C.LILAC))
    print(col("  Voker вызывает инструменты, а не заменяет их знание", C.GREY))
    print()


# ============================ ПАНЕЛИ ============================

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


def rail_line(s: str):
    print(col("│ ", C.PURPLE_DEEP) + col(s, C.LILAC))


def rail(lines):
    w = term_width()
    inner = w - 2
    if isinstance(lines, str):
        lines = lines.splitlines() or [""]
    for ln in lines:
        for wl in (textwrap.wrap(ln, inner) or [""]):
            rail_line(wl)


# ============================ ТАБЛИЦА ============================

def _fit(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def print_table(headers, rows, caps):
    widths = []
    for i in range(len(headers)):
        mx = len(headers[i])
        for r in rows:
            mx = max(mx, len(_fit(r[i], caps[i])))
        widths.append(min(mx, caps[i]))

    def border(l, m, r):
        return l + m.join("─" * (w + 2) for w in widths) + r

    def row_str(cells):
        return "│" + "│".join(" " + _fit(c, caps[i]).ljust(widths[i]) + " "
                              for i, c in enumerate(cells)) + "│"

    print(col(border("╭", "┬", "╮"), C.PURPLE_DEEP))
    print(col(row_str(headers), C.PURPLE_BRIGHT + C.BOLD))
    print(col(border("├", "┼", "┤"), C.PURPLE_DEEP))
    for r in rows:
        print(col(row_str(r), C.LILAC))
    print(col(border("╰", "┴", "╯"), C.PURPLE_DEEP))


# ============================ МОДЕЛЬ ДАННЫХ ============================

@dataclass
class Action:
    name: str
    desc: str
    explain: str
    prompt: str
    binary: str = ""
    install: dict = field(default_factory=dict)
    args_template: str = ""
    func: Optional[Callable] = None
    requires_auth: bool = False
    needs_root: bool = False
    interactive: bool = False   # нужен живой ввод (вывод не перехватываем)
    outfile_ext: str = ""       # если задано — {outfile} укажет на файл результата
    default: str = ""           # значение при пустом вводе
    note: str = ""


@dataclass
class Category:
    name: str
    desc: str
    actions: list = field(default_factory=list)


# ============================ ВСТРОЕННЫЕ ФУНКЦИИ ============================

def fn_b64_encode(s):
    return [base64.b64encode(s.encode()).decode()]


def fn_b64_decode(s):
    try:
        return [base64.b64decode(s.encode()).decode(errors="replace")]
    except Exception as e:
        return [f"Не удалось декодировать: {e}"]


def fn_hex_encode(s):
    return [s.encode().hex()]


def fn_hex_decode(s):
    try:
        return [bytes.fromhex(s.strip().replace(" ", "")).decode(errors="replace")]
    except Exception as e:
        return [f"Ошибка: {e}"]


def fn_url_encode(s):
    import urllib.parse
    return [urllib.parse.quote(s)]


def fn_url_decode(s):
    import urllib.parse
    return [urllib.parse.unquote(s)]


def fn_rot13(s):
    import codecs
    return [codecs.encode(s, "rot_13")]


def fn_caesar_all(s):
    out = []
    for k in range(1, 26):
        r = "".join(
            chr((ord(c) - 97 + k) % 26 + 97) if c.islower()
            else chr((ord(c) - 65 + k) % 26 + 65) if c.isupper()
            else c for c in s)
        out.append(f"сдвиг {k:2}: {r}")
    return out


def fn_hashes(s):
    d = s.encode()
    return [
        f"MD5     : {hashlib.md5(d).hexdigest()}",
        f"SHA1    : {hashlib.sha1(d).hexdigest()}",
        f"SHA256  : {hashlib.sha256(d).hexdigest()}",
    ]


def fn_file_hash(path):
    p = Path(path)
    if not p.is_file():
        return [f"Файл не найден: {path}"]
    d = p.read_bytes()
    return [
        f"Файл    : {p.name}  ({len(d)} байт)",
        f"MD5     : {hashlib.md5(d).hexdigest()}",
        f"SHA256  : {hashlib.sha256(d).hexdigest()}",
    ]


def fn_jwt_decode(tok):
    parts = tok.strip().split(".")
    if len(parts) < 2:
        return ["Не похоже на JWT (нужны части, разделённые точками)."]

    def dec(seg):
        seg += "=" * (-len(seg) % 4)
        return base64.urlsafe_b64decode(seg).decode(errors="replace")

    try:
        return ["HEADER:", dec(parts[0]), "", "PAYLOAD:", dec(parts[1]),
                "", "(подпись не проверяется — только чтение содержимого)"]
    except Exception as e:
        return [f"Ошибка разбора: {e}"]


def fn_gen_password(n_str):
    import secrets, string
    try:
        n = int(n_str) if n_str else 20
    except ValueError:
        n = 20
    n = max(8, min(n, 128))
    alpha = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return [f"Пароль ({n} символов):", "".join(secrets.choice(alpha) for _ in range(n))]


def fn_cidr(cidr):
    import ipaddress
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = list(net.hosts())
        rng = f"{hosts[0]} — {hosts[-1]}" if hosts else "-"
        return [
            f"Сеть      : {net.network_address}",
            f"Маска     : {net.netmask}",
            f"Broadcast : {getattr(net, 'broadcast_address', '-')}",
            f"Всего адр.: {net.num_addresses}",
            f"Хостов    : {len(hosts)}",
            f"Диапазон  : {rng}",
        ]
    except Exception as e:
        return [f"Ошибка: {e}"]


def fn_port_check(arg):
    import socket
    if ":" not in arg:
        return ["Формат: host:port  (например example.com:443)"]
    host, port = arg.rsplit(":", 1)
    try:
        port = int(port)
    except ValueError:
        return ["Порт должен быть числом."]
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((host, port))
        s.close()
        return [f"Порт {port} на {host}: ОТКРЫТ"]
    except Exception:
        return [f"Порт {port} на {host}: закрыт или недоступен"]


def fn_my_ip(_):
    import socket
    host = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local = s.getsockname()[0]
        s.close()
    except Exception:
        local = "?"
    return [f"Имя хоста : {host}", f"Локальный IP: {local}"]


# ============================ РЕЕСТР ИНСТРУМЕНТОВ ============================

TOOLKIT = [
    Category("Разведка (OSINT)", "Сбор информации из открытых источников", [
        Action("Поиск по нику в соцсетях и на сайтах",
               "Где занят такой же username (сотни сайтов).",
               "Берёт один никнейм и проверяет сотни сайтов, где он зарегистрирован. Помогает связать аккаунты одного человека.",
               "Введи никнейм", binary="sherlock",
               install={"pipx": "pipx install sherlock-project"}, args_template="{target}",
               note="Возможны ложные совпадения — проверяй вручную."),
        Action("Почты и поддомены по домену",
               "Собирает e-mail и поддомены из открытых баз.",
               "По домену ищет почтовые адреса и поддомены в поисковиках и публичных базах. Классика первого этапа разведки.",
               "Введи домен (example.com)", binary="theHarvester",
               install={"pipx": "pipx install theHarvester"}, args_template="-d {target} -b duckduckgo,bing,crtsh"),
        Action("Все поддомены сайта",
               "Перебирает и находит поддомены домена.",
               "Ищет скрытые поддомены вида mail.site.com, dev.site.com. Часто именно на забытых поддоменах и находят проблемы.",
               "Введи домен", binary="sublist3r",
               install={"pipx": "pipx install sublist3r", "apt": "sudo apt install sublist3r"}, args_template="-d {target}"),
        Action("Глубокая разведка DNS (dnsrecon)",
               "Расширенный сбор DNS-записей и зон.",
               "Собирает из DNS максимум: записи, зоны, поддомены. Более подробно, чем обычный запрос.",
               "Введи домен", binary="dnsrecon",
               install={"apt": "sudo apt install dnsrecon"}, args_template="-d {target}"),
        Action("Перечисление DNS (dnsenum)",
               "Другой инструмент разведки DNS.",
               "Ещё один сборщик DNS-информации: записи, поддомены, диапазоны. Полезно сравнить результаты с dnsrecon.",
               "Введи домен", binary="dnsenum",
               install={"apt": "sudo apt install dnsenum"}, args_template="{target}"),
        Action("Разведка DNS (fierce)",
               "Ищет поддомены и соседние сети.",
               "Прощупывает DNS домена и находит поддомены и связанные диапазоны IP.",
               "Введи домен", binary="fierce",
               install={"apt": "sudo apt install fierce"}, args_template="--domain {target}"),
        Action("Кому принадлежит домен или IP (WHOIS)",
               "Регистрационные данные домена/IP.",
               "Показывает, кто зарегистрировал домен или владеет диапазоном IP: организация, даты, контакты.",
               "Введи домен или IP", binary="whois",
               install={"apt": "sudo apt install whois", "pacman": "sudo pacman -S whois"}, args_template="{target}"),
        Action("DNS-записи домена (dig)",
               "Показывает A, MX, NS и другие записи.",
               "«Адресная книга» домена: где хостится сайт (A), куда идёт почта (MX), какие серверы имён (NS).",
               "Введи домен", binary="dig",
               install={"apt": "sudo apt install dnsutils", "dnf": "sudo dnf install bind-utils"}, args_template="{target} ANY"),
        Action("Быстрый DNS-запрос (host)",
               "Простой перевод домена в IP и обратно.",
               "Самый простой способ узнать IP домена или домен по IP. Быстро и без лишнего.",
               "Введи домен или IP", binary="host",
               install={"apt": "sudo apt install dnsutils"}, args_template="{target}"),
        Action("Информация и гео по IP-адресу",
               "Страна, город, провайдер по IP.",
               "Запрашивает публичный сервис ipinfo.io и показывает примерное местоположение и провайдера IP.",
               "Введи IP-адрес", binary="curl",
               install={"apt": "sudo apt install curl"}, args_template="-s https://ipinfo.io/{target}"),
        Action("Метаданные и GPS из файла (EXIF)",
               "Достаёт скрытые данные из фото/файла.",
               "Читает скрытые метаданные: модель камеры, дату и часто GPS-координаты съёмки. Это простой GEOINT.",
               "Введи путь к файлу (photo.jpg)", binary="exiftool",
               install={"apt": "sudo apt install libimage-exiftool-perl"}, args_template="{target}",
               note="GPS будет только если он реально записан — соцсети часто вырезают его."),
        Action("Определить веб-файрвол (wafw00f)",
               "Проверяет, стоит ли перед сайтом WAF.",
               "Определяет, защищён ли сайт веб-файрволом (Cloudflare и т.п.). Полезно понимать до любых веб-проверок.",
               "Введи URL сайта", binary="wafw00f",
               install={"apt": "sudo apt install wafw00f", "pipx": "pipx install wafw00f"}, args_template="{target}",
               requires_auth=True),
        Action("Собрать словарь со страницы (cewl)",
               "Делает список слов из текста сайта.",
               "Скачивает текст сайта и собирает из него список слов — их потом используют как словарь паролей/каталогов.",
               "Введи URL сайта", binary="cewl",
               install={"apt": "sudo apt install cewl"}, args_template="{target}", requires_auth=True),
    ]),

    Category("Сеть", "Изучение хостов и открытых портов", [
        Action("Доступен ли хост (ping)",
               "Жив ли компьютер и как быстро отвечает.",
               "Отправляет 4 коротких сигнала и смотрит, отвечает ли машина. Первый вопрос: «цель вообще онлайн?».",
               "Введи IP или домен", binary="ping",
               install={"apt": "sudo apt install iputils-ping"}, args_template="-c 4 {target}"),
        Action("Найти живые устройства в сети (nmap)",
               "Сканирует подсеть, показывает активные хосты.",
               "По диапазону адресов находит все включённые устройства. Так составляют карту локальной сети.",
               "Введи подсеть (192.168.1.0/24)", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="-sn {target}", requires_auth=True),
        Action("Устройства в сети по ARP (arp-scan)",
               "Находит соседей по локальной сети.",
               "Рассылает ARP-запросы и находит устройства в твоей локальной сети вместе с их MAC-адресами.",
               "", binary="arp-scan",
               install={"apt": "sudo apt install arp-scan"}, args_template="--localnet",
               needs_root=True, requires_auth=True),
        Action("Быстрое сканирование портов (nmap)",
               "Самые частые открытые порты цели.",
               "Проверяет 100 популярных портов: какие «двери» у цели открыты (сайт, почта, SSH).",
               "Введи IP или домен", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="-F {target}", requires_auth=True),
        Action("Сервисы и версии на портах (nmap)",
               "Что за программы слушают и какие версии.",
               "Не просто «порт открыт», а какая программа и версия за ним. По версии видно известные уязвимости.",
               "Введи IP или домен", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="-sV {target}", requires_auth=True),
        Action("Определить ОС цели (nmap)",
               "Угадывает операционную систему.",
               "По особенностям сетевых ответов пытается понять, Windows это, Linux или другое. Нужен root.",
               "Введи IP цели", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="-O {target}",
               requires_auth=True, needs_root=True),
        Action("Проверка на известные уязвимости (nmap)",
               "Запускает скрипты поиска уязвимостей.",
               "Гоняет встроенные nmap-скрипты категории vuln и отмечает известные проблемы на открытых сервисах.",
               "Введи IP или домен", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="--script vuln {target}", requires_auth=True),
        Action("Очень быстрый скан портов (masscan)",
               "Сканирует порты на большой скорости.",
               "Просматривает диапазон портов гораздо быстрее nmap. Хорош для больших сетей. Нужен root.",
               "Введи IP или подсеть", binary="masscan",
               install={"apt": "sudo apt install masscan"}, args_template="-p1-1000 {target} --rate 1000",
               requires_auth=True, needs_root=True, note="Высокая скорость создаёт заметную нагрузку — только по своим целям."),
        Action("Маршрут до хоста (traceroute)",
               "Через какие узлы идёт путь до цели.",
               "Показывает цепочку промежуточных серверов между тобой и целью. Видно, где теряется связь.",
               "Введи IP или домен", binary="traceroute",
               install={"apt": "sudo apt install traceroute"}, args_template="{target}"),
        Action("Перехват трафика → файл для Wireshark",
               "Записывает пакеты в .pcap.",
               "Ловит 200 сетевых пакетов на интерфейсе и сохраняет их в .pcap — этот файл открывается в Wireshark. Нужен root.",
               "Интерфейс (Enter = any)", binary="tcpdump",
               install={"apt": "sudo apt install tcpdump"}, args_template="-i {target} -c 200 -w {outfile}",
               needs_root=True, outfile_ext="pcap", default="any",
               note="Открой полученный .pcap в Wireshark для анализа."),
        Action("Мои открытые порты (ss)",
               "Что слушает на твоём компьютере.",
               "Показывает, какие порты открыты на ЭТОЙ машине и какие программы их слушают. Полностью безопасно.",
               "", binary="ss",
               install={"apt": "sudo apt install iproute2"}, args_template="-tuln"),
    ]),

    Category("Веб", "Изучение веб-сайтов", [
        Action("HTTP-заголовки сайта (curl)",
               "Служебные заголовки ответа сервера.",
               "Показывает, что сервер сообщает о себе: тип, редиректы, cookies. Быстро прощупать сайт, ничего не ломая.",
               "Введи URL (https://example.com)", binary="curl",
               install={"apt": "sudo apt install curl"}, args_template="-I {target}", requires_auth=True),
        Action("Определить технологии сайта (whatweb)",
               "CMS, сервер, библиотеки сайта.",
               "Определяет, на чём сделан сайт: WordPress, веб-сервер, библиотеки. С этого выбирают, что проверять дальше.",
               "Введи URL или домен", binary="whatweb",
               install={"apt": "sudo apt install whatweb"}, args_template="{target}", requires_auth=True),
        Action("Поиск скрытых страниц (gobuster)",
               "Перебирает пути, находит скрытые страницы.",
               "По словарю проверяет тысячи адресов (/admin, /backup) и показывает реально существующие.",
               "Введи URL сайта", binary="gobuster",
               install={"apt": "sudo apt install gobuster"},
               args_template="dir -u {target} -w /usr/share/wordlists/dirb/common.txt",
               requires_auth=True, note="Словарь по указанному пути есть на Kali; на другой ОС укажи свой."),
        Action("Поиск папок (dirb)",
               "Классический перебор директорий.",
               "Похоже на gobuster, но со встроенным словарём. Простой запуск без указания словаря.",
               "Введи URL сайта", binary="dirb",
               install={"apt": "sudo apt install dirb"}, args_template="{target}", requires_auth=True),
        Action("Фаззинг адресов (ffuf)",
               "Быстро подбирает пути и параметры.",
               "Очень быстрый инструмент: подставляет слова из словаря в адрес и ищет живые страницы.",
               "Введи URL с FUZZ (site.com/FUZZ)", binary="ffuf",
               install={"apt": "sudo apt install ffuf"},
               args_template="-u {target} -w /usr/share/wordlists/dirb/common.txt",
               requires_auth=True, note="В адресе укажи слово FUZZ там, где подставлять слова."),
        Action("Базовая проверка сайта (nikto)",
               "Ищет типовые уязвимости и мисконфиги.",
               "Проверяет сайт по большому списку известных проблем и устаревших файлов. Хороший обзорный скан.",
               "Введи URL сайта", binary="nikto",
               install={"apt": "sudo apt install nikto"}, args_template="-h {target}", requires_auth=True),
        Action("Сканер WordPress (wpscan)",
               "Плагины, темы и их известные проблемы.",
               "Если сайт на WordPress — находит версии темы и плагинов и сверяет с базой уязвимостей.",
               "Введи URL WordPress-сайта", binary="wpscan",
               install={"apt": "sudo apt install wpscan"}, args_template="--url {target}", requires_auth=True),
        Action("Шаблонный поиск уязвимостей (nuclei)",
               "Проверяет сайт по базе шаблонов.",
               "Современный сканер: гоняет тысячи готовых шаблонов известных уязвимостей и мисконфигов.",
               "Введи URL сайта", binary="nuclei",
               install={"apt": "sudo apt install nuclei"}, args_template="-u {target}", requires_auth=True),
        Action("Тест SQL-инъекций (sqlmap)",
               "Проверяет параметры на SQL-инъекции.",
               "Стандартный инструмент проверки на SQL-инъекции. Мощный и активный — только по своим/учебным целям.",
               "Введи URL с параметром (?id=1)", binary="sqlmap",
               install={"apt": "sudo apt install sqlmap"}, args_template="-u {target} --batch",
               requires_auth=True, note="Активно взаимодействует с БД сайта. Запуск только с разрешения."),
    ]),

    Category("Wi-Fi", "Аудит беспроводных сетей (только с разрешения!)", [
        Action("Показать Wi-Fi сети рядом (iwlist)",
               "Список доступных беспроводных сетей.",
               "Сканирует эфир и показывает сети вокруг: имена, каналы, тип защиты. Просто осмотреться.",
               "", binary="iwlist",
               install={"apt": "sudo apt install wireless-tools"}, args_template="scanning", needs_root=True),
        Action("Аудит защищённости Wi-Fi (wifite)",
               "Проверяет стойкость ближайших сетей.",
               "Комбайн для проверки Wi-Fi. Запускать можно ТОЛЬКО на своей сети. Нужен адаптер с режимом мониторинга.",
               "", binary="wifite",
               install={"apt": "sudo apt install wifite"}, args_template="",
               requires_auth=True, needs_root=True, interactive=True,
               note="Интерактивный инструмент — вывод не сохраняется в файл."),
    ]),

    Category("Хеши, пароли и CTF", "Работа с хешами и файлами (легально: свои/CTF)", [
        Action("Определить тип хеша (hashid)",
               "Подсказывает, что это за хеш.",
               "По виду строки угадывает алгоритм (MD5, SHA1, bcrypt). Нужно, чтобы понять, чем такой хеш подбирать.",
               "Введи хеш", binary="hashid",
               install={"pipx": "pipx install hashid", "apt": "sudo apt install hashid"}, args_template="{target}"),
        Action("Подобрать пароль к хешу (john)",
               "Перебор пароля по словарю.",
               "Берёт файл с хешами и словарь, ищет совпадения. Легально — только для своих хешей и CTF.",
               "Введи путь к файлу с хешами", binary="john",
               install={"apt": "sudo apt install john"},
               args_template="--wordlist=/usr/share/wordlists/rockyou.txt {target}",
               requires_auth=True, note="Словарь rockyou.txt есть на Kali (иногда как .gz — распакуй)."),
        Action("Читаемые строки из файла (strings)",
               "Достаёт текст из любого файла.",
               "Вытаскивает все читаемые строки из бинарного файла или дампа. Первое, что делают в CTF с непонятным файлом.",
               "Введи путь к файлу", binary="strings",
               install={"apt": "sudo apt install binutils"}, args_template="{target}"),
        Action("Анализ файла на вложения (binwalk)",
               "Ищет спрятанные файлы внутри файла.",
               "Просматривает файл (образ, картинку) и находит внутри другие файлы и сжатые данные. Классика CTF.",
               "Введи путь к файлу", binary="binwalk",
               install={"apt": "sudo apt install binwalk"}, args_template="{target}"),
        Action("Извлечь скрытое из картинки (steghide)",
               "Достаёт данные, спрятанные в изображении.",
               "Пытается извлечь данные, спрятанные в картинке/аудио методом стеганографии. Спросит пароль.",
               "Введи путь к файлу", binary="steghide",
               install={"apt": "sudo apt install steghide"}, args_template="extract -sf {target}",
               interactive=True, note="Интерактивно спросит пароль — вывод не сохраняется."),
    ]),

    Category("Утилиты", "Встроенные функции — работают без установки", [
        Action("Base64: закодировать", "Текст → Base64.",
               "Превращает обычный текст в Base64. Часто нужно с токенами и веб-запросами.",
               "Введи текст", func=fn_b64_encode),
        Action("Base64: раскодировать", "Base64 → текст.",
               "Обратное действие: Base64 назад в читаемый текст.",
               "Введи строку Base64", func=fn_b64_decode),
        Action("HEX: закодировать", "Текст → шестнадцатеричный вид.",
               "Переводит текст в hex-представление байтов. Пригодится в реверсе и веб-задачах.",
               "Введи текст", func=fn_hex_encode),
        Action("HEX: раскодировать", "HEX → текст.",
               "Переводит hex-строку обратно в текст.",
               "Введи hex-строку", func=fn_hex_decode),
        Action("URL: закодировать", "Текст → безопасный для URL вид.",
               "Экранирует спецсимволы, чтобы строку можно было вставить в адрес.",
               "Введи текст", func=fn_url_encode),
        Action("URL: раскодировать", "URL-строка → обычный текст.",
               "Возвращает %20 и подобное обратно в нормальные символы.",
               "Введи URL-строку", func=fn_url_decode),
        Action("ROT13", "Простой шифр сдвига на 13.",
               "Сдвигает каждую букву на 13 позиций. Классическая CTF-разминка.",
               "Введи текст", func=fn_rot13),
        Action("Шифр Цезаря: все сдвиги", "Показывает все 25 вариантов.",
               "Выводит текст при всех сдвигах 1–25 — глазами находишь читаемый. Частая CTF-задача.",
               "Введи текст", func=fn_caesar_all),
        Action("Хеши строки", "MD5, SHA1 и SHA256 текста.",
               "Считает три популярных хеша от введённого текста.",
               "Введи текст", func=fn_hashes),
        Action("Хеш файла", "MD5 и SHA256 файла.",
               "Считает хеши файла — так проверяют, что скачанное не подменили.",
               "Введи путь к файлу", func=fn_file_hash),
        Action("Декодер JWT", "Читает содержимое JWT-токена.",
               "Разбирает JWT и показывает header и payload. Подпись не проверяет — только чтение.",
               "Введи JWT-токен", func=fn_jwt_decode),
        Action("Генератор пароля", "Надёжный случайный пароль.",
               "Создаёт криптостойкий случайный пароль. Укажи длину или оставь пусто (20).",
               "Длина (Enter = 20)", func=fn_gen_password),
        Action("Калькулятор подсети (CIDR)", "Диапазон адресов по маске.",
               "По записи вида 192.168.1.0/24 показывает маску, broadcast и диапазон хостов.",
               "Введи подсеть (192.168.1.0/24)", func=fn_cidr),
        Action("Проверить один порт", "Открыт ли порт на хосте.",
               "Пробует подключиться к одному порту и говорит, открыт он или нет.",
               "Введи host:port", func=fn_port_check, requires_auth=True),
        Action("Мой IP и хост", "Локальный адрес этой машины.",
               "Показывает имя хоста и локальный IP твоего компьютера. Безопасно.",
               "", func=fn_my_ip),
    ]),
]


# ============================ СБОР РЕЗУЛЬТАТОВ ============================

RESULTS_DIR = Path.home() / ".voker" / "results"
SESSION = []
SESSION_ID = time.strftime("%Y%m%d_%H%M%S")


def slug(s):
    s = re.sub(r"[^A-Za-z0-9._-]", "_", s or "")
    return s[:40] or "none"


def save_result(action, target, cmd_str, returncode, lines, artifact=None):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = f"{ts}_{slug(action.binary or action.name)}_{slug(target)}"
    txt = RESULTS_DIR / f"{base}.txt"
    header = [
        "Voker — результат команды",
        f"Пункт   : {action.name}",
        f"Цель    : {target or '-'}",
        f"Команда : {cmd_str}",
        f"Код     : {returncode}",
        f"Время   : {ts}",
        "-" * 50,
    ]
    txt.write_text("\n".join(header + lines) + "\n", encoding="utf-8")

    entry = {
        "time": ts, "name": action.name, "tool": action.binary or "built-in",
        "target": target, "command": cmd_str, "exit_code": returncode,
        "lines": len(lines), "txt_file": str(txt),
    }
    if artifact:
        entry["artifact"] = str(artifact)
    SESSION.append(entry)
    js = RESULTS_DIR / f"session_{SESSION_ID}.json"
    js.write_text(json.dumps(SESSION, ensure_ascii=False, indent=2), encoding="utf-8")
    return txt, js


def show_session_table():
    if not SESSION:
        rail(["Пока ничего не собрано."])
        return
    headers = ["Время", "Пункт", "Цель", "Код", "Стр."]
    rows = [[e["time"][-6:], e["name"], e["target"] or "-",
             str(e["exit_code"]), str(e["lines"])] for e in SESSION]
    print_table(headers, rows, caps=[8, 30, 22, 4, 5])
    print(col(f"  Полные результаты: {RESULTS_DIR}", C.GREY))


# ============================ ЗАПУСК КОМАНД ============================

def detect_pkg_manager():
    for pm in ("apt", "pacman", "dnf", "yum", "brew"):
        if shutil.which(pm):
            return pm
    return None


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def show_install_help(action):
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
        print(col("  Другие варианты: " + ", ".join(f"{k}: {v}" for k, v in action.install.items()), C.GREY))
    print(col("  После установки выбери пункт снова.\n", C.GREY))


def build_parts(action, target, outfile=""):
    arg_str = action.args_template
    if arg_str:
        arg_str = arg_str.format(target=target, outfile=outfile)
    parts = [action.binary] + (shlex.split(arg_str) if arg_str else [])
    if action.needs_root and not is_root() and shutil.which("sudo"):
        parts = ["sudo"] + parts
    return parts


def run_and_capture(parts):
    """Запускает процесс, показывает вывод построчно и одновременно собирает его."""
    lines = []
    try:
        proc = subprocess.Popen(parts, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        rail_line(col("Не удалось запустить процесс.", C.RED))
        return 1, ["<не удалось запустить>"]
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            rail_line(line)
            lines.append(line)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        rail_line(col("Прервано пользователем.", C.GREY))
    return proc.returncode, lines


def run_action(action):
    print(col(f"\n  {action.explain}", C.GREY))
    if action.requires_auth:
        print(col("  • активно обращается к цели — только с разрешения", C.GREY))
    if action.note:
        print(col(f"  ℹ  {action.note}", C.GREY))

    # ---- встроенная функция ----
    if action.func is not None:
        target = input(col(f"\n  {action.prompt}: ", C.LILAC)).strip() if action.prompt else ""
        print()
        panel_open(action.name)
        t = time.perf_counter()
        ok = True
        lines = []
        try:
            lines = list(action.func(target))
            rail(lines)
        except Exception as e:
            ok = False
            lines = [f"Ошибка: {e}"]
            rail(lines)
        panel_close(ok, time.perf_counter() - t)
        save_result(action, target, "(встроенная функция)", 0 if ok else 1, lines)
        print()
        show_session_table()
        return

    # ---- внешний инструмент ----
    if not shutil.which(action.binary):
        show_install_help(action)
        return

    target = ""
    if action.prompt:
        target = input(col(f"\n  {action.prompt}: ", C.LILAC)).strip()
        if not target:
            if action.default:
                target = action.default
            else:
                print(col("  Пусто — отмена.", C.GREY))
                return

    outfile = ""
    if action.outfile_ext:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        outfile = str(RESULTS_DIR / f"{ts}_{slug(action.binary)}.{action.outfile_ext}")

    parts = build_parts(action, target, outfile)
    cmd_str = " ".join(shlex.quote(p) for p in parts)
    title = action.name + (f"  ·  {target}" if target else "")
    print()
    panel_open(title)
    t = time.perf_counter()

    if action.interactive:
        # живой ввод — без перехвата, вывод не сохраняем
        ok = True
        try:
            r = subprocess.run(parts)
            ok = (r.returncode == 0)
            rc = r.returncode
        except KeyboardInterrupt:
            ok = False
            rc = 130
            print(col("\n  Прервано.", C.GREY))
        panel_close(ok, time.perf_counter() - t)
        save_result(action, target, cmd_str, rc,
                    ["(интерактивный инструмент — вывод не сохранён)"])
    else:
        rc, lines = run_and_capture(parts)
        ok = (rc == 0)
        panel_close(ok, time.perf_counter() - t)
        artifact = outfile if (outfile and Path(outfile).exists()) else None
        save_result(action, target, cmd_str, rc, lines, artifact=artifact)
        if artifact:
            print(col(f"  💾 Файл сохранён: {artifact}", C.GREEN))
            print(col("     Открой его в Wireshark для анализа.", C.GREY))

    print()
    show_session_table()


# ============================ МЕНЮ ============================

def show_installed():
    print()
    panel_open("Что установлено")
    for cat in TOOLKIT:
        for act in cat.actions:
            if act.func is not None:
                mark, tail = col("✓", C.GREEN), "встроенное"
            elif shutil.which(act.binary):
                mark, tail = col("✓", C.GREEN), act.binary
            else:
                mark, tail = col("✗", C.RED), act.binary + " — не установлен"
            print(col("│ ", C.PURPLE_DEEP) + f"{mark} " + col(act.name, C.LILAC) + col(f"  ({tail})", C.GREY))
    panel_close(True, 0.0)


def category_menu(cat):
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
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(cat.name, C.LILAC) + col(f"  ({len(cat.actions)})", C.GREY))
            print(col(f"       {cat.desc}", C.GREY))
        print(col("\n  [r] Результаты этой сессии", C.GREY))
        print(col("  [i] Проверить установленные инструменты", C.GREY))
        print(col("  [q] Выход", C.GREY))
        choice = input(col("\n  Выбор: ", C.YELLOW)).strip().lower()
        if choice in ("q", "quit", "exit"):
            print(col("\n  До встречи. Учись легально. 💜\n", C.PURPLE_BRIGHT))
            return
        if choice == "i":
            show_installed()
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
            continue
        if choice == "r":
            print()
            panel_open("Результаты сессии")
            show_session_table()
            panel_close(True, 0.0)
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(TOOLKIT):
            category_menu(TOOLKIT[int(choice) - 1])
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ CLI ============================

def print_tree():
    print_banner()
    total = 0
    for cat in TOOLKIT:
        print(col(f"▸ {cat.name}", C.PURPLE_BRIGHT + C.BOLD) + col(f" — {cat.desc}", C.GREY))
        for act in cat.actions:
            total += 1
            if act.func is not None:
                mark, tgt = col("✓", C.GREEN), "встроенное"
            else:
                ok = bool(shutil.which(act.binary))
                mark = col("✓" if ok else "✗", C.GREEN if ok else C.RED)
                tgt = act.binary
            flags = " [auth]" if act.requires_auth else ""
            print(f"    {mark} {act.name} " + col(f"→ {tgt}{flags}", C.GREY))
        print()
    print(col(f"Всего: {total} команд", C.LILAC))


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


if __name__ == "__main__":
    main()
