#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voker 1.0 — понятный проводник по кибербезопасности для начинающих.

Voker не содержит инструменты внутри себя. Он проверяет, установлен ли нужный
инструмент, помогает поставить, запускает его — а вместо непонятной простыни
вывода показывает человеческий отчёт («открыт порт 80 — это веб-сайт») и
сохраняет красивый HTML-отчёт, который открывается в браузере.

Запуск:  python3 voker.py
Список:  python3 voker.py --list
"""

import os
import re
import sys
import json
import time
import html
import shlex
import shutil
import textwrap
import threading
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

# ============================ ЦВЕТА ============================

class C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    PURPLE = "\033[38;5;135m"; PURPLE_BRIGHT = "\033[38;5;177m"
    PURPLE_DEEP = "\033[38;5;99m"; LILAC = "\033[38;5;183m"
    GREY = "\033[38;5;245m"; GREEN = "\033[38;5;114m"
    RED = "\033[38;5;203m"; YELLOW = "\033[38;5;221m"


def _supports_color():
    return not os.environ.get("NO_COLOR") and sys.stdout.isatty()


USE_COLOR = _supports_color()
IS_TTY = sys.stdout.isatty()


def col(text, color):
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
    print(col("  понятный проводник по кибербезопасности  ·  v1.0", C.LILAC))
    print()


# ============================ ПАНЕЛИ ============================

def term_width():
    try:
        return max(48, min(shutil.get_terminal_size().columns, 100))
    except Exception:
        return 80


def _pad(s, width):
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s + " " * (width - len(s))


def panel_card(text, color):
    w = term_width(); inner = w - 4
    print(col("╭" + "─" * (w - 2) + "╮", C.PURPLE_DEEP))
    print(col("│ ", C.PURPLE_DEEP) + col(_pad(text, inner), color) + col(" │", C.PURPLE_DEEP))
    print(col("╰" + "─" * (w - 2) + "╯", C.PURPLE_DEEP))


def panel_open(title):
    panel_card("▸ " + title, C.PURPLE_BRIGHT + C.BOLD)


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

    def bd(l, m, r):
        return l + m.join("─" * (w + 2) for w in widths) + r

    def rw(cells):
        return "│" + "│".join(" " + _fit(c, caps[i]).ljust(widths[i]) + " "
                              for i, c in enumerate(cells)) + "│"

    print(col(bd("╭", "┬", "╮"), C.PURPLE_DEEP))
    print(col(rw(headers), C.PURPLE_BRIGHT + C.BOLD))
    print(col(bd("├", "┼", "┤"), C.PURPLE_DEEP))
    for r in rows:
        print(col(rw(r), C.LILAC))
    print(col(bd("╰", "┴", "╯"), C.PURPLE_DEEP))


# ============================ ОТЧЁТ (структура) ============================

@dataclass
class Report:
    headline: str
    level: str = "info"          # good | info | warn | bad
    bullets: list = field(default_factory=list)   # [(текст, уровень)]
    raw_lines: list = field(default_factory=list)


LEVEL_EMOJI = {"good": "✅", "info": "•", "warn": "⚠️", "bad": "❌"}
LEVEL_COLOR = {"good": C.GREEN, "info": C.LILAC, "warn": C.YELLOW, "bad": C.RED}


def show_report(rep):
    panel_card(rep.headline, LEVEL_COLOR.get(rep.level, C.LILAC) + C.BOLD)
    for text, lvl in rep.bullets:
        e = LEVEL_EMOJI.get(lvl, "•")
        print(col(f"   {e} ", LEVEL_COLOR.get(lvl, C.LILAC)) + col(text, C.LILAC))


# ============================ АНИМАЦИЯ ПРОГРЕССА ============================

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_PCT = re.compile(r"([\d]+(?:\.\d+)?)\s*%\s*done", re.I)
_FRAC = re.compile(r"(?:progress:?\s*\[?)\s*(\d+)\s*/\s*(\d+)", re.I)


def extract_percent(line):
    m = _PCT.search(line)
    if m:
        try:
            return max(0.0, min(100.0, float(m.group(1))))
        except ValueError:
            return None
    m = _FRAC.search(line)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b > 0:
            return max(0.0, min(100.0, a * 100.0 / b))
    return None


def _render_progress(pct, elapsed, i, typical):
    frame = SPIN[i % len(SPIN)]
    t = f"{elapsed:4.0f}s"
    if pct is not None:
        filled = int(pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        line = f"  {frame} [{bar}] {pct:5.1f}%   ·   {t}"
    else:
        hint = f"   ·   {typical}" if typical else ""
        line = f"  {frame} работаю, собираю данные...   ·   {t}{hint}"
    sys.stdout.write("\r" + col(line, C.PURPLE_BRIGHT) + "     ")
    sys.stdout.flush()


def _clear_line():
    sys.stdout.write("\r" + " " * (term_width()) + "\r")
    sys.stdout.flush()


def _kill(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_with_ui(parts, timeout=0, typical=""):
    """Запускает процесс, прячет сырой вывод за анимацию, собирает его.
    Возвращает (код, строки, статус: ok|timeout|interrupted|error)."""
    shared = {"lines": [], "pct": None}
    try:
        proc = subprocess.Popen(parts, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        return 1, ["<не удалось запустить>"], "error"

    def reader():
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                shared["lines"].append(line)
                p = extract_percent(line)
                if p is not None:
                    shared["pct"] = p
        except Exception:
            pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    status = "ok"
    start = time.time()
    i = 0
    if not IS_TTY:
        print(col("  работаю...", C.PURPLE_BRIGHT))
    try:
        while proc.poll() is None:
            el = time.time() - start
            if timeout and el > timeout:
                _kill(proc)
                status = "timeout"
                break
            if IS_TTY:
                _render_progress(shared["pct"], el, i, typical)
                i += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        _kill(proc)
        status = "interrupted"

    th.join(timeout=2)
    if IS_TTY:
        _clear_line()
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, shared["lines"], status


def run_interactive(parts):
    try:
        r = subprocess.run(parts)
        return r.returncode, ("ok" if r.returncode == 0 else "error")
    except KeyboardInterrupt:
        return 130, "interrupted"


# ============================ ПАРСЕРЫ ОТЧЁТОВ ============================

PORTS = {
    21: "FTP (передача файлов)", 22: "SSH (удалённый доступ)",
    23: "Telnet (устаревший доступ)", 25: "SMTP (почта)", 53: "DNS",
    80: "веб-сайт (HTTP)", 110: "POP3 (почта)", 139: "SMB (сеть Windows)",
    143: "IMAP (почта)", 443: "веб-сайт (HTTPS)", 445: "SMB (файлы Windows)",
    3306: "MySQL (база данных)", 3389: "RDP (рабочий стол Windows)",
    5432: "PostgreSQL (база данных)", 8080: "веб-сервер (доп. порт)",
    8443: "веб-сайт HTTPS (доп. порт)",
}


def _all(lines):
    return "\n".join(lines)


def p_generic(target, rc, lines, status):
    if status == "timeout":
        return Report("Не успело завершиться за отведённое время", "warn",
                      [("Показан частичный результат — полный текст в отчёте.", "warn")])
    if status == "interrupted":
        return Report("Прервано вручную", "warn",
                      [("Сохранено то, что успело прийти.", "warn")])
    if rc != 0 and not lines:
        return Report("Команда завершилась с ошибкой", "bad",
                      [("Подробности в техническом выводе отчёта.", "bad")])
    n = len([l for l in lines if l.strip()])
    return Report("Готово", "good", [(f"Получено {n} строк вывода — детали в отчёте.", "info")])


def p_ping(target, rc, lines, status):
    txt = _all(lines)
    loss = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", txt)
    avg = re.search(r"=\s*[\d.]+/([\d.]+)/", txt)
    if loss and float(loss.group(1)) >= 100:
        return Report(f"{target} не отвечает на ping", "warn", [
            ("Хост не ответил. Это не всегда значит, что он выключен —", "info"),
            ("многие серверы специально игнорируют ping.", "info")])
    if loss and float(loss.group(1)) < 100:
        b = [(f"{target} на связи и отвечает.", "good")]
        if avg:
            b.append((f"Среднее время ответа: {float(avg.group(1)):.0f} мс.", "info"))
        if float(loss.group(1)) > 0:
            b.append((f"Часть пакетов потеряна ({loss.group(1)}%) — связь нестабильна.", "warn"))
        return Report(f"{target} доступен", "good", b)
    return p_generic(target, rc, lines, status)


def _parse_nmap_ports(lines):
    open_ports = []
    for l in lines:
        m = re.match(r"\s*(\d+)/tcp\s+open\s+(\S+)(.*)", l)
        if m:
            port = int(m.group(1))
            svc = m.group(2)
            ver = m.group(3).strip()
            open_ports.append((port, svc, ver))
    return open_ports


def _nmap_down(lines):
    t = _all(lines).lower()
    return ("host seems down" in t) or ("0 hosts up" in t) or ("note: host" in t)


def p_nmap_ports(target, rc, lines, status):
    if _nmap_down(lines):
        return Report(f"{target} недоступен или блокирует скан", "warn", [
            ("Хост не отвечает на сканирование. Возможно, он offline", "info"),
            ("или закрыт файрволом.", "info")])
    ports = _parse_nmap_ports(lines)
    if not ports:
        return Report("Открытых портов не найдено", "good", [
            ("Все просканированные порты закрыты — снаружи зацепиться не за что.", "good")])
    lvl = "warn" if len(ports) > 3 else "info"
    b = [(f"Найдено открытых портов: {len(ports)}", lvl)]
    for port, svc, ver in ports:
        human = PORTS.get(port, svc)
        line = f"Порт {port} открыт — {human}"
        if ver:
            line += f"  [{ver}]"
        b.append((line, "info"))
    return Report(f"У {target} есть открытые порты", lvl, b)


def p_nmap_os(target, rc, lines, status):
    txt = _all(lines)
    m = re.search(r"OS details:\s*(.+)", txt) or re.search(r"Running:\s*(.+)", txt)
    if m:
        return Report(f"Похоже на: {m.group(1).strip()}", "info",
                      [("Это предположение nmap по сетевым отпечаткам, не 100%.", "info")])
    if _nmap_down(lines):
        return Report(f"{target} недоступен", "warn", [("Хост не отвечает.", "info")])
    return Report("Не удалось определить ОС", "info",
                  [("nmap не смог уверенно распознать систему.", "info")])


def p_nmap_vuln(target, rc, lines, status):
    n = _all(lines).count("VULNERABLE")
    if n > 0:
        return Report(f"Найдено потенциальных уязвимостей: {n}", "bad", [
            (f"nmap отметил {n} возможных проблем — смотри детали в отчёте.", "bad"),
            ("«Потенциальных» — проверяй вручную, бывают ложные срабатывания.", "warn")])
    if _nmap_down(lines):
        return Report(f"{target} недоступен", "warn", [("Хост не отвечает.", "info")])
    return Report("Явных уязвимостей не найдено", "good",
                  [("Скрипты nmap ничего очевидного не нашли.", "good")])


def p_nmap_hosts(target, rc, lines, status):
    hosts = re.findall(r"Nmap scan report for\s+(\S+)", _all(lines))
    if not hosts:
        return Report("Живых устройств не найдено", "info",
                      [("В указанной сети никто не ответил.", "info")])
    b = [(f"Найдено устройств: {len(hosts)}", "info")]
    for h in hosts[:30]:
        b.append((h, "info"))
    return Report(f"В сети активно {len(hosts)} устройств", "info", b)


def p_whois(target, rc, lines, status):
    txt = _all(lines)
    def find(*keys):
        for k in keys:
            m = re.search(rf"{k}:\s*(.+)", txt, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return None
    reg = find("Registrar")
    created = find("Creation Date", "created")
    org = find("Registrant Organization", "OrgName", "org")
    country = find("Registrant Country", "Country")
    b = []
    if org: b.append((f"Владелец: {org}", "info"))
    if reg: b.append((f"Регистратор: {reg}", "info"))
    if created: b.append((f"Домен создан: {created}", "info"))
    if country: b.append((f"Страна: {country}", "info"))
    if not b:
        return p_generic(target, rc, lines, status)
    return Report(f"Данные по {target}", "info", b)


def p_dig(target, rc, lines, status):
    ips = re.findall(r"\bIN\s+A\s+([\d.]+)", _all(lines))
    mx = re.findall(r"\bIN\s+MX\s+\d+\s+(\S+)", _all(lines))
    b = []
    if ips:
        b.append((f"IP-адрес(а): {', '.join(sorted(set(ips)))}", "info"))
    if mx:
        b.append((f"Почтовые серверы: {', '.join(sorted(set(mx))[:3])}", "info"))
    if not b:
        return Report(f"Для {target} записи не найдены", "info",
                      [("DNS не вернул адресов — проверь имя домена.", "info")])
    return Report(f"DNS домена {target}", "info", b)


def p_ipinfo(target, rc, lines, status):
    try:
        data = json.loads(_all(lines))
    except Exception:
        return p_generic(target, rc, lines, status)
    b = []
    if data.get("city") or data.get("country"):
        loc = ", ".join(x for x in [data.get("city"), data.get("region"), data.get("country")] if x)
        b.append((f"Местоположение: {loc}", "info"))
    if data.get("org"):
        b.append((f"Провайдер/владелец: {data['org']}", "info"))
    if data.get("loc"):
        b.append((f"Координаты: {data['loc']}", "info"))
    if not b:
        return p_generic(target, rc, lines, status)
    return Report(f"Информация по IP {target}", "info", b)


def p_exif(target, rc, lines, status):
    txt = _all(lines)
    gps = re.search(r"GPS Position\s*:\s*(.+)", txt)
    model = re.search(r"Camera Model Name\s*:\s*(.+)", txt) or re.search(r"Model\s*:\s*(.+)", txt)
    date = re.search(r"Create Date\s*:\s*(.+)", txt)
    b = []
    if gps:
        b.append((f"📍 Координаты съёмки: {gps.group(1).strip()}", "warn"))
    if model:
        b.append((f"Камера/устройство: {model.group(1).strip()}", "info"))
    if date:
        b.append((f"Дата создания: {date.group(1).strip()}", "info"))
    if not b:
        return Report("Полезных метаданных не найдено", "info",
                      [("В файле нет GPS/камеры — возможно, их вырезали при загрузке.", "info")])
    lvl = "warn" if gps else "info"
    return Report("Найдены метаданные" + (" с координатами!" if gps else ""), lvl, b)


def p_sherlock(target, rc, lines, status):
    found = re.findall(r"\[\+\]\s*(\S+):\s*(https?://\S+)", _all(lines))
    if not found:
        return Report(f"Аккаунтов с ником «{target}» не найдено", "info",
                      [("Ни на одном из проверенных сайтов совпадений нет.", "info")])
    b = [(f"Найдено аккаунтов: {len(found)} (возможны ложные)", "info")]
    for site, url in found[:25]:
        b.append((f"{site}: {url}", "info"))
    return Report(f"Ник «{target}» встречается на {len(found)} сайтах", "info", b)


def p_theharvester(target, rc, lines, status):
    txt = _all(lines)
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", txt)
    hosts = re.findall(r"\b(?:[\w-]+\.)+[\w-]+\b", txt)
    emails = sorted(set(emails))
    b = [(f"Найдено e-mail: {len(emails)}", "info")]
    for e in emails[:15]:
        b.append((e, "info"))
    if not emails:
        b = [("Почтовых адресов не найдено.", "info")]
    return Report(f"Разведка по {target}", "info", b)


def p_sublist3r(target, rc, lines, status):
    subs = sorted(set(re.findall(rf"\b[\w-]+\.{re.escape(target)}\b", _all(lines))))
    if not subs:
        return Report(f"Поддоменов для {target} не найдено", "info",
                      [("Ничего не нашлось в открытых источниках.", "info")])
    b = [(f"Найдено поддоменов: {len(subs)}", "info")]
    for s in subs[:25]:
        b.append((s, "info"))
    return Report(f"У {target} есть поддомены", "info", b)


def p_traceroute(target, rc, lines, status):
    hops = re.findall(r"^\s*(\d+)\s", _all(lines), re.M)
    n = max((int(h) for h in hops), default=0)
    if n == 0:
        return p_generic(target, rc, lines, status)
    return Report(f"Путь до {target}: {n} промежуточных узлов", "info",
                  [("Полная цепочка серверов — в отчёте.", "info")])


def p_curl_headers(target, rc, lines, status):
    txt = _all(lines)
    st = re.search(r"HTTP/[\d.]+\s+(\d{3})", txt)
    server = re.search(r"^server:\s*(.+)", txt, re.I | re.M)
    b = []
    if st:
        code = st.group(1)
        meaning = {"200": "сайт работает", "301": "переадресация",
                   "302": "переадресация", "403": "доступ запрещён",
                   "404": "страница не найдена", "500": "ошибка сервера"}.get(code, "")
        b.append((f"Код ответа: {code}" + (f" — {meaning}" if meaning else ""),
                  "good" if code == "200" else "warn"))
    if server:
        b.append((f"Сервер: {server.group(1).strip()}", "info"))
    if not b:
        return p_generic(target, rc, lines, status)
    return Report(f"Ответ сайта {target}", b[0][1], b)


def p_whatweb(target, rc, lines, status):
    techs = sorted(set(re.findall(r"([A-Za-z][\w-]+)\[", _all(lines))))
    skip = {"Country", "IP", "HTTPServer"}
    techs = [t for t in techs if t not in skip]
    if not techs:
        return p_generic(target, rc, lines, status)
    return Report(f"Технологии сайта {target}", "info",
                  [("Обнаружено: " + ", ".join(techs[:15]), "info")])


def p_gobuster(target, rc, lines, status):
    found = re.findall(r"(/\S+)\s+\(Status:\s*(\d+)", _all(lines))
    if not found:
        return Report("Скрытых страниц не найдено", "info",
                      [("По словарю ничего живого не нашлось.", "info")])
    b = [(f"Найдено страниц/папок: {len(found)}", "warn")]
    for path, code in found[:25]:
        b.append((f"{path}  (код {code})", "info"))
    return Report(f"На {target} есть скрытые страницы", "warn", b)


def p_nikto(target, rc, lines, status):
    findings = [l for l in lines if l.strip().startswith("+") and "Target" not in l]
    n = len(findings)
    if n == 0:
        return Report("Явных проблем не найдено", "good",
                      [("Базовая проверка ничего очевидного не выявила.", "good")])
    return Report(f"Найдено замечаний: {n}", "warn",
                  [(f"nikto отметил {n} пунктов — детали в отчёте.", "warn"),
                   ("Не все из них критичны, читай внимательно.", "info")])


def p_wpscan(target, rc, lines, status):
    txt = _all(lines)
    ver = re.search(r"WordPress version\s+([\d.]+)", txt)
    vulns = txt.count("[!]")
    b = []
    if ver:
        b.append((f"Версия WordPress: {ver.group(1)}", "info"))
    if vulns:
        b.append((f"Отмечено предупреждений: {vulns}", "warn"))
    if not b:
        return p_generic(target, rc, lines, status)
    return Report(f"Сканер WordPress: {target}", "warn" if vulns else "info", b)


def p_iwlist(target, rc, lines, status):
    ssids = re.findall(r'ESSID:"([^"]*)"', _all(lines))
    enc = re.findall(r"Encryption key:(on|off)", _all(lines))
    ssids = [s for s in ssids if s]
    if not ssids:
        return Report("Сетей рядом не найдено", "info",
                      [("Возможно, адаптер выключен или нет прав.", "info")])
    b = [(f"Найдено сетей: {len(ssids)}", "info")]
    for i, s in enumerate(ssids[:20]):
        lock = "🔒" if (i < len(enc) and enc[i] == "on") else "🔓"
        b.append((f"{lock} {s}", "info"))
    return Report(f"Вокруг {len(ssids)} Wi-Fi сетей", "info", b)


def p_hashid(target, rc, lines, status):
    kinds = [l.strip("[] ").strip() for l in lines if l.strip().startswith("[+]")]
    if not kinds:
        return p_generic(target, rc, lines, status)
    return Report("Возможные типы хеша", "info",
                  [(k, "info") for k in kinds[:8]])


def p_john(target, rc, lines, status):
    cracked = re.findall(r"(\S+)\s+\((\S+)\)", _all(lines))
    if cracked:
        b = [(f"Подобрано паролей: {len(cracked)}", "bad")]
        for pw, who in cracked[:15]:
            b.append((f"{who} → {pw}", "info"))
        return Report("Пароли подобраны!", "bad", b)
    return Report("Пароль пока не подобран", "info",
                  [("По этому словарю совпадений нет. Попробуй другой словарь.", "info")])


def p_smb(target, rc, lines, status):
    txt = _all(lines)
    shares = re.findall(r"^\s*([\w$.-]+)\s+(?:READ|WRITE|READ, WRITE|Disk)", txt, re.M | re.I)
    users = re.findall(r"user:\[([^\]]+)\]", txt, re.I)
    b = []
    if shares:
        b.append((f"Найдено сетевых папок (шар): {len(set(shares))}", "warn"))
        for s in sorted(set(shares))[:15]:
            b.append((f"Папка: {s}", "info"))
    if users:
        b.append((f"Найдено пользователей: {len(set(users))}", "warn"))
        for u in sorted(set(users))[:15]:
            b.append((f"Пользователь: {u}", "info"))
    if not b:
        return p_generic(target, rc, lines, status)
    return Report(f"Перечисление {target}", "warn", b)


def p_holehe(target, rc, lines, status):
    used = re.findall(r"\[\+\]\s*(\S+)", _all(lines))
    if not used:
        return Report(f"Почта {target} нигде явно не найдена", "info",
                      [("Ни один сервис не подтвердил регистрацию.", "info")])
    b = [(f"Почта зарегистрирована на сайтах: {len(used)}", "warn")]
    for s in used[:20]:
        b.append((s, "info"))
    return Report(f"{target} используется на {len(used)} сервисах", "warn", b)


# ============================ ВИЗАРД NMAP ============================
def ask(prompt):
    return input(col(f"\n  {prompt}: ", C.LILAC)).strip()


@dataclass
class ExecSpec:
    parts: list
    target: str
    parser: Callable
    typical: str = ""
    outfile: str = ""
    title: str = ""


def wiz_nmap(action):
    target = pick_target("Введи IP или домен цели")
    if not target:
        return None
    print(col("\n  Что хочешь узнать про цель?", C.LILAC))
    print(col("   [1] Какие порты открыты (быстро)", C.GREY))
    print(col("   [2] Какие программы и версии на портах", C.GREY))
    print(col("   [3] Какая операционная система (нужен root)", C.GREY))
    print(col("   [4] Есть ли известные уязвимости (долго)", C.GREY))
    choice = input(col("\n  Выбор [1-4]: ", C.YELLOW)).strip()
    base = ["nmap", "--stats-every", "2s"]
    if choice == "1":
        parts, parser, typ = base + ["-F", target], p_nmap_ports, "10–60 сек"
    elif choice == "2":
        parts, parser, typ = base + ["-sV", target], p_nmap_ports, "30–120 сек"
    elif choice == "3":
        parts, parser, typ = base + ["-O", target], p_nmap_os, "20–90 сек"
        if not is_root() and shutil.which("sudo"):
            parts = ["sudo"] + parts
    elif choice == "4":
        parts, parser, typ = base + ["--script", "vuln", target], p_nmap_vuln, "2–20 минут"
    else:
        print(col("  Нет такого варианта — отмена.", C.RED))
        return None
    return ExecSpec(parts=parts, target=target, parser=parser, typical=typ,
                    title="Скан цели")


# ============================ ЭКСПЛУАТАЦИЯ: hydra / sqlmap ============================
# Подаются как «продвинутый ручной запуск»: показываем шаблон и разбор флагов,
# требуем явно вписать УЧЕБНУЮ цель. Не одна кнопка «атакуй что угодно».

def p_hydra(target, rc, lines, status):
    creds = re.findall(r"login:\s*(\S+)\s+password:\s*(\S+)", _all(lines))
    if creds:
        b = [(f"Подобрано учётных данных: {len(creds)}", "bad")]
        for u, p in creds[:15]:
            b.append((f"{u} : {p}", "info"))
        b.append(("Вот почему слабые пароли и их повторное использование опасны.", "warn"))
        return Report("Учётные данные подобраны!", "bad", b)
    return Report("Пароль не подобран", "info",
                  [("По этому словарю совпадений нет — попробуй другой словарь.", "info")])


def p_sqlmap(target, rc, lines, status):
    t = _all(lines).lower()
    neg = ("not injectable" in t) or ("do not appear to be injectable" in t) \
        or ("all tested parameters do not" in t)
    if neg:
        return Report("SQL-инъекция не найдена", "good",
                      [("Проверенные параметры не уязвимы.", "good")])
    pos = ("is vulnerable" in t) or ("sqlmap identified the following injection" in t) \
        or ("the following injection point" in t)
    if pos:
        dbms = re.search(r"back-end DBMS:\s*(.+)", _all(lines))
        b = [("Параметр уязвим к SQL-инъекции.", "bad")]
        if dbms:
            b.append((f"База данных: {dbms.group(1).strip()}", "info"))
        b.append(("Детали и возможности — в техническом выводе отчёта.", "info"))
        return Report("Найдена SQL-инъекция!", "bad", b)
    return p_generic(target, rc, lines, status)


def _explain(template, flags):
    print(col("\n  Шаблон команды (впиши свою учебную цель):", C.LILAC))
    print(col(f"      {template}", C.GREEN + C.BOLD))
    print(col("\n  Что означает каждый флаг:", C.LILAC))
    for flag, meaning in flags:
        print(col(f"      {flag:16}", C.PURPLE_BRIGHT) + col(meaning, C.GREY))


def wiz_hydra(action):
    _explain(
        "hydra -l ЛОГИН -P СЛОВАРЬ ЦЕЛЬ СЕРВИС",
        [("-l ЛОГИН", "один логин (или -L файл со списком логинов через @файл)"),
         ("-P СЛОВАРЬ", "файл со списком паролей для перебора"),
         ("ЦЕЛЬ", "IP учебной машины (HTB/THM) или своей системы"),
         ("СЕРВИС", "что атакуем: ssh, ftp, http-post-form и т.п.")])
    print(col("\n  Пример для HTB: hydra -l root -P rockyou.txt 10.10.10.5 ssh", C.GREY))

    service = ask("Сервис (ssh / ftp / ...)")
    target = ask("Учебная цель — IP машины HTB/THM или своей системы")
    login = ask("Логин (или @путь/к/файлу для списка логинов)")
    wordlist = ask("Путь к словарю паролей")
    if not (service and target and login and wordlist):
        print(col("  Не хватает данных — отмена.", C.GREY))
        return None
    login_flag = ["-L", login[1:]] if login.startswith("@") else ["-l", login]
    parts = ["hydra"] + login_flag + ["-P", wordlist, target, service]
    print(col("\n  Будет запущено: " + " ".join(shlex.quote(p) for p in parts), C.LILAC))
    return ExecSpec(parts=parts, target=target, parser=p_hydra,
                    typical="от секунд до многих минут", title="Подбор пароля (hydra)")


def wiz_sqlmap(action):
    _explain(
        'sqlmap -u "URL-с-параметром" --batch',
        [("-u URL", "адрес страницы с параметром, например http://ЦЕЛЬ/item?id=1"),
         ("--batch", "не задавать вопросов — брать ответы по умолчанию")])
    print(col("\n  Пример: sqlmap -u \"http://10.10.10.5/item.php?id=1\" --batch", C.GREY))

    url = ask("URL учебной цели с параметром (…?id=1)")
    if not url:
        print(col("  Пусто — отмена.", C.GREY))
        return None
    parts = ["sqlmap", "-u", url, "--batch"]
    print(col("\n  Будет запущено: " + " ".join(shlex.quote(p) for p in parts), C.LILAC))
    return ExecSpec(parts=parts, target=url, parser=p_sqlmap,
                    typical="1–15 минут", title="Тест SQL-инъекции (sqlmap)")


# ============================ МОДЕЛЬ ДАННЫХ ============================

@dataclass
class Action:
    name: str
    desc: str
    explain: str
    prompt: str = ""
    binary: str = ""
    install: dict = field(default_factory=dict)
    args_template: str = ""
    parser: Callable = p_generic
    wizard: Optional[Callable] = None
    typical: str = ""
    requires_auth: bool = False
    needs_root: bool = False
    interactive: bool = False
    outfile_ext: str = ""
    default: str = ""
    timeout: int = 0
    note: str = ""


@dataclass
class Category:
    name: str
    desc: str
    actions: list = field(default_factory=list)
    gated: bool = False        # требует подтверждения при первом входе
    gate_text: str = ""


# ============================ НАБОР ИНСТРУМЕНТОВ (v1.0) ============================

TOOLKIT = [
    Category("Разведка", "Узнать что-то о цели из открытых источников", [
        Action("Кому принадлежит домен/IP", "Владелец, регистратор, дата создания.",
               "Показывает, кто владеет доменом или адресом — как «выписка» на сайт.",
               "Введи домен или IP", binary="whois",
               install={"apt": "sudo apt install whois"}, args_template="{target}",
               parser=p_whois, typical="5–15 сек"),
        Action("Адреса и почта домена", "IP-адреса и почтовые серверы.",
               "Куда «ведёт» домен: на каком IP сайт и через какие серверы идёт почта.",
               "Введи домен", binary="dig",
               install={"apt": "sudo apt install dnsutils"}, args_template="{target} ANY",
               parser=p_dig, typical="5–10 сек"),
        Action("Почты и поддомены компании", "Собирает контакты из открытых баз.",
               "Ищет по домену e-mail адреса и поддомены в поисковиках. Первый шаг разведки.",
               "Введи домен (example.com)", binary="theHarvester",
               install={"pipx": "pipx install theHarvester"},
               args_template="-d {target} -b duckduckgo,bing,crtsh",
               parser=p_theharvester, typical="20–90 сек"),
        Action("Все поддомены сайта", "Находит скрытые поддомены.",
               "Ищет адреса вида mail.site.com, dev.site.com — часто самое интересное там.",
               "Введи домен", binary="sublist3r",
               install={"pipx": "pipx install sublist3r"}, args_template="-d {target}",
               parser=p_sublist3r, typical="30–120 сек"),
        Action("Где находится IP", "Страна, город, провайдер по адресу.",
               "По IP показывает примерное местоположение и чей это провайдер.",
               "Введи IP-адрес", binary="curl",
               install={"apt": "sudo apt install curl"},
               args_template="-s https://ipinfo.io/{target}",
               parser=p_ipinfo, typical="5 сек"),
        Action("Что спрятано в фото/файле", "Метаданные и GPS-координаты.",
               "Достаёт скрытые данные: камеру, дату и часто координаты, где сделано фото.",
               "Введи путь к файлу (photo.jpg)", binary="exiftool",
               install={"apt": "sudo apt install libimage-exiftool-perl"},
               args_template="{target}", parser=p_exif, typical="5 сек"),
        Action("Найти ник в соцсетях", "Где занят такой же username.",
               "Проверяет сотни сайтов: где зарегистрирован такой никнейм.",
               "Введи никнейм", binary="sherlock",
               install={"pipx": "pipx install sherlock-project"}, args_template="{target}",
               parser=p_sherlock, typical="1–3 минуты"),
        Action("Где засветилась почта (holehe)", "На каких сайтах есть аккаунт.",
               "По e-mail проверяет, на каких сервисах он зарегистрирован — сильный "
               "OSINT-приём для профилирования.",
               "Введи e-mail", binary="holehe",
               install={"pipx": "pipx install holehe"}, args_template="{target}",
               parser=p_holehe, timeout=300, typical="30–90 сек"),
    ]),

    Category("Сеть", "Проверить хост и сеть", [
        Action("Доступен ли хост", "Отвечает ли машина и как быстро.",
               "Простой вопрос: «эта цель сейчас онлайн и на связи?».",
               "Введи IP или домен", binary="ping",
               install={"apt": "sudo apt install iputils-ping"},
               args_template="-c 4 {target}", parser=p_ping, typical="5–15 сек"),
        Action("Проверить цель (умный скан)", "Мастер: сам подберёт настройки nmap.",
               "Спросит, что ты хочешь узнать, и сам настроит сканирование цели.",
               binary="nmap", install={"apt": "sudo apt install nmap"},
               wizard=wiz_nmap, requires_auth=True, timeout=1800),
        Action("Кто есть в моей сети", "Список активных устройств рядом.",
               "Показывает все включённые устройства в указанной локальной сети.",
               "Введи сеть (192.168.1.0/24)", binary="nmap",
               install={"apt": "sudo apt install nmap"}, args_template="-sn {target}",
               parser=p_nmap_hosts, requires_auth=True, typical="10–40 сек"),
        Action("Путь до сайта", "Через какие узлы идёт соединение.",
               "Показывает цепочку серверов между тобой и целью.",
               "Введи IP или домен", binary="traceroute",
               install={"apt": "sudo apt install traceroute"}, args_template="{target}",
               parser=p_traceroute, typical="10–30 сек"),
        Action("Записать трафик для Wireshark", "Сохраняет 200 пакетов в .pcap.",
               "Ловит сетевые пакеты и сохраняет в файл, который открывается в Wireshark.",
               "Интерфейс (Enter = any)", binary="tcpdump",
               install={"apt": "sudo apt install tcpdump"},
               args_template="-i {target} -c 200 -w {outfile}",
               parser=p_generic, needs_root=True, outfile_ext="pcap", default="any",
               typical="зависит от трафика"),
        Action("Общие папки и юзеры Windows (smbmap)", "Что расшарено по SMB.",
               "Перечисляет сетевые папки Windows/Samba и права на них — этап "
               "перечисления перед доступом к системе.",
               "Введи IP цели", binary="smbmap",
               install={"apt": "sudo apt install smbmap", "pipx": "pipx install smbmap"},
               args_template="-H {target}", parser=p_smb, requires_auth=True, typical="10–40 сек"),
        Action("Перечисление Windows-сети (enum4linux-ng)", "Юзеры, группы, шары.",
               "Собирает максимум о цели по SMB: пользователей, группы, папки. "
               "Классический этап перечисления Active Directory/Windows.",
               "Введи IP цели", binary="enum4linux-ng",
               install={"apt": "sudo apt install enum4linux-ng", "pipx": "pipx install enum4linux-ng"},
               args_template="-A {target}", parser=p_smb, requires_auth=True, timeout=600,
               typical="30–120 сек"),
    ]),

    Category("Веб", "Изучить сайт", [
        Action("Как отвечает сайт", "Код ответа и тип сервера.",
               "Прощупывает сайт: работает ли он, что за сервер — ничего не ломая.",
               "Введи URL (https://example.com)", binary="curl",
               install={"apt": "sudo apt install curl"}, args_template="-I {target}",
               parser=p_curl_headers, requires_auth=True, typical="5 сек"),
        Action("На чём сделан сайт", "CMS, сервер, библиотеки.",
               "Определяет технологии сайта: WordPress, сервер и прочее.",
               "Введи URL или домен", binary="whatweb",
               install={"apt": "sudo apt install whatweb"}, args_template="{target}",
               parser=p_whatweb, requires_auth=True, typical="10–30 сек"),
        Action("Найти скрытые страницы", "Ищет непубличные адреса сайта.",
               "По словарю проверяет тысячи адресов (/admin, /backup) и находит существующие.",
               "Введи URL сайта", binary="gobuster",
               install={"apt": "sudo apt install gobuster"},
               args_template="dir -u {target} -w /usr/share/wordlists/dirb/common.txt",
               parser=p_gobuster, requires_auth=True, timeout=900, typical="1–10 минут",
               note="Словарь по этому пути есть на Kali; на другой ОС укажи свой."),
        Action("Базовая проверка сайта", "Ищет типовые проблемы и мисконфиги.",
               "Проверяет сайт по списку известных проблем. Обзорный скан.",
               "Введи URL сайта", binary="nikto",
               install={"apt": "sudo apt install nikto"}, args_template="-h {target}",
               parser=p_nikto, requires_auth=True, timeout=1200, typical="2–15 минут"),
        Action("Проверить WordPress", "Версии, плагины и их проблемы.",
               "Если сайт на WordPress — сверяет версии темы и плагинов с базой уязвимостей.",
               "Введи URL WordPress-сайта", binary="wpscan",
               install={"apt": "sudo apt install wpscan"}, args_template="--url {target}",
               parser=p_wpscan, requires_auth=True, timeout=1200, typical="1–10 минут"),
    ]),

    Category("Wi-Fi", "Беспроводные сети (только с разрешения!)", [
        Action("Показать сети рядом", "Список Wi-Fi вокруг и их защита.",
               "Сканирует эфир и показывает сети: имена и есть ли пароль.",
               "", binary="iwlist",
               install={"apt": "sudo apt install wireless-tools"},
               args_template="scanning", parser=p_iwlist, needs_root=True, typical="5–15 сек"),
        Action("Аудит своей Wi-Fi сети", "Проверка стойкости защиты.",
               "Комбайн для проверки Wi-Fi. Запускать ТОЛЬКО на своей сети. Нужен спец. адаптер.",
               "", binary="wifite", install={"apt": "sudo apt install wifite"},
               args_template="", requires_auth=True, needs_root=True, interactive=True,
               note="Интерактивный инструмент — работает в своём окне, отчёт не формируется."),
    ]),

    Category("Хеши и пароли", "Работа с хешами (свои / CTF)", [
        Action("Что это за хеш", "Определяет тип хеша.",
               "По виду строки угадывает алгоритм — чтобы понять, чем его подбирать.",
               "Введи хеш", binary="hashid",
               install={"pipx": "pipx install hashid"}, args_template="{target}",
               parser=p_hashid, typical="1 сек"),
        Action("Подобрать пароль к хешу", "Перебор по словарю (свои/CTF).",
               "Берёт файл с хешами и словарь, ищет совпадения. Только для своих хешей и CTF.",
               "Введи путь к файлу с хешами", binary="john",
               install={"apt": "sudo apt install john"},
               args_template="--wordlist=/usr/share/wordlists/rockyou.txt {target}",
               parser=p_john, requires_auth=True, timeout=900, typical="от секунд до минут",
               note="Словарь rockyou.txt есть на Kali (иногда как .gz — распакуй)."),
    ]),

    Category("Эксплуатация", "Активные инструменты — ТОЛЬКО полигоны и CTF",
             gated=True,
             gate_text=(
                 "Здесь инструменты, которые атакуют цель напрямую: подбор паролей "
                 "и SQL-инъекции. Применять их к чужим системам без письменного "
                 "разрешения — уголовное преступление.\n"
                 "  Запускай ТОЛЬКО на учебных площадках (HackTheBox, TryHackMe, "
                 "DVWA) или на своих системах."),
             actions=[
        Action("Подбор пароля к сервису (hydra)", "Ручной запуск с разбором флагов.",
               "Перебирает пароли к сервису (ssh, ftp, веб-формы). Покажу шаблон и "
               "объясню каждый флаг — цель вписываешь сам.",
               binary="hydra", install={"apt": "sudo apt install hydra"},
               wizard=wiz_hydra, requires_auth=True, timeout=1800),
        Action("Тест SQL-инъекции (sqlmap)", "Ручной запуск с разбором флагов.",
               "Проверяет параметр сайта на SQL-инъекцию. Покажу шаблон и объясню "
               "флаги — URL учебной цели вписываешь сам.",
               binary="sqlmap", install={"apt": "sudo apt install sqlmap"},
               wizard=wiz_sqlmap, requires_auth=True, timeout=1800),
    ]),
]


# ============================ РЕЗУЛЬТАТЫ / HTML ============================

RESULTS_DIR = Path.home() / ".voker" / "results"
SESSION = []
SESSION_ID = time.strftime("%Y%m%d_%H%M%S")

LEVEL_HTML = {"good": ("#3ad29f", "✅"), "info": ("#b39ddb", "ℹ️"),
              "warn": ("#ffd166", "⚠️"), "bad": ("#ef5350", "❌")}

HTML_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;
background:#14101c;color:#e8e3f0;padding:24px}
.wrap{max-width:820px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.logo{font-size:22px;font-weight:700;color:#b39ddb}
.ts{color:#8a80a0;font-size:13px}
.verdict{display:flex;gap:16px;align-items:center;background:#1e1830;
border-left:6px solid #b39ddb;border-radius:12px;padding:18px 20px;margin-bottom:18px}
.verdict .emoji{font-size:34px}
.hl{font-size:20px;font-weight:700}
.sub{color:#9b90b5;font-size:14px;margin-top:4px}
ul.bul{list-style:none;padding:0;margin:0 0 18px}
ul.bul li{background:#1a1526;border-radius:8px;padding:10px 14px;margin-bottom:8px;
border-left:3px solid #6c5b8c}
ul.bul li.warn{border-left-color:#ffd166}
ul.bul li.bad{border-left-color:#ef5350}
ul.bul li.good{border-left-color:#3ad29f}
details{background:#1a1526;border-radius:8px;padding:12px 14px;margin-bottom:18px}
summary{cursor:pointer;color:#b39ddb}
pre{overflow-x:auto;color:#c9c0dc;font-size:13px;white-space:pre-wrap;margin:12px 0 0}
.meta{color:#8a80a0;font-size:13px;margin-bottom:10px}
.meta code{background:#231b34;padding:2px 6px;border-radius:5px;color:#cbb8ea}
.foot{color:#6f6588;font-size:12px;border-top:1px solid #2a2340;padding-top:12px;margin-top:20px}
"""


def _html_report(action, spec, rc, status, rep, ts):
    color, emoji = LEVEL_HTML.get(rep.level, LEVEL_HTML["info"])
    bullets = "".join(
        f'<li class="{lvl}">{html.escape(t)}</li>' for t, lvl in rep.bullets
    ) or "<li>Нет данных</li>"
    raw = html.escape("\n".join(rep.raw_lines)) or "(вывод пуст)"
    cmd = html.escape(" ".join(shlex.quote(p) for p in spec.parts))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voker — {html.escape(action.name)}</title><style>{HTML_CSS}</style></head>
<body><div class="wrap">
<div class="head"><span class="logo">💜 Voker</span><span class="ts">{ts}</span></div>
<div class="verdict" style="border-left-color:{color}">
  <div class="emoji">{emoji}</div>
  <div><div class="hl">{html.escape(rep.headline)}</div>
  <div class="sub">{html.escape(action.name)} · цель: {html.escape(spec.target or '—')}</div></div>
</div>
<ul class="bul">{bullets}</ul>
<details><summary>Показать технический вывод</summary><pre>{raw}</pre></details>
<div class="meta">Команда: <code>{cmd}</code><br>Код: {rc} · Статус: {status}</div>
<div class="foot">Voker · только для легального использования с разрешения владельца цели</div>
</div></body></html>"""


def save_result(action, spec, rc, status, rep):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{stamp}_{slug(action.binary or action.name)}_{slug(spec.target)}"

    txt = RESULTS_DIR / f"{base}.txt"
    txt.write_text(
        f"{action.name} | цель: {spec.target} | статус: {status} | код: {rc}\n"
        + "-" * 50 + "\n" + "\n".join(rep.raw_lines) + "\n", encoding="utf-8")

    htmlf = RESULTS_DIR / f"{base}.html"
    htmlf.write_text(_html_report(action, spec, rc, status, rep, ts), encoding="utf-8")

    SESSION.append({
        "time": stamp, "name": action.name, "target": spec.target or "-",
        "status": status, "headline": rep.headline, "level": rep.level,
        "bullets": rep.bullets, "html": str(htmlf), "txt": str(txt),
    })
    js = RESULTS_DIR / f"session_{SESSION_ID}.json"
    js.write_text(json.dumps(SESSION, ensure_ascii=False, indent=2), encoding="utf-8")
    return txt, htmlf


def slug(s):
    s = re.sub(r"[^A-Za-z0-9._-]", "_", s or "")
    return s[:40] or "none"


def show_session_table():
    if not SESSION:
        print(col("  Пока ничего не собрано.", C.GREY))
        return
    rows = [[e["time"][-6:], e["name"], e["target"], e["status"]] for e in SESSION]
    print_table(["Время", "Что делали", "Цель", "Статус"], rows, caps=[8, 32, 24, 11])
    print(col(f"  Отчёты (HTML) лежат в: {RESULTS_DIR}", C.GREY))


def build_session_html():
    if not SESSION:
        return None
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cards = ""
    for e in SESSION:
        color, emoji = LEVEL_HTML.get(e["level"], LEVEL_HTML["info"])
        bl = "".join(f'<li class="{lvl}">{html.escape(t)}</li>' for t, lvl in e["bullets"])
        cards += f"""<div class="verdict" style="border-left-color:{color}">
<div class="emoji">{emoji}</div><div><div class="hl">{html.escape(e['headline'])}</div>
<div class="sub">{html.escape(e['name'])} · цель: {html.escape(e['target'])} · {e['time'][-6:]}</div>
</div></div><ul class="bul">{bl}</ul>"""
    ts = time.strftime("%Y-%m-%d %H:%M")
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voker — отчёт сессии</title><style>{HTML_CSS}</style></head>
<body><div class="wrap"><div class="head"><span class="logo">💜 Voker · отчёт сессии</span>
<span class="ts">{ts}</span></div>{cards}
<div class="foot">Voker · только для легального использования с разрешения владельца</div>
</div></body></html>"""
    path = RESULTS_DIR / f"session_{SESSION_ID}.html"
    path.write_text(doc, encoding="utf-8")
    return path


# ============================ ЗАПУСК ============================

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
    print(col("  Установи так:", C.LILAC))
    print(col(f"      {chosen}", C.GREEN + C.BOLD))
    print(col("  Потом выбери пункт снова.\n", C.GREY))


def build_parts(action, target, outfile=""):
    arg_str = action.args_template.format(target=target, outfile=outfile) if action.args_template else ""
    parts = [action.binary] + (shlex.split(arg_str) if arg_str else [])
    if action.needs_root and not is_root() and shutil.which("sudo"):
        parts = ["sudo"] + parts
    return parts


def run_action(action):
    print(col(f"\n  {action.explain}", C.GREY))
    if action.requires_auth:
        print(col("  ⚠  АКТИВНО ОБРАЩАЕТСЯ К ЦЕЛИ — только с разрешения владельца",
                  C.RED + C.BOLD))
    if action.note:
        print(col(f"  ℹ  {action.note}", C.GREY))

    if action.binary and not shutil.which(action.binary):
        show_install_help(action)
        return
    if action.needs_root and not is_root() and not shutil.which("sudo"):
        print(col("\n  ✗ Нужны root-права, а sudo не найден.", C.RED + C.BOLD))
        print(col("    Запусти Voker от root и повтори.", C.GREY))
        return

    # собираем спецификацию запуска
    if action.wizard:
        spec = action.wizard(action)
        if not spec:
            return
    else:
        target = ""
        if action.prompt:
            target = pick_target(action.prompt)
            if not target:
                if action.default:
                    target = action.default
                else:
                    print(col("  Пусто — отмена.", C.GREY))
                    return
        outfile = ""
        if action.outfile_ext:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            outfile = str(RESULTS_DIR / f"{stamp}_{slug(action.binary)}.{action.outfile_ext}")
        spec = ExecSpec(parts=build_parts(action, target, outfile), target=target,
                        parser=action.parser, typical=action.typical,
                        outfile=outfile, title=action.name)

    # выполняем
    # scope-guard: активные действия не должны бить вне разрешённых доменов
    if action.requires_auth and spec.target and not in_scope(spec.target):
        print(col("\n  ⛔ ЦЕЛЬ ВНЕ SCOPE", C.RED + C.BOLD))
        print(col(f"     {host_of(spec.target)} нет в списке разрешённых доменов.", C.YELLOW))
        print(col("     В баг-баунти выход за scope = бан из программы или хуже.", C.YELLOW))
        print(col(f"     Текущий scope: {', '.join(sorted(SCOPE)) or '(пусто)'}", C.GREY))
        ans = input(col("     Всё равно запустить? Введи 'ВНЕ SCOPE': ", C.YELLOW)).strip().upper()
        if ans != "ВНЕ SCOPE":
            print(col("     Отменено — цель вне scope.", C.GREY))
            return

    title = spec.title + (f"  ·  {spec.target}" if spec.target else "")
    print()
    panel_open(title)

    if action.interactive:
        rc, status = run_interactive(spec.parts)
        rep = Report("Готово" if status == "ok" else "Прервано", "info",
                     [("Инструмент работал в своём окне — отчёт не формируется.", "info")])
    else:
        rc, lines, status = run_with_ui(spec.parts, timeout=action.timeout, typical=spec.typical)
        rep = spec.parser(spec.target, rc, lines, status)
        rep.raw_lines = lines
        if status in ("timeout", "interrupted"):
            rep.bullets.insert(0, ("Показан частичный результат — команда не завершилась полностью.", "warn"))
        if status == "ok":
            msg = harvest_assets(spec.parser, spec.target, lines)
            if msg:
                rep.bullets.append((msg, "good"))

    print()
    show_report(rep)
    txt, htmlf = save_result(action, spec, rc, status, rep)
    print(col(f"\n  📄 Красивый отчёт: {htmlf}", C.GREEN))
    print(col(f"     Открыть: xdg-open \"{htmlf}\"", C.GREY))
    if spec.outfile and Path(spec.outfile).exists():
        print(col(f"  💾 Файл трафика: {spec.outfile}  (открой в Wireshark)", C.GREEN))
    print()
    show_session_table()


# ============================ SCOPE-GUARD ============================

SCOPE_FILE = Path.home() / ".voker" / "scope.txt"
SCOPE = set()


def load_scope():
    SCOPE.clear()
    if SCOPE_FILE.exists():
        for line in SCOPE_FILE.read_text(encoding="utf-8").splitlines():
            d = line.strip().lower()
            if d:
                SCOPE.add(d)


def save_scope():
    SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_FILE.write_text("\n".join(sorted(SCOPE)) + "\n", encoding="utf-8")


def host_of(target):
    import urllib.parse
    t = (target or "").strip()
    if "://" in t:
        t = urllib.parse.urlparse(t).netloc
    t = t.split("/")[0].split(":")[0]
    return t.lower()


def in_scope(target):
    if not SCOPE:
        return True                 # scope не задан — ограничений нет
    h = host_of(target)
    return any(h == d or h.endswith("." + d) for d in SCOPE)


def scope_menu():
    while True:
        print()
        panel_open("Scope — разрешённые домены")
        if SCOPE:
            for d in sorted(SCOPE):
                print(col("   ✓ ", C.GREEN) + col(d, C.LILAC))
        else:
            print(col("   (пусто — ограничений нет, активные команды бьют по любой цели)", C.YELLOW))
        print(col("\n  Пока scope задан, команды вне него блокируются.", C.GREY))
        print(col("\n  [1] Добавить домен", C.GREY))
        print(col("  [2] Очистить scope", C.GREY))
        print(col("  [0] Назад", C.GREY))
        ch = input(col("\n  Выбор: ", C.YELLOW)).strip()
        if ch == "0":
            return
        if ch == "1":
            d = input(col("  Домен из scope программы (example.com): ", C.LILAC)).strip().lower()
            d = host_of(d)
            if d:
                SCOPE.add(d)
                save_scope()
                print(col(f"  Добавлено: {d}", C.GREEN))
        elif ch == "2":
            SCOPE.clear()
            save_scope()
            print(col("  Scope очищен.", C.GREY))


# ============================ ИНВЕНТАРЬ АКТИВОВ ============================
# Общее хранилище найденного: команды его наполняют, следующие — берут цель оттуда.

INV_FILE = Path.home() / ".voker" / "inventory.json"
INVENTORY = {"subdomains": [], "hosts": [], "ips": [], "urls": [], "findings": []}


def load_inventory():
    if INV_FILE.exists():
        try:
            data = json.loads(INV_FILE.read_text(encoding="utf-8"))
            for k in INVENTORY:
                INVENTORY[k] = list(data.get(k, []))
        except Exception:
            pass


def save_inventory():
    INV_FILE.parent.mkdir(parents=True, exist_ok=True)
    INV_FILE.write_text(json.dumps(INVENTORY, ensure_ascii=False, indent=2), encoding="utf-8")


def inv_add(kind, items):
    if kind not in INVENTORY:
        return 0
    n = 0
    for it in items:
        it = (it or "").strip()
        if it and it not in INVENTORY[kind]:
            INVENTORY[kind].append(it)
            n += 1
    if n:
        save_inventory()
    return n


def inv_pickable():
    """Цели, которые можно подставить в следующую команду (свежие сверху)."""
    seen, out = set(), []
    for it in reversed(INVENTORY["ips"] + INVENTORY["hosts"] + INVENTORY["subdomains"]):
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def harvest_assets(parser, target, lines):
    """После команды вытаскивает активы в инвентарь. Возвращает сообщение или ''."""
    txt = "\n".join(lines)
    added = {}
    if parser is p_subfinder:
        added["subdomains"] = inv_add("subdomains", [l.strip() for l in lines if l.strip() and "." in l])
    elif parser is p_httpx:
        added["hosts"] = inv_add("hosts", [l.strip() for l in lines if l.strip().startswith("http")])
    elif parser is p_gau:
        added["urls"] = inv_add("urls", [l.strip() for l in lines if l.strip().startswith("http")])
    elif parser is p_nmap_ports:
        ips = re.findall(r"Nmap scan report for \S+ \(([\d.]+)\)", txt) or \
              re.findall(r"Nmap scan report for ([\d.]+)", txt)
        added["ips"] = inv_add("ips", ips or ([target] if target else []))
    elif parser is p_nmap_hosts:
        found = re.findall(r"Nmap scan report for (\S+)", txt)
        added["ips"] = inv_add("ips", [f for f in found if re.match(r"[\d.]+$", f)])
        added["hosts"] = inv_add("hosts", [f for f in found if not re.match(r"[\d.]+$", f)])
    elif parser is p_dig:
        added["ips"] = inv_add("ips", re.findall(r"\bIN\s+A\s+([\d.]+)", txt))
    elif parser is p_nuclei:
        added["findings"] = inv_add("findings",
            [l.strip() for l in lines if re.search(r"\[(critical|high|medium|low|info)\]", l, re.I)])
    total = sum(v for v in added.values() if v)
    if total:
        parts = [f"{v} {k}" for k, v in added.items() if v]
        return f"➕ В инвентарь добавлено: {', '.join(parts)}"
    return ""


def pick_target(prompt):
    """Спрашивает цель, но сперва предлагает выбрать из инвентаря."""
    picks = inv_pickable()
    if not picks:
        return ask(prompt)
    print(col(f"\n  {prompt}", C.LILAC))
    print(col("  или выбери из найденного ранее:", C.GREY))
    for i, a in enumerate(picks[:10], 1):
        print(col(f"   [{i}] ", C.PURPLE_BRIGHT) + col(a, C.LILAC))
    raw = input(col("  Номер из списка или впиши цель: ", C.YELLOW)).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(picks[:10]):
        return picks[int(raw) - 1]
    return raw


def inventory_menu():
    while True:
        print()
        panel_open("Инвентарь активов")
        empty = True
        labels = {"subdomains": "Поддомены", "hosts": "Живые хосты",
                  "ips": "IP-адреса", "urls": "Архивные URL", "findings": "Находки"}
        for k, label in labels.items():
            items = INVENTORY[k]
            if items:
                empty = False
                print(col(f"\n  {label} ({len(items)}):", C.PURPLE_BRIGHT))
                for it in items[:15]:
                    print(col("   • ", C.PURPLE_DEEP) + col(it, C.LILAC))
                if len(items) > 15:
                    print(col(f"   … ещё {len(items) - 15}", C.GREY))
        if empty:
            print(col("\n  Пусто. Запусти разведку — найденное будет копиться здесь", C.YELLOW))
            print(col("  и предлагаться как цель в следующих командах.", C.YELLOW))
        print(col("\n  [1] Очистить инвентарь", C.GREY))
        print(col("  [0] Назад", C.GREY))
        ch = input(col("\n  Выбор: ", C.YELLOW)).strip()
        if ch == "0":
            return
        if ch == "1":
            for k in INVENTORY:
                INVENTORY[k] = []
            save_inventory()
            print(col("  Инвентарь очищен.", C.GREY))


# ============================ ПАРСЕРЫ BUG BOUNTY ============================

def p_subfinder(target, rc, lines, status):
    subs = sorted(set(l.strip() for l in lines if l.strip() and "." in l))
    if not subs:
        return Report(f"Поддоменов для {target} не найдено", "info",
                      [("Ничего не нашлось.", "info")])
    b = [(f"Найдено поддоменов: {len(subs)}", "info")]
    for s in subs[:30]:
        b.append((s, "info"))
    return Report(f"У {target} найдено {len(subs)} поддоменов", "info", b)


def p_httpx(target, rc, lines, status):
    live = [l.strip() for l in lines if l.strip().startswith("http")]
    if not live:
        return Report("Живых хостов не найдено", "info", [("Никто не ответил по HTTP(S).", "info")])
    b = [(f"Живых веб-хостов: {len(live)}", "info")]
    for u in live[:30]:
        b.append((u, "info"))
    return Report(f"Отвечает {len(live)} хостов", "info", b)


def p_gau(target, rc, lines, status):
    urls = sorted(set(l.strip() for l in lines if l.strip().startswith("http")))
    if not urls:
        return Report("Архивных URL не найдено", "info", [("Веб-архив ничего не отдал.", "info")])
    b = [(f"Найдено URL в архивах: {len(urls)}", "info"),
         ("Ищи среди них старые API, параметры, .js, забытые пути.", "info")]
    for u in urls[:20]:
        b.append((u, "info"))
    return Report(f"{len(urls)} архивных URL для {target}", "info", b)


def p_ffuf(target, rc, lines, status):
    hits = [l.strip() for l in lines if l.strip() and not l.strip().startswith(":")]
    hits = [l for l in hits if re.search(r"\bStatus:\s*\d+", l) or l.startswith("/")]
    if not hits:
        return Report("Скрытых путей не найдено", "info", [("По словарю ничего живого.", "info")])
    b = [(f"Найдено путей: {len(hits)}", "warn")]
    for h in hits[:25]:
        b.append((h, "info"))
    return Report(f"Найдены скрытые пути на {target}", "warn", b)


def p_nuclei(target, rc, lines, status):
    sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    findings = []
    for l in lines:
        m = re.search(r"\[(critical|high|medium|low|info)\]", l, re.I)
        if m:
            s = m.group(1).lower()
            sev[s] += 1
            findings.append((s, l.strip()))
    total = sum(sev.values())
    if total == 0:
        return Report("Уязвимостей не найдено", "good",
                      [("nuclei не отметил проблем по своим шаблонам.", "good")])
    lvl = "bad" if (sev["critical"] or sev["high"]) else ("warn" if sev["medium"] else "info")
    b = [(f"critical {sev['critical']} · high {sev['high']} · medium {sev['medium']}"
          f" · low {sev['low']} · info {sev['info']}", lvl)]
    for s, line in findings:
        if s in ("critical", "high"):
            b.append((line, "bad"))
    for s, line in findings:
        if s == "medium":
            b.append((line, "warn"))
    return Report(f"nuclei нашёл {total} находок", lvl, b[:22])


# ============================ ИНСТРУМЕНТЫ BUG BOUNTY ============================

BB_TOOLS = [
    Action("Поддомены (subfinder)", "Шаг 1 — найти все поддомены цели.",
           "Масштабно собирает поддомены домена из множества источников. С этого "
           "начинается веб-разведка: чем больше поверхность, тем больше шансов на баг.",
           "Введи домен (in-scope)", binary="subfinder",
           install={"apt": "sudo apt install subfinder"}, args_template="-d {target} -silent",
           parser=p_subfinder, requires_auth=True, typical="20–90 сек"),
    Action("Живые хосты (httpx)", "Шаг 2 — какие из поддоменов отвечают.",
           "Проверяет, какие хосты реально живы по HTTP(S). Дальше работаем только "
           "с живыми — остальные тратят время.",
           "Введи домен или хост", binary="httpx",
           install={"apt": "sudo apt install httpx-toolkit"},
           args_template="-u {target} -silent -title -status-code -tech-detect",
           parser=p_httpx, requires_auth=True, typical="10–40 сек",
           note="Это httpx от ProjectDiscovery (не питоновская библиотека)."),
    Action("Архивные URL (gau)", "Шаг 3 — забытые старые адреса из веб-архива.",
           "Достаёт исторические URL цели из Wayback Machine и других архивов. Там "
           "часто лежат старые API, параметры и забытые страницы — золото баг-баунти.",
           "Введи домен (in-scope)", binary="gau",
           install={"go": "go install github.com/lc/gau/v2/cmd/gau@latest"},
           args_template="{target}", parser=p_gau, requires_auth=True, timeout=300,
           typical="20–90 сек"),
    Action("Скрытые пути (ffuf)", "Шаг 4 — перебор непубличных путей.",
           "Подставляет слова из словаря вместо FUZZ и находит скрытые страницы и "
           "эндпоинты, которых нет в ссылках.",
           "URL с FUZZ (https://site/FUZZ)", binary="ffuf",
           install={"apt": "sudo apt install ffuf"},
           args_template="-u {target} -w /usr/share/wordlists/dirb/common.txt -s",
           parser=p_ffuf, requires_auth=True, timeout=900, typical="1–10 минут",
           note="Впиши слово FUZZ в адрес там, где перебирать."),
    Action("Сканер уязвимостей (nuclei)", "Шаг 5 — прогнать по шаблонам уязвимостей.",
           "Главная рабочая лошадь баг-баунти: гоняет тысячи готовых шаблонов "
           "известных уязвимостей и мисконфигов по цели.",
           "Введи URL или домен (in-scope)", binary="nuclei",
           install={"apt": "sudo apt install nuclei"}, args_template="-u {target} -silent",
           parser=p_nuclei, requires_auth=True, timeout=1800, typical="1–15 минут"),
]


# ============================ СЦЕНАРИИ (МЕТОДОЛОГИЯ) ============================

def _step(n, total, title):
    print()
    panel_card(f"Шаг {n}/{total} · {title}", C.PURPLE_BRIGHT + C.BOLD)


def _scenario_step(n, total, stitle, parts, parser, target, typ, raw, bullets, timeout=600):
    """Один шаг сценария: запуск + отчёт + сбор в инвентарь."""
    _step(n, total, stitle)
    if not shutil.which(parts[0]):
        print(col(f"  ⚠ {parts[0]} не установлен — шаг пропущен.", C.YELLOW))
        bullets.append((f"— {stitle}: инструмент не установлен —", "warn"))
        return
    rc, lines, st = run_with_ui(parts, timeout=timeout, typical=typ)
    r = parser(target, rc, lines, st)
    msg = harvest_assets(parser, target, lines)
    if msg:
        print(col("  " + msg, C.GREEN))
    raw.append("")
    raw.append(f"# {stitle}")
    raw.extend([l for l in lines if l.strip()])
    bullets.append((f"— {stitle} —", "info"))
    bullets.extend(r.bullets[:5])


def _finish_scenario(title, target, level, bullets, raw):
    rep = Report(title, level, bullets)
    rep.raw_lines = raw
    print()
    show_report(rep)
    fake = Action(title, "", "", binary="")
    spec = ExecSpec(parts=["scenario", target], target=target, parser=p_generic, title=title)
    _, htmlf = save_result(fake, spec, 0, "ok", rep)
    print(col(f"\n  📄 Отчёт сценария: {htmlf}", C.GREEN))
    print(col(f"     Открыть: xdg-open \"{htmlf}\"", C.GREY))
    print()
    show_session_table()


def scenario_network():
    print(col("\n  Разведка сети: живые хосты → порты и сервисы.", C.GREY))
    subnet = pick_target("Подсеть или IP (192.168.1.0/24)")
    if not subnet:
        return
    if not in_scope(subnet):
        print(col("\n  ⛔ Цель вне scope.", C.RED + C.BOLD))
        return
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    hosts_file = RESULTS_DIR / f"{stamp}_hosts.txt"
    raw, bullets = [], []

    _step(1, 2, "ищу живые устройства (nmap -sn)")
    rc, lines, st = run_with_ui(["nmap", "-sn", subnet], timeout=300, typical="10–40 сек")
    ips = re.findall(r"Nmap scan report for (?:\S+ \()?([\d.]+)\)?", "\n".join(lines))
    ips = sorted(set(ips))
    harvest_assets(p_nmap_hosts, subnet, lines)
    hosts_file.write_text("\n".join(ips) + "\n", encoding="utf-8")
    raw += ["# живые хосты"] + ips
    bullets.append((f"Живых устройств: {len(ips)}", "info"))
    print(col(f"  → живых хостов: {len(ips)}", C.LILAC))
    if not ips:
        _finish_scenario(f"Разведка сети {subnet}", subnet, "info", bullets, raw)
        return

    _step(2, 2, "сканирую порты и сервисы (nmap -sV)")
    rc, lines, st = run_with_ui(["nmap", "-sV", "--top-ports", "50", "-iL", str(hosts_file),
                                 "--stats-every", "3s"], timeout=1800, typical="1–10 минут")
    harvest_assets(p_nmap_ports, subnet, lines)
    r = p_nmap_ports(subnet, rc, lines, st)
    raw += ["", "# порты/сервисы"] + [l for l in lines if l.strip()]
    bullets.extend(r.bullets[:15])
    _finish_scenario(f"Разведка сети {subnet}", subnet, "info", bullets, raw)


def scenario_website():
    print(col("\n  Разведка сайта: инфо о домене → технологии → скрытые страницы.", C.GREY))
    target = pick_target("Домен или URL сайта (in-scope)")
    if not target:
        return
    if not in_scope(target):
        print(col("\n  ⛔ Цель вне scope.", C.RED + C.BOLD))
        return
    dom = host_of(target)
    url = target if target.startswith("http") else "https://" + dom
    raw, bullets = [], []
    _scenario_step(1, 4, "кому принадлежит (whois)", ["whois", dom], p_whois, dom,
                   "5–15 сек", raw, bullets, timeout=60)
    _scenario_step(2, 4, "DNS-записи (dig)", ["dig", dom, "ANY"], p_dig, dom,
                   "5–10 сек", raw, bullets, timeout=60)
    _scenario_step(3, 4, "технологии сайта (whatweb)", ["whatweb", url], p_whatweb, url,
                   "10–30 сек", raw, bullets, timeout=120)
    _scenario_step(4, 4, "скрытые страницы (gobuster)",
                   ["gobuster", "dir", "-u", url, "-w",
                    "/usr/share/wordlists/dirb/common.txt", "-q"],
                   p_gobuster, url, "1–10 минут", raw, bullets, timeout=900)
    _finish_scenario(f"Разведка сайта {dom}", dom, "info", bullets, raw)


def scenario_osint():
    print(col("\n  OSINT по домену: владелец → адреса → поддомены → контакты.", C.GREY))
    dom = pick_target("Домен для OSINT")
    if not dom:
        return
    dom = host_of(dom)
    raw, bullets = [], []
    _scenario_step(1, 4, "владелец домена (whois)", ["whois", dom], p_whois, dom,
                   "5–15 сек", raw, bullets, timeout=60)
    _scenario_step(2, 4, "адреса и почта (dig)", ["dig", dom, "ANY"], p_dig, dom,
                   "5–10 сек", raw, bullets, timeout=60)
    _scenario_step(3, 4, "поддомены (subfinder)", ["subfinder", "-d", dom, "-silent"],
                   p_subfinder, dom, "20–90 сек", raw, bullets, timeout=300)
    _scenario_step(4, 4, "почты и контакты (theHarvester)",
                   ["theHarvester", "-d", dom, "-b", "duckduckgo,bing,crtsh"],
                   p_theharvester, dom, "20–90 сек", raw, bullets, timeout=300)
    _finish_scenario(f"OSINT по {dom}", dom, "info", bullets, raw)


SCENARIOS = [
    ("Разведка сети", "живые хосты → порты и сервисы", scenario_network),
    ("Разведка сайта", "домен → технологии → скрытые страницы", scenario_website),
    ("OSINT по домену", "владелец → адреса → поддомены → контакты", scenario_osint),
]


def scenarios_menu():
    while True:
        print()
        panel_open("Сценарии · пошаговая методология")
        print(col("  Готовые конвейеры: инструменты идут по порядку, данные —", C.GREY))
        print(col("  в общий инвентарь, результат — единый отчёт.\n", C.GREY))
        for i, (name, desc, _) in enumerate(SCENARIOS, 1):
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(name, C.LILAC)
                  + col("  ⚠", C.RED + C.BOLD))
            print(col(f"       {desc}", C.GREY))
        print(col("\n  [0] Назад", C.GREY))
        ch = input(col("\n  Выбор: ", C.YELLOW)).strip()
        if ch == "0":
            return
        if ch.isdigit() and 1 <= int(ch) <= len(SCENARIOS):
            SCENARIOS[int(ch) - 1][2]()
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ ПАЙПЛАЙН РАЗВЕДКИ (BUG BOUNTY) ============================

def run_pipeline():
    print(col("\n  Полная разведка: поддомены → живые хосты → уязвимости.", C.GREY))
    print(col("  Всё по одному домену, результат — единый отчёт.", C.GREY))
    domain = input(col("\n  Домен для разведки (in-scope): ", C.LILAC)).strip()
    if not domain:
        print(col("  Пусто — отмена.", C.GREY))
        return
    if not in_scope(domain):
        print(col("\n  ⛔ Домен вне scope. Сначала добавь его в scope или проверь список.", C.RED + C.BOLD))
        return
    need = ["subfinder", "httpx", "nuclei"]
    missing = [t for t in need if not shutil.which(t)]
    if missing:
        print(col(f"\n  Для пайплайна нужны: {', '.join(need)}.", C.RED))
        print(col(f"  Не установлены: {', '.join(missing)} — поставь их и повтори.", C.GREY))
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    subs_file = RESULTS_DIR / f"{stamp}_subs.txt"
    live_file = RESULTS_DIR / f"{stamp}_live.txt"
    raw = []

    # Шаг 1 — поддомены
    _step(1, 3, "ищу поддомены (subfinder)")
    rc, subs_lines, st = run_with_ui(["subfinder", "-d", domain, "-silent"],
                                     timeout=300, typical="20–90 сек")
    subs = sorted(set([l.strip() for l in subs_lines if l.strip() and "." in l] + [domain]))
    subs_file.write_text("\n".join(subs) + "\n", encoding="utf-8")
    raw += [f"# поддомены ({len(subs)})"] + subs
    print(col(f"  → поддоменов: {len(subs)}", C.LILAC))

    # Шаг 2 — живые хосты
    _step(2, 3, "проверяю, кто жив (httpx)")
    rc, live_lines, st = run_with_ui(["httpx", "-l", str(subs_file), "-silent"],
                                     timeout=300, typical="20–60 сек")
    live = sorted(set(l.strip() for l in live_lines if l.strip().startswith("http")))
    live_file.write_text("\n".join(live) + "\n", encoding="utf-8")
    raw += ["", f"# живые хосты ({len(live)})"] + live
    print(col(f"  → живых хостов: {len(live)}", C.LILAC))

    if not live:
        print(col("\n  Живых хостов нет — дальше сканировать нечего.", C.YELLOW))
        return

    # Шаг 3 — уязвимости
    _step(3, 3, "ищу уязвимости (nuclei)")
    rc, find_lines, st = run_with_ui(["nuclei", "-l", str(live_file), "-silent"],
                                     timeout=1800, typical="1–15 минут")
    raw += ["", "# nuclei"] + [l for l in find_lines if l.strip()]

    # общий отчёт
    nrep = p_nuclei(domain, rc, find_lines, st)
    rep = Report(f"Разведка {domain}: {len(subs)} поддоменов, {len(live)} живых",
                 nrep.level,
                 [(f"Поддоменов найдено: {len(subs)}", "info"),
                  (f"Живых веб-хостов: {len(live)}", "info")] + nrep.bullets)
    rep.raw_lines = raw

    print()
    show_report(rep)
    fake = Action("Разведка для баг-баунти", "", "", binary="")
    spec = ExecSpec(parts=["pipeline", domain], target=domain,
                    parser=p_generic, title="Разведка (пайплайн)")
    _, htmlf = save_result(fake, spec, 0, st, rep)
    print(col(f"\n  📄 Отчёт разведки: {htmlf}", C.GREEN))
    print(col(f"     Открыть: xdg-open \"{htmlf}\"", C.GREY))
    print()
    show_session_table()


# ============================ МЕНЮ BUG BOUNTY ============================

def bugbounty_menu():
    while True:
        print()
        panel_open("Bug Bounty · пошаговый режим")
        print(col("  Порядок работы: задай scope → разведка → поиск уязвимостей.", C.GREY))
        print(col("  Баг-баунти — авторизованное тестирование, но строго в рамках scope!", C.GREY))
        print(col("  📄 Полный алгоритм со всеми шагами — в файле METHODOLOGY_BUGBOUNTY.txt\n", C.GREY))
        print(col("  [s] ", C.PURPLE_BRIGHT) + col("Задать scope (разрешённые домены)", C.LILAC)
              + col("  ← начни отсюда", C.YELLOW))
        print(col(f"       сейчас в scope: {', '.join(sorted(SCOPE)) or '(пусто)'}", C.GREY))
        for i, act in enumerate(BB_TOOLS, 1):
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(act.name, C.LILAC)
                  + col("  ⚠", C.RED + C.BOLD))
            print(col(f"       {act.desc}", C.GREY))
        print(col("  [p] ", C.PURPLE_BRIGHT) + col("⚡ Полный пайплайн: поддомены → живые → уязвимости", C.LILAC))
        print(col("       одной командой по одному домену, единый отчёт", C.GREY))
        print(col("\n  [0] Назад", C.GREY))
        ch = input(col("\n  Выбор: ", C.YELLOW)).strip().lower()
        if ch == "0":
            return
        if ch == "s":
            scope_menu()
        elif ch == "p":
            run_pipeline()
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
        elif ch.isdigit() and 1 <= int(ch) <= len(BB_TOOLS):
            run_action(BB_TOOLS[int(ch) - 1])
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ МЕНЮ ============================

CONFIRMED_CATS = set()


def category_gate(cat):
    """Разовое подтверждение при первом входе в защищённую категорию за сессию."""
    if not cat.gated or cat.name in CONFIRMED_CATS:
        return True
    print()
    panel_card("⚠  " + cat.name + " — активные инструменты", C.RED + C.BOLD)
    for line in cat.gate_text.split("\n"):
        print(col("  " + line.strip(), C.YELLOW))
    ans = input(col("\n  Подтверди: цель — учебная площадка или своя система? "
                    "Введи 'ДА': ", C.YELLOW)).strip().lower()
    if ans not in ("да", "yes", "y"):
        print(col("  Не подтверждено — возврат в меню.", C.GREY))
        return False
    CONFIRMED_CATS.add(cat.name)
    return True


def category_menu(cat):
    if not category_gate(cat):
        return
    while True:
        print()
        panel_open(cat.name)
        print(col(f"  {cat.desc}\n", C.GREY))
        for i, act in enumerate(cat.actions, 1):
            tag = col("  ⚠", C.RED + C.BOLD) if act.requires_auth else ""
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(act.name, C.LILAC) + tag)
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
        panel_open("Voker · главное меню")
        print(col("  Методика: разведка → перечисление → уязвимости → доступ → отчёт", C.GREY))
        print(col("  🧭 Сценарии ведут по этому пути; отдельные инструменты — ниже.\n", C.GREY))
        print(col("  [c] ", C.PURPLE_BRIGHT) + col("🧭 Сценарии (пошаговая методология)", C.LILAC))
        print(col("  [b] ", C.PURPLE_BRIGHT) + col("🎯 Bug Bounty — режим веб-охоты", C.LILAC))
        print(col("  [a] ", C.PURPLE_BRIGHT) + col("📦 Инвентарь активов", C.LILAC)
              + col(f"   (найдено целей: {len(inv_pickable())})", C.GREY))
        print(col("  [s] ", C.PURPLE_BRIGHT) + col("Scope — разрешённые домены", C.LILAC)
              + col(f"   ({len(SCOPE)} в списке)", C.GREY))
        print(col(f"\n  Отдельные инструменты ({total}):", C.GREY))
        for i, cat in enumerate(TOOLKIT, 1):
            tag = col("  ⚠", C.RED + C.BOLD) if cat.gated else ""
            print(col(f"  [{i}] ", C.PURPLE_BRIGHT) + col(cat.name, C.LILAC)
                  + col(f"  ({len(cat.actions)})", C.GREY) + tag)
        print(col("\n  [o] Общий отчёт сессии (HTML)   ·   [q] Выход", C.GREY))
        choice = input(col("\n  Выбор: ", C.YELLOW)).strip().lower()
        if choice in ("q", "quit", "exit"):
            print(col("\n  До встречи. Учись легально. 💜\n", C.PURPLE_BRIGHT))
            return
        if choice == "c":
            scenarios_menu()
            continue
        if choice == "b":
            bugbounty_menu()
            continue
        if choice == "a":
            inventory_menu()
            continue
        if choice == "s":
            scope_menu()
            continue
        if choice == "o":
            path = build_session_html()
            if path:
                print(col(f"\n  📄 Общий отчёт: {path}", C.GREEN))
                print(col(f"     Открыть: xdg-open \"{path}\"", C.GREY))
            else:
                print(col("  Пока нечего собирать — сначала запусти пару команд.", C.GREY))
            input(col("\n  Нажми Enter, чтобы продолжить...", C.GREY))
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(TOOLKIT):
            category_menu(TOOLKIT[int(choice) - 1])
        else:
            print(col("  Нет такого пункта.", C.RED))


# ============================ CLI / ДИСКЛЕЙМЕР ============================

CONFIG_DIR = Path.home() / ".voker"
ACCEPT_FILE = CONFIG_DIR / "accepted"

DISCLAIMER = """
╔══════════════════════════════════════════════════════════════════╗
║                    ПРАВОВОЕ ПРЕДУПРЕЖДЕНИЕ                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Voker — для ОБУЧЕНИЯ и ЛЕГАЛЬНОГО тестирования.                  ║
║  Проверять чужие сети, сайты и Wi-Fi без письменного разрешения   ║
║  владельца во многих странах — уголовное преступление.            ║
║  То, что инструмент есть в Kali, НЕ делает его применение         ║
║  законным. Законно то, что ты запускаешь по своим системам или    ║
║  с разрешения. Ответственность — только твоя.                     ║
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


def print_tree():
    print_banner()
    total = 0
    for cat in TOOLKIT:
        print(col(f"▸ {cat.name}", C.PURPLE_BRIGHT + C.BOLD) + col(f" — {cat.desc}", C.GREY))
        for act in cat.actions:
            total += 1
            b = act.binary or "—"
            ok = bool(shutil.which(act.binary)) if act.binary else True
            mark = col("✓" if ok else "✗", C.GREEN if ok else C.RED)
            flags = " [auth]" if act.requires_auth else ""
            print(f"    {mark} {act.name} " + col(f"→ {b}{flags}", C.GREY))
        print()
    print(col(f"Всего: {total} инструментов", C.LILAC))


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
        load_scope()
        load_inventory()
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(col("\n\n  Выход.\n", C.GREY))


if __name__ == "__main__":
    main()
