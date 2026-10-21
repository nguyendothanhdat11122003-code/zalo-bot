# ============================================================
# FILE: tool_tdatt.py
# Zalo War Tool — Rich UI + Anti-Drop 2026
# Cài: pip install rich zlapi requests tqdm
# Chạy: python tool_tdatt.py
# Mật khẩu: toolwar hoặc tdatt212
# ============================================================

import os
import sys
import time
import json
import re
import ast
import random
import signal
import hashlib
import logging
import threading
import unicodedata
from collections import deque

# ============================================================
# RICH UI (fallback ANSI)
# ============================================================
HAS_RICH = False
console = None
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    console = Console()
    HAS_RICH = True
except Exception:
    HAS_RICH = False
    console = None

from zlapi import ZaloAPI, ThreadType
from zlapi.models import Message, Mention, MultiMention, MessageStyle, MultiMsgStyle

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    import tkinter as tk
    from tkinter import scrolledtext
    HAS_TK = True
except ImportError:
    HAS_TK = False


# ============================================================
# CONFIG
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTO_FOLDER = os.path.join(BASE_DIR, "ngon")
AUTO_FILE_DELAY = 0.5
CONFIG_FILE = os.path.join(BASE_DIR, "tdatt_session.json")
LOG_FILE = os.path.join(BASE_DIR, "toolwar.log")
TARGETS_FILE = os.path.join(BASE_DIR, "targets.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "toolwar_settings.json")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.json")
WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.json")
PROXY_FILE = os.path.join(BASE_DIR, "proxy.json")
SCAN_FILE = os.path.join(BASE_DIR, "groups_scan.json")

PWD_HASHES = {
    hashlib.sha256("toolwar".encode()).hexdigest(),
    hashlib.sha256("tdatt212".encode()).hexdigest(),
}

ZERO_WIDTH = ['\u200b', '\u200c', '\u200d', '\ufeff']
EMOJI_POOL = ['😀', '🔥', '💀', '⚡', '🌟', '✨', '🎯', '🚀', '💥', '🎲']

DEFAULT_SETTINGS = {
    # tốc độ
    "delay": 0.1,
    "file_delay": 0.5,
    "use_color": False,
    "font_size": "40",
    "stealth": True,
    "emoji": False,
    "rate_per_min": 120,
    "fake_typing": False,
    "typing_delay": False,
    "randomize_delay": False,
    # send retry
    "retry_max": 3,
    "retry_delay": 1.5,
    # anti-drop
    "keepalive_base": 30,          # heartbeat base (s)
    "keepalive_jitter": 10,        # +/- random (s)
    "watchdog_timeout": 120,       # idle -> reconnect (s)
    "watchdog_interval": 8,        # poll (s)
    "reconnect_max": 10,
    "reconnect_base": 3.0,
    "reconnect_cap": 90.0,         # max wait giữa 2 attempt
    "reconnect_jitter": 1.5,
    "circuit_break": True,         # bật circuit breaker sau nhiều fail
    "circuit_threshold": 6,        # N fail liên tiếp -> pause 5 phút
    "circuit_cooldown": 300,
    "auto_resume": True,
    "session_refresh": True,       # refresh cookie định kỳ (nếu API hỗ trợ)
}


# ============================================================
# LOGGER
# ============================================================
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("toolwar")


# ============================================================
# OUTPUT HELPERS
# ============================================================
def rprint(*args, **kwargs):
    try:
        if HAS_RICH and console:
            console.print(*args, **kwargs)
            return
    except Exception:
        pass
    plain = " ".join(str(a) for a in args)
    plain = re.sub(r'\[/?[^\]]+\]', '', plain)
    print(plain)


def rinput(prompt_text=""):
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def rconfirm(prompt_text):
    rprint(f"[bold yellow]❓ {prompt_text} (y/n)[/bold yellow]")
    while True:
        a = rinput("> ").lower()
        if a in ('y', 'yes', 'c', 'có', '1'):
            return True
        if a in ('n', 'no', 'k', 'không', '0'):
            return False
        rprint("[red]⚠️ Nhập y hoặc n![/red]")


# ============================================================
# SESSION / SETTINGS
# ============================================================
def save_session(imei, cookies):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"imei": imei, "cookies": cookies,
                       "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.error(f"save_session: {e}")
        return False


def load_session():
    if not os.path.isfile(CONFIG_FILE):
        return None, None, None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        imei, ck = d.get("imei"), d.get("cookies")
        return (imei, ck, d.get("saved_at", "?")) if imei and ck else (None, None, None)
    except Exception:
        return None, None, None


def clear_session():
    if os.path.isfile(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
        except Exception:
            pass


def load_settings():
    if not os.path.isfile(SETTINGS_FILE):
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        rprint("[bold green]💾 Đã lưu settings.[/bold green]")
    except Exception as e:
        rprint(f"[bold red]❌ Lỗi: {e}[/bold red]")


# ============================================================
# BLACKLIST / WHITELIST
# ============================================================
def _load_list(path):
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(str(x) for x in json.load(f))
    except Exception:
        return set()


def is_allowed(uid, blacklist, whitelist):
    uid = str(uid)
    if whitelist and uid not in whitelist:
        return False
    if uid in blacklist:
        return False
    return True


# ============================================================
# CLEAN NAME
# ============================================================
def clean_name(name):
    if not name:
        return "[Không tên]"
    name = re.sub(r'[\U0001F000-\U0001FFFF]', '', name)
    name = re.sub(r'[\u2600-\u27BF]', '', name)
    name = re.sub(r'[\uFE00-\uFE0F]', '', name)
    name = re.sub(r'[\u200B-\u200F\u2028-\u202F]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name or "[Không tên]"


# ============================================================
# PROXY MANAGER
# ============================================================
class ProxyManager:
    _original = None
    _current = None

    @classmethod
    def set(cls, proxy_url):
        import requests
        if cls._original is None:
            cls._original = requests.Session
        if not proxy_url:
            if cls._original:
                requests.Session = cls._original
            cls._current = None
            rprint("[yellow]🌐 Đã tắt proxy.[/yellow]")
            return
        old = cls._original
        class ProxiedSession(old):
            def request(self, *a, **kw):
                kw.setdefault('proxies', {'http': proxy_url, 'https': proxy_url})
                return super().request(*a, **kw)
        requests.Session = ProxiedSession
        cls._current = proxy_url
        rprint(f"[green]🌐 Đã set proxy: {proxy_url}[/green]")


def load_proxies():
    if not os.path.isfile(PROXY_FILE):
        return {}
    try:
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_proxies(data):
    with open(PROXY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# UTILS
# ============================================================
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_interface():
    clear_screen()
    if HAS_RICH:
        try:
            banner = """
████████╗██████╗  █████╗ ████████╗████████╗    ██████╗ ███████╗
╚══██╔══╝██╔══██╗██╔══██╗╚══██╔══╝╚══██╔══╝    ██╔══██╗╚══███╔╝
   ██║   ██║  ██║███████║   ██║      ██║       ██║  ██║  ███╔╝
   ██║   ██║  ██║██╔══██║   ██║      ██║       ██║  ██║ ███╔╝
   ██║   ██████╔╝██║  ██║   ██║      ██║       ██████╔╝███████╗
   ╚═╝   ╚═════╝ ╚═╝  ╚═╝   ╚═╝      ╚═╝       ╚═════╝ ╚══════╝
            """
            text = Text()
            colors = ["bright_red", "yellow", "bright_green",
                      "cyan", "bright_blue", "magenta"]
            for i, line in enumerate(banner.split("\n")):
                text.append(line + "\n", style=f"bold {colors[i % len(colors)]}")
            panel = Panel(
                Align.center(text),
                border_style="bright_magenta",
                padding=(1, 2),
                title="[bold cyan]⚡ ZALO WAR TOOL ⚡[/bold cyan]",
                subtitle="[bold yellow]• Tdatt Dz • VIP v7 FAST • Anti-Drop 2026 •[/bold yellow]",
            )
            console.print(panel)
            return
        except Exception:
            pass
    print("=" * 60)
    print("\033[96m🔥 ZALO WAR TOOL — VIP v7 FAST 🔥\033[0m\n")


def print_main_menu():
    if HAS_RICH:
        try:
            t = Table(title="[bold cyan]📋 MENU CHÍNH[/bold cyan]",
                      show_header=False, border_style="bright_blue",
                      padding=(0, 2))
            t.add_column("STT", style="bold green", width=6, justify="center")
            t.add_column("Chức năng", style="bright_white")
            for n, l in [
                ("1", "🌟 Nhắn tin trên box Zalo"),
                ("2", "💬 Nhắn tin riêng với User"),
                ("3", "🔑 Đổi IMEI / Cookie (xoá session)"),
                ("4", "📁 Export targets"),
                ("5", "👥 Debug bạn bè"),
                ("6", "🔍 Anti-ghost (check ai block)"),
                ("7", "🗺️  Quét toàn bộ nhóm"),
                ("8", "🌐 Proxy manager"),
                ("9", "🖥️  Mở GUI mode"),
                ("10", "⚙️  Cài đặt tốc độ & chống rớt"),
                ("11", "♻️  Force reconnect"),
                ("12", "❌ Thoát"),
            ]:
                t.add_row(f"❯ {n}", l)
            console.print(t)
            return
        except Exception:
            pass
    print("\n======== • MENU CHÍNH • ========")
    print("1. Nhắn tin trên box Zalo")
    print("2. Nhắn tin riêng với User")
    print("3. Đổi IMEI / Cookie")
    print("4. Export targets")
    print("5. Debug bạn bè")
    print("6. Anti-ghost")
    print("7. Quét toàn bộ nhóm")
    print("8. Proxy manager")
    print("9. GUI mode")
    print("10. Cài đặt tốc độ & chống rớt")
    print("11. Force reconnect")
    print("12. Thoát")


def print_level2_menu(choice):
    if HAS_RICH:
        try:
            t = Table(title="[bold cyan]🎯 CHỌN KIỂU SPAM[/bold cyan]",
                      show_header=False, border_style="bright_yellow",
                      padding=(0, 2))
            t.add_column("STT", style="bold green", width=6, justify="center")
            t.add_column("Kiểu", style="bright_white")
            if choice == '1':
                for n, l in [("1", "🌟 Treo một ngôn"),
                             ("2", "🎯 Treo một ngôn + tag"),
                             ("3", "📁 Nhây theo file"),
                             ("4", "📁🎯 Nhây theo file + tag")]:
                    t.add_row(f"❯ {n}", l)
            else:
                for n, l in [("1", "🌟 Treo một ngôn"),
                             ("3", "📁 Nhây theo file")]:
                    t.add_row(f"❯ {n}", l)
            console.print(t)
            return
        except Exception:
            pass
    print("\n==== • SELECT LEVEL 2 • ====")
    if choice == '1':
        print("1. Treo một ngôn\n2. Treo một ngôn + tag")
        print("3. Nhây theo file\n4. Nhây theo file + tag")
    else:
        print("1. Treo một ngôn\n3. Nhây theo file")


def normalize_password(text):
    text = unicodedata.normalize('NFKD', text)
    clean = "".join(c for c in text if not unicodedata.combining(c))
    clean = re.sub(r'[^a-zA-Z0-9]', '', clean)
    return clean.lower()


def parse_cookie_string(s):
    s = s.strip()
    for parse in (json.loads, ast.literal_eval):
        try:
            v = parse(s)
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    c = {}
    for p in s.split(';'):
        if '=' in p:
            k, val = p.strip().split('=', 1)
            c[k] = val
    return c or None


def parse_multi_input(s, max_val):
    cleaned = s.replace('&', ',').replace(' ', ',')
    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
    out = []
    for p in parts:
        if p.isdigit():
            v = int(p)
            if 1 <= v <= max_val and v not in out:
                out.append(v)
    return out


def ask_yes_no(p):
    return rconfirm(p)


def obfuscate(text):
    if not text:
        return text
    return text + "".join(random.choice(ZERO_WIDTH)
                          for _ in range(random.randint(1, 3)))


def sprinkle_emoji(text):
    if not text:
        return text
    return f"{random.choice(EMOJI_POOL)} {text} {random.choice(EMOJI_POOL)}"


def fake_typing_delay(text, base=0.03):
    time.sleep(len(text or "") * base * random.uniform(0.7, 1.3))


TEMPLATE_VARS = {
    "{time}": lambda: time.strftime("%H:%M:%S"),
    "{date}": lambda: time.strftime("%d/%m/%Y"),
    "{random}": lambda: str(random.randint(1000, 9999)),
    "{emoji}": lambda: random.choice(EMOJI_POOL),
}


def render_template(text):
    if not text:
        return text
    for k, fn in TEMPLATE_VARS.items():
        if k in text:
            text = text.replace(k, fn())
    return text


def _extract_uid(item):
    if not isinstance(item, dict):
        return None
    return (item.get('userId') or item.get('uid')
            or item.get('id') or item.get('globalId'))


def _extract_name(item, fb=''):
    if not isinstance(item, dict):
        return fb
    name = (item.get('displayName') or item.get('zaloName')
            or item.get('name') or fb)
    return clean_name(name) if name else fb


# ============================================================
# RATE LIMITER — token bucket + sliding window
# ============================================================
class RateLimiter:
    def __init__(self, max_per_min=120):
        self.max = max_per_min
        self.times = deque()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            while self.times and now - self.times[0] >= 60:
                self.times.popleft()
            if len(self.times) >= self.max:
                s = 60 - (now - self.times[0])
                if s > 0:
                    rprint(f"[yellow]⚠️ Rate limit — nghỉ {s:.1f}s[/yellow]")
                    time.sleep(s)
            self.times.append(time.time())


# ============================================================
# HEARTBEAT WATCHDOG
# ============================================================
class HeartbeatWatchdog:
    """Watchdog thụ động: client beat() sau mỗi call API thành công.
       Idle > timeout -> kích hoạt reconnect."""
    def __init__(self, client, timeout=120, interval=8):
        self.client = client
        self.timeout = timeout
        self.interval = interval
        self._last_ok = time.time()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def beat(self):
        with self._lock:
            self._last_ok = time.time()

    def idle(self):
        with self._lock:
            return time.time() - self._last_ok

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                return
            if self.client._reconnecting.is_set():
                continue
            idle = self.idle()
            if idle > self.timeout:
                rprint(f"[bold red]💓 Watchdog: idle {idle:.0f}s > {self.timeout}s → reconnect[/bold red]")
                self.client.force_reconnect("watchdog-idle")


# ============================================================
# KEEPALIVE — adaptive jitter
# ============================================================
class KeepAliveLoop:
    """Ping nhẹ giữ session warm. Khoảng chạy jitter để tránh pattern."""
    def __init__(self, client):
        self.client = client
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            s = self.client.settings
            base = int(s.get("keepalive_base", 30))
            jit = int(s.get("keepalive_jitter", 10))
            wait = max(5, base + random.randint(-jit, jit))
            if self._stop.wait(wait):
                return
            if self.client._reconnecting.is_set():
                continue
            try:
                self.client.fetchAllGroups()
                self.client.watchdog.beat()
                log.info("keepalive ok")
            except Exception as e:
                log.warning(f"keepalive fail: {e}")
                # Không beat -> watchdog sẽ tự bắt nếu kéo dài


# ============================================================
# CIRCUIT BREAKER — ngắt mạch khi fail liên tục
# ============================================================
class CircuitBreaker:
    def __init__(self, threshold=6, cooldown=300):
        self.threshold = threshold
        self.cooldown = cooldown
        self.fails = 0
        self.open_until = 0
        self.lock = threading.Lock()

    def ok(self):
        with self.lock:
            self.fails = 0

    def fail(self):
        with self.lock:
            self.fails += 1
            if self.fails >= self.threshold:
                self.open_until = time.time() + self.cooldown
                self.fails = 0
                return True
        return False

    def is_open(self):
        with self.lock:
            return time.time() < self.open_until

    def remaining(self):
        with self.lock:
            return max(0, self.open_until - time.time())


# ============================================================
# KEYWORD LISTENER
# ============================================================
class KeywordListener:
    def __init__(self, client, rules=None):
        self.client = client
        self.rules = rules or {}
        self.enabled = False
        self.replied = set()

    def start(self): self.enabled = True
    def stop(self): self.enabled = False

    def on_message(self, message, thread_id, thread_type, author_id):
        if not self.enabled:
            return
        text = (message or "").lower()
        for kw, reply in self.rules.items():
            if kw.lower() in text and author_id not in self.replied:
                try:
                    self.client.send(Message(text=reply),
                                     thread_id=thread_id, thread_type=thread_type)
                    self.replied.add(author_id)
                except Exception as e:
                    log.error(f"listener: {e}")
                break


# ============================================================
# CLIENT
# ============================================================
class ZaloWarClient(ZaloAPI):
    def __init__(self, imei, cookies, label="Bot", rate_per_min=120):
        super().__init__('api_key', 'secret_key', imei, cookies)
        self.label = label
        self.running = threading.Event()
        self.rate_limiter = RateLimiter(rate_per_min)
        self.counter = 0
        self.counter_lock = threading.Lock()
        self.listener = KeywordListener(self)
        self.blacklist = _load_list(BLACKLIST_FILE)
        self.whitelist = _load_list(WHITELIST_FILE)
        self.settings = load_settings()
        self._name_cache = {}

        # anti-drop state
        self._imei = imei
        self._cookies = cookies
        self._reconnecting = threading.Event()
        self._reconnect_generation = 0
        self._resume_callback = None
        self.watchdog = HeartbeatWatchdog(
            self,
            timeout=self.settings.get("watchdog_timeout", 120),
            interval=self.settings.get("watchdog_interval", 8),
        )
        self.keepalive = KeepAliveLoop(self)
        self.breaker = CircuitBreaker(
            threshold=self.settings.get("circuit_threshold", 6),
            cooldown=self.settings.get("circuit_cooldown", 300),
        )
        self.watchdog.start()
        self.keepalive.start()

    # ---------- resume hook ----------
    def set_resume_callback(self, cb):
        self._resume_callback = cb

    # ---------- reconnect ----------
    def force_reconnect(self, reason="manual"):
        threading.Thread(
            target=self._reconnect_loop, args=(reason,), daemon=True
        ).start()

    def _reconnect_loop(self, reason):
        if self._reconnecting.is_set():
            return
        self._reconnecting.set()
        gen = self._reconnect_generation + 1
        self._reconnect_generation = gen
        was_running = self.running.is_set()
        s = self.settings
        max_attempts = int(s.get("reconnect_max", 10))
        base = float(s.get("reconnect_base", 3.0))
        cap = float(s.get("reconnect_cap", 90.0))
        jitter = float(s.get("reconnect_jitter", 1.5))
        log.warning(f"reconnect start reason={reason} gen={gen}")
        try:
            for attempt in range(1, max_attempts + 1):
                if gen != self._reconnect_generation:
                    return
                wait = min(cap, base * (1.7 ** (attempt - 1))) + random.uniform(0, jitter)
                rprint(f"[yellow]🔄 Reconnect {attempt}/{max_attempts} "
                       f"({reason}) sau {wait:.1f}s...[/yellow]")
                time.sleep(wait)
                if gen != self._reconnect_generation:
                    return
                try:
                    ZaloAPI.__init__(self, 'api_key', 'secret_key',
                                     self._imei, self._cookies)
                    self.watchdog.beat()
                    self.breaker.ok()
                    rprint("[bold green]✅ Reconnect OK[/bold green]")
                    log.info(f"reconnect ok attempt={attempt} gen={gen}")
                    if was_running and s.get("auto_resume", True):
                        self.running.set()
                        if self._resume_callback:
                            try:
                                self._resume_callback()
                            except Exception as e:
                                log.error(f"resume cb: {e}")
                    return
                except Exception as e:
                    rprint(f"[red]   ✗ {e}[/red]")
                    log.error(f"reconnect fail #{attempt}: {e}")
                    if self.breaker.fail() and s.get("circuit_break", True):
                        cd = self.breaker.remaining()
                        rprint(f"[bold red]🛑 Circuit breaker mở — nghỉ {cd:.0f}s[/bold red]")
                        time.sleep(cd)
                        self.breaker.ok()
            rprint("[bold red]❌ Reconnect thất bại hết lượt.[/bold red]")
            log.error("reconnect exhausted")
            self.running.clear()
        finally:
            self._reconnecting.clear()

    # ---------- data ----------
    def fetch_groups(self):
        try:
            all_groups = self.fetchAllGroups()
            self.watchdog.beat()
            out, gmap = [], None
            if hasattr(all_groups, 'gridVerMap'):
                gmap = all_groups.gridVerMap
            elif isinstance(all_groups, dict):
                gmap = all_groups.get('gridVerMap') or {}
            if gmap:
                for gid in gmap:
                    try:
                        info = self.fetchGroupInfo(gid)
                        name = info.gridInfoMap[gid].get('name', gid)
                    except Exception:
                        name = gid
                    out.append({'id': gid, 'name': clean_name(name)})
            elif isinstance(all_groups, dict):
                for item in all_groups.get('data', []):
                    uid = _extract_uid(item)
                    if uid:
                        out.append({'id': uid, 'name': _extract_name(item, uid)})
            return out
        except Exception as e:
            rprint(f"[red]❌ Lỗi lấy nhóm: {e}[/red]")
            if self._is_conn_error(e):
                self.force_reconnect("fetch_groups")
            return []

    def fetch_members(self, group_id):
        try:
            info = self.fetchGroupInfo(group_id)
            self.watchdog.beat()
            if not info or group_id not in info.gridInfoMap:
                return []
            mem_ver = info.gridInfoMap[group_id].get("memVerList", [])
            uids = [m.split("_")[0] for m in mem_ver]
            out = []
            for uid in uids:
                try:
                    ui = self.fetchUserInfo(uid)
                    p = ui.changed_profiles.get(uid, {})
                    name = p.get('displayName') or p.get('zaloName') or f"[ID: {uid}]"
                    out.append({'id': uid, 'name': clean_name(name)})
                except Exception:
                    out.append({'id': uid, 'name': f"[ID: {uid}]"})
            return out
        except Exception as e:
            rprint(f"[red]❌ Lỗi lấy members: {e}[/red]")
            if self._is_conn_error(e):
                self.force_reconnect("fetch_members")
            return []

    def fetch_friends(self, debug=False):
        try:
            fl = self.fetchAllFriends()
            self.watchdog.beat()
            friends, seen = [], set()

            def _add(uid, info):
                if not uid or uid in seen:
                    return
                seen.add(uid)
                friends.append({'id': str(uid),
                                'name': _extract_name(info, str(uid))})

            for attr in ('gridInfoMap',):
                sub = getattr(fl, attr, None)
                if isinstance(sub, dict):
                    for uid, info in sub.items():
                        _add(uid, info)
                    if friends:
                        return friends

            changed = getattr(fl, 'changed_profiles', None) or {}
            unchanged = getattr(fl, 'unchanged_profiles', None) or {}
            if changed or unchanged:
                for uid, info in {**unchanged, **changed}.items():
                    _add(uid, info)
                if friends:
                    return friends

            data = getattr(fl, 'data', None)
            if isinstance(data, dict):
                if any(isinstance(v, dict) for v in data.values()):
                    for uid, info in data.items():
                        _add(uid, info)
                else:
                    for k in ('friends', 'items', 'list', 'data'):
                        if isinstance(data.get(k), list):
                            for it in data[k]:
                                _add(_extract_uid(it), it)
            elif isinstance(data, list):
                for it in data:
                    _add(_extract_uid(it), it)
            if friends:
                return friends

            if isinstance(fl, dict):
                for k in ('gridInfoMap', 'changed_profiles', 'unchanged_profiles',
                          'friends', 'data', 'items', 'list'):
                    sub = fl.get(k)
                    if isinstance(sub, dict):
                        for uid, info in sub.items():
                            _add(uid, info)
                    elif isinstance(sub, list):
                        for it in sub:
                            _add(_extract_uid(it), it)
                if not friends:
                    for uid, info in fl.items():
                        if isinstance(info, dict):
                            _add(uid, info)
                if friends:
                    return friends

            if isinstance(fl, list):
                for it in fl:
                    _add(_extract_uid(it), it)
                return friends

            if hasattr(fl, '__dict__'):
                for v in fl.__dict__.values():
                    if isinstance(v, dict) and v:
                        for uid, info in v.items():
                            if isinstance(info, dict):
                                _add(uid, info)
                    elif isinstance(v, list) and v:
                        for it in v:
                            if isinstance(it, dict):
                                _add(_extract_uid(it), it)
            return friends
        except Exception as e:
            rprint(f"[red]❌ Lỗi lấy bạn bè: {e}[/red]")
            if self._is_conn_error(e):
                self.force_reconnect("fetch_friends")
            return []

    def fetch_all_conversations(self):
        try:
            return [{'id': f['id'], 'name': f['name'], 'type': 'user'}
                    for f in self.fetch_friends()]
        except Exception as e:
            rprint(f"[red]❌ Lỗi: {e}[/red]")
            return []

    # ---------- anti-ghost ----------
    def check_block(self, user_id):
        try:
            info = self.fetchUserInfo(user_id)
            self.watchdog.beat()
            if not info:
                return None
            profile = None
            if hasattr(info, 'changed_profiles'):
                profile = info.changed_profiles.get(user_id)
            elif hasattr(info, 'unchanged_profiles'):
                profile = info.unchanged_profiles.get(user_id)
            if not profile:
                return True
            name = profile.get('displayName') or profile.get('zaloName')
            return not bool(name)
        except Exception:
            return None

    def scan_blocked(self, group_id=None):
        if group_id:
            targets = self.fetch_members(group_id)
            label = "nhóm"
        else:
            targets = self.fetch_friends()
            label = "bạn bè"
        blocked = []
        rprint(f"\n[cyan]🔍 Check {len(targets)} người trong {label}...[/cyan]")
        for i, t in enumerate(targets, 1):
            if i % 20 == 0:
                rprint(f"   [dim]... {i}/{len(targets)}[/dim]")
            if self.check_block(t['id']) is True:
                blocked.append(t)
                rprint(f"   [red]🚫 {t['name']}[/red]")
        return blocked

    def send_typing(self, thread_id, thread_type=ThreadType.GROUP):
        try:
            if hasattr(self, 'sendTypingEvent'):
                self.sendTypingEvent(thread_id=thread_id, thread_type=thread_type)
                return True
            if hasattr(self, 'sendTyping'):
                self.sendTyping(thread_id=thread_id, thread_type=thread_type)
                return True
        except Exception:
            pass
        return False

    # ---------- group scan ----------
    def scan_all_groups_info(self, max_groups=None):
        groups = self.fetch_groups()
        if max_groups:
            groups = groups[:max_groups]
        result = []
        rprint(f"\n[cyan]🔍 Quét {len(groups)} nhóm...[/cyan]")
        for i, g in enumerate(groups, 1):
            rprint(f"[dim][{i}/{len(groups)}][/dim] [yellow]{g['name']}[/yellow]")
            try:
                members = self.fetch_members(g['id'])
                admins = []
                try:
                    info = self.fetchGroupInfo(g['id'])
                    if hasattr(info, 'gridInfoMap'):
                        gi = info.gridInfoMap.get(g['id'], {})
                        admin_ids = gi.get('adminIds') or gi.get('admins') or []
                        for a in admin_ids:
                            m = next((x for x in members if x['id'] == a), None)
                            admins.append(m or {'id': a, 'name': a})
                except Exception:
                    pass
                result.append({'id': g['id'], 'name': g['name'],
                               'member_count': len(members),
                               'admins': admins, 'members': members})
            except Exception as e:
                rprint(f"   [red]❌ {e}[/red]")
                result.append({'id': g['id'], 'name': g['name'], 'error': str(e)})
        try:
            with open(SCAN_FILE, "w", encoding="utf-8") as f:
                json.dump({"scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "total_groups": len(result), "groups": result},
                          f, ensure_ascii=False, indent=2)
            rprint(f"\n[green]💾 Đã lưu: {SCAN_FILE}[/green]")
        except Exception as e:
            rprint(f"[yellow]⚠️ Lưu lỗi: {e}[/yellow]")
        return result

    # ---------- style / mention ----------
    def _make_style(self, text, font_size="40"):
        if not text:
            return None
        try:
            lines = text.strip().split('\n')
            colors = ["#db342e", "#f27806", "#f7b503",
                      "#15a85f", "#00bfff", "#ff00ff"]
            random.shuffle(colors)
            styles, off = [], 0
            for i, line in enumerate(lines):
                if not line:
                    off += 1
                    continue
                c = colors[i % len(colors)]
                styles.append(MessageStyle(offset=off, length=len(line),
                                           style="color", color=c, auto_format=False))
                styles.append(MessageStyle(offset=off, length=len(line),
                                           style="bold", auto_format=False))
                styles.append(MessageStyle(offset=off, length=len(line),
                                           style="font", size=str(font_size),
                                           auto_format=False))
                off += len(line) + 1
            return MultiMsgStyle(styles)
        except Exception:
            return None

    def _get_name_cached(self, uid):
        if uid in self._name_cache:
            return self._name_cache[uid]
        try:
            ui = self.fetchUserInfo(uid)
            name = ui.changed_profiles.get(uid, {}).get('displayName', uid)
            name = clean_name(name)
        except Exception:
            name = uid
        self._name_cache[uid] = name
        return name

    def _build_mention(self, msg, uids, all_mode=False):
        mentions = []
        formatted = (msg or "").rstrip() + " "
        if all_mode:
            tag = "@All"
            off = len(formatted)
            formatted += tag
            mentions.append(Mention(uid="-1", length=len(tag),
                                    offset=off, auto_format=False))
        elif uids:
            for uid in uids:
                tag = f"@{self._get_name_cached(uid)}"
                off = len(formatted)
                formatted += tag + " "
                mentions.append(Mention(uid=uid, length=len(tag),
                                        offset=off, auto_format=False))
        return formatted, (MultiMention(mentions) if mentions else None)

    def _incr(self):
        with self.counter_lock:
            self.counter += 1
            return self.counter

    # ---------- error classification ----------
    def _is_conn_error(self, e):
        m = str(e).lower()
        keys = ("connection", "timeout", "reset", "broken pipe", "ssl",
                "network", "unreachable", "refused", "eof", "read timed",
                "temporarily", "502", "503", "504")
        return any(k in m for k in keys)

    # ---------- retry wrapper ----------
    def _send_with_retry(self, fn, *args, **kwargs):
        retry_max = int(self.settings.get("retry_max", 3))
        retry_delay = float(self.settings.get("retry_delay", 1.5))
        last_err = None
        for attempt in range(1, retry_max + 1):
            if self.breaker.is_open():
                rprint(f"[red]🛑 Circuit breaker mở — nghỉ {self.breaker.remaining():.0f}s[/red]")
                time.sleep(min(self.breaker.remaining(), 30))
            try:
                r = fn(*args, **kwargs)
                self.breaker.ok()
                return r
            except Exception as e:
                last_err = e
                if self._is_conn_error(e):
                    rprint(f"[yellow]   ↻ retry {attempt}/{retry_max} — {e}[/yellow]")
                    time.sleep(retry_delay * attempt + random.uniform(0, 0.5))
                    if attempt == retry_max:
                        if self.breaker.fail():
                            rprint(f"[bold red]🛑 Circuit mở sau {retry_max} fail[/bold red]")
                        self.force_reconnect("retry-exhausted")
                else:
                    # lỗi logic — không retry
                    raise
        raise last_err

    # ---------- send group ----------
    def send_to_group(self, gid, text, uids=None, all_mode=False,
                      use_color=False, font_size="40", stealth=False, emoji=False):
        if not is_allowed(gid, self.blacklist, self.whitelist):
            return
        if self._reconnecting.is_set():
            return
        try:
            self.rate_limiter.wait()
            if self.settings.get("typing_delay"):
                self.send_typing(gid, ThreadType.GROUP)
                time.sleep(random.uniform(0.1, 0.3))
            content = render_template(text)
            if emoji:
                content = sprinkle_emoji(content)
            if stealth:
                content = obfuscate(content)
            if self.settings.get("fake_typing"):
                fake_typing_delay(content)
            formatted, mention = self._build_mention(content, uids or [], all_mode)
            style = self._make_style(formatted, font_size) if use_color else None
            msg = Message(text=formatted, mention=mention, style=style)
            self._send_with_retry(self.send, msg,
                                  thread_id=gid, thread_type=ThreadType.GROUP)
            self.watchdog.beat()
            n = self._incr()
            tag = "@All " if all_mode else (f"tag {len(uids)} " if uids else "")
            rprint(f"[green]✓[/green] [bold]#{n}[/bold] gửi {tag}nhóm")
            log.info(f"send_group #{n} gid={gid}")
        except Exception as e:
            rprint(f"[red]![/red] Lỗi: {e}")
            log.error(f"send_group: {e}")

    # ---------- send user ----------
    def send_to_user(self, uid, text, use_color=False, font_size="40",
                     stealth=False, emoji=False):
        if not is_allowed(uid, self.blacklist, self.whitelist):
            return
        if self._reconnecting.is_set():
            return
        try:
            self.rate_limiter.wait()
            if self.settings.get("typing_delay"):
                self.send_typing(uid, ThreadType.USER)
                time.sleep(random.uniform(0.1, 0.3))
            content = render_template(text)
            if emoji:
                content = sprinkle_emoji(content)
            if stealth:
                content = obfuscate(content)
            if self.settings.get("fake_typing"):
                fake_typing_delay(content)
            style = self._make_style(content, font_size) if use_color else None
            msg = Message(text=content, style=style)
            self._send_with_retry(self.send, msg,
                                  thread_id=uid, thread_type=ThreadType.USER)
            self.watchdog.beat()
            n = self._incr()
            rprint(f"[green]✓[/green] [bold]#{n}[/bold] gửi tin riêng")
            log.info(f"send_user #{n} uid={uid}")
        except Exception as e:
            rprint(f"[red]![/red] Lỗi: {e}")
            log.error(f"send_user: {e}")

    # ---------- files ----------
    def _resolve_files(self, inp):
        inp = inp.strip()
        if inp.lower() == 'auto':
            if not os.path.isdir(AUTO_FOLDER):
                rprint(f"[red]❌ Folder '{AUTO_FOLDER}' không tồn tại![/red]")
                return []
            files = [os.path.join(AUTO_FOLDER, f) for f in sorted(os.listdir(AUTO_FOLDER))
                     if os.path.isfile(os.path.join(AUTO_FOLDER, f)) and not f.startswith('.')]
            if not files:
                rprint("[red]❌ Folder rỗng![/red]")
                return []
            rprint(f"\n[cyan]🤖 AUTO — {len(files)} file:[/cyan]")
            for f in files:
                rprint(f"   • {os.path.basename(f)}")
            return files
        files = []
        for p in [x.strip() for x in inp.split(',') if x.strip()]:
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    full = os.path.join(p, f)
                    if os.path.isfile(full) and not f.startswith('.'):
                        files.append(full)
            elif os.path.isfile(p):
                files.append(p)
            else:
                rprint(f"[yellow]⚠️ Bỏ qua '{p}'[/yellow]")
        return files

    def _read_lines(self, fp, mode):
        with open(fp, 'r', encoding='utf-8') as f:
            content = f.read()
        if mode == "1":
            return [content]
        return [ln.strip() for ln in content.splitlines() if ln.strip()]

    def _sleep(self, delay_time):
        if self.settings.get("randomize_delay"):
            time.sleep(delay_time * random.uniform(0.85, 1.25))
        else:
            time.sleep(delay_time)

    def _wait_if_reconnecting(self):
        while self._reconnecting.is_set() and self.running.is_set():
            time.sleep(0.8)

    # ---------- loops ----------
    def loop_spam_group(self, gid, inp, mode, uids, all_mode, use_color, font_size,
                        delay_time, file_delay=0.5, stealth=False, emoji=False):
        files = self._resolve_files(inp)
        if not files:
            rprint("[red]❌ Không có file![/red]")
            return
        rprint(f"[cyan]📂 {len(files)} file[/cyan]\n")
        self.running.set()

        def _resume():
            if self.running.is_set():
                rprint("[green]🔁 Resume loop sau reconnect[/green]")
        self.set_resume_callback(_resume)

        r = 0
        while self.running.is_set():
            r += 1
            rprint(f"\n[magenta]════ VÒNG {r} ════[/magenta]")
            for fp in files:
                if not self.running.is_set():
                    break
                rprint(f"\n[yellow]▶ {fp}[/yellow]")
                try:
                    lines = self._read_lines(fp, mode)
                except Exception as e:
                    rprint(f"[red]❌ {e}[/red]")
                    continue
                if not lines:
                    continue
                it = tqdm(lines, desc=os.path.basename(fp)) if HAS_TQDM else lines
                for line in it:
                    if not self.running.is_set():
                        break
                    self._wait_if_reconnecting()
                    self.send_to_group(gid, line, uids, all_mode,
                                       use_color, font_size, stealth, emoji)
                    self._sleep(delay_time)
                if self.running.is_set() and file_delay > 0:
                    rprint(f"[dim]⏸ Nghỉ {file_delay}s[/dim]")
                    time.sleep(file_delay)
            rprint("\n[green]🔁 Hết file, quay lại...[/green]")

    def loop_spam_user(self, uid, inp, mode, use_color, font_size,
                       delay_time, file_delay=0.5, stealth=False, emoji=False):
        files = self._resolve_files(inp)
        if not files:
            return
        self.running.set()
        while self.running.is_set():
            for fp in files:
                if not self.running.is_set():
                    break
                try:
                    lines = self._read_lines(fp, mode)
                except Exception:
                    continue
                if not lines:
                    continue
                for line in lines:
                    if not self.running.is_set():
                        break
                    self._wait_if_reconnecting()
                    self.send_to_user(uid, line, use_color, font_size,
                                      stealth, emoji)
                    self._sleep(delay_time)
                if self.running.is_set() and file_delay > 0:
                    time.sleep(file_delay)


# ============================================================
# EXPORT
# ============================================================
def export_targets(client, path=None):
    path = path or TARGETS_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"groups": client.fetch_groups(),
                       "friends": client.fetch_friends(),
                       "exported_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=2)
        rprint(f"[green]💾 Đã export: {path}[/green]")
    except Exception as e:
        rprint(f"[red]❌ {e}[/red]")


# ============================================================
# SELECTION HELPERS
# ============================================================
def select_group(client):
    groups = client.fetch_groups()
    if not groups:
        rprint("[red]❌ Không có nhóm.[/red]")
        return None, None
    if HAS_RICH:
        try:
            t = Table(title="[bold cyan]📋 DANH SÁCH NHÓM[/bold cyan]",
                      border_style="bright_blue", show_lines=True)
            t.add_column("STT", style="bold yellow", justify="center", width=5)
            t.add_column("Tên nhóm", style="bright_white")
            t.add_column("ID", style="dim cyan")
            for i, g in enumerate(groups, 1):
                t.add_row(str(i), g['name'], g['id'])
            console.print(t)
        except Exception:
            pass
    else:
        print("\n📋 Nhóm:")
        for i, g in enumerate(groups, 1):
            print(f"  {i}. {g['name']} ({g['id']})")
    raw = rinput("👉 Nhập STT nhóm: ")
    if not raw.isdigit() or not (1 <= int(raw) <= len(groups)):
        rprint("[red]❌ Lỗi![/red]")
        return None, None
    g = groups[int(raw) - 1]
    return g['id'], g['name']


def select_members(client, gid):
    members = client.fetch_members(gid)
    if not members:
        rprint("[red]❌ Không có members.[/red]")
        return [], False
    if HAS_RICH:
        try:
            t = Table(title="[bold cyan]👥 DANH SÁCH THÀNH VIÊN[/bold cyan]",
                      border_style="bright_blue", show_lines=True)
            t.add_column("STT", style="bold yellow", justify="center", width=5)
            t.add_column("Tên", style="bright_white")
            t.add_column("ID", style="dim cyan")
            for i, m in enumerate(members, 1):
                t.add_row(str(i), m['name'], m['id'])
            console.print(t)
            console.print("[bold yellow]💡 'all' để @All, hoặc STT (1,2,3)[/bold yellow]")
        except Exception:
            pass
    else:
        print("\n👥 Members:")
        for i, m in enumerate(members, 1):
            print(f"  {i}. {m['name']} ({m['id']})")
        print("\n💡 'all' để @All, hoặc STT (1,2,3)")
    raw = rinput("👉 Chọn: ").lower()
    if raw in ('all', '@all'):
        return [], True
    idxs = parse_multi_input(raw, len(members))
    return [members[i-1]['id'] for i in idxs], False


def ask_file_input():
    fn = rinput("🧸 File/folder/'auto': ")
    mode = rinput("🎯 Dạng (1=1 ngôn/file, 2=mỗi dòng 1 ngôn): ")
    mode = mode if mode in ('1', '2') else '1'
    if fn.lower() == 'auto':
        fd = AUTO_FILE_DELAY
        rprint(f"[yellow]⏱ Auto — nghỉ {fd}s[/yellow]")
    else:
        raw = rinput("⏱ Nghỉ giữa file (mặc định 0.5): ")
        try:
            fd = float(raw) if raw else 0.5
            if fd < 0:
                fd = 0
        except ValueError:
            fd = 0.5
    return fn, mode, fd


def wait_for_stop(client, threads=None):
    rprint("[dim]⏹️ Gõ 'stop' để dừng[/dim]")
    while True:
        try:
            if input().strip().lower() == 'stop':
                client.running.clear()
                rprint("\n[yellow]🚦 Đã dừng.[/yellow]\n")
                if threads:
                    for t in threads:
                        t.join(timeout=3)
                return
        except (EOFError, KeyboardInterrupt):
            client.running.clear()
            return


def install_signal_handler():
    def _h(sig, frame):
        rprint("\n[red]🚦 Ctrl+C![/red]")
        sys.exit(0)
    signal.signal(signal.SIGINT, _h)


# ============================================================
# GUI
# ============================================================
def launch_gui(client):
    if not HAS_TK:
        rprint("[red]❌ tkinter không có.[/red]")
        return
    root = tk.Tk()
    root.title("Toolwar GUI")
    root.geometry("900x650")
    root.configure(bg="#111")
    hdr = tk.Frame(root, bg="#1a1a1a", height=40)
    hdr.pack(fill="x")
    tk.Label(hdr, text="💀 TOOLWAR GUI 💀", fg="#0f0", bg="#1a1a1a",
             font=("Consolas", 13, "bold")).pack(pady=8)
    main = tk.Frame(root, bg="#111")
    main.pack(fill="both", expand=True, padx=10, pady=10)
    left = tk.Frame(main, bg="#111", width=220)
    left.pack(side="left", fill="y", padx=(0, 10))
    left.pack_propagate(False)
    right = tk.Frame(main, bg="#111")
    right.pack(side="right", fill="both", expand=True)
    log_box = scrolledtext.ScrolledText(right, bg="#000", fg="#0f0",
                                        font=("Consolas", 10),
                                        insertbackground="#0f0", wrap="word")
    log_box.pack(fill="both", expand=True)

    def log(t):
        log_box.insert(tk.END, t + "\n")
        log_box.see(tk.END)
        root.update_idletasks()

    btn_style = {"bg": "#1f1f1f", "fg": "#0f0", "bd": 0,
                 "font": ("Consolas", 10, "bold"),
                 "activebackground": "#333", "activeforeground": "#0f0",
                 "height": 2, "anchor": "w", "padx": 10}

    def add_btn(text, cmd, ov=None, side="top"):
        s = btn_style.copy()
        if ov:
            s.update(ov)
        tk.Button(left, text=text, command=cmd, **s).pack(fill="x", pady=2, side=side)

    def act_friends():
        log_box.delete("1.0", tk.END)
        fr = client.fetch_friends()
        log(f"👥 {len(fr)} bạn bè:")
        for i, f in enumerate(fr[:50], 1):
            log(f"  {i}. {f['name']} ({f['id']})")

    def act_groups():
        log_box.delete("1.0", tk.END)
        gs = client.fetch_groups()
        log(f"🏘️ {len(gs)} nhóm:")
        for i, g in enumerate(gs, 1):
            log(f"  {i}. {g['name']} ({g['id']})")

    def act_anti_ghost():
        log_box.delete("1.0", tk.END)
        log("🔍 Đang check...")
        def run():
            try:
                blocked = client.scan_blocked()
                log(f"\n🚫 {len(blocked)} người có thể block:")
                for b in blocked:
                    log(f"   • {b['name']} ({b['id']})")
                if not blocked:
                    log("✅ Không ai block.")
            except Exception as e:
                log(f"❌ {e}")
        threading.Thread(target=run, daemon=True).start()

    def act_proxy():
        w = tk.Toplevel(root)
        w.title("Proxy")
        w.geometry("400x180")
        w.configure(bg="#111")
        tk.Label(w, text="Proxy URL:", bg="#111", fg="#0f0",
                 font=("Consolas", 10)).pack(pady=(15, 0))
        e = tk.Entry(w, bg="#000", fg="#0f0", insertbackground="#0f0",
                     font=("Consolas", 10), width=45)
        e.pack(pady=5)
        tk.Label(w, text="VD: http://user:pass@ip:port", bg="#111", fg="#666",
                 font=("Consolas", 8)).pack()
        def apply():
            url = e.get().strip()
            if url:
                ProxyManager.set(url)
                log(f"🌐 Proxy: {url}")
            w.destroy()
        tk.Button(w, text="ÁP DỤNG", command=apply, bg="#0a0", fg="#000",
                  font=("Consolas", 10, "bold"), bd=0, height=2).pack(
            fill="x", padx=20, pady=10)

    def act_health():
        log_box.delete("1.0", tk.END)
        idle = client.watchdog.idle()
        log("💓 Anti-drop status")
        log(f"  • Idle: {idle:.1f}s / timeout {client.watchdog.timeout}s")
        log(f"  • Reconnecting: {'CÓ' if client._reconnecting.is_set() else 'KHÔNG'}")
        log(f"  • Circuit: {'MỞ ' + str(int(client.breaker.remaining())) + 's' if client.breaker.is_open() else 'ĐÓNG'}")
        log(f"  • Counter: {client.counter}")

    add_btn("👥 Bạn bè", act_friends)
    add_btn("🏘️ Nhóm", act_groups)
    add_btn("🔍 Anti-ghost", act_anti_ghost)
    add_btn("🌐 Set proxy", act_proxy)
    add_btn("🚫 Tắt proxy", lambda: ProxyManager.set(None))
    add_btn("💓 Health", act_health)
    add_btn("🔄 Reconnect", lambda: client.force_reconnect("gui"))
    add_btn("❌ Thoát", root.quit, {"bg": "#3a0000", "fg": "#f66"}, "bottom")
    log("💀 GUI sẵn sàng.")
    root.mainloop()


# ============================================================
# SPEED + ANTI-DROP SETTINGS
# ============================================================
def speed_menu(client):
    while True:
        s = client.settings
        if HAS_RICH:
            try:
                t = Table(title="[bold cyan]⚙️ TỐC ĐỘ & CHỐNG RỚT[/bold cyan]",
                          border_style="bright_blue", show_header=False,
                          padding=(0, 2))
                t.add_column("STT", style="bold green", width=5, justify="center")
                t.add_column("Cài đặt", style="bright_white")
                t.add_column("Giá trị", style="bold yellow", justify="right")
                rows = [
                    ("1", "Typing indicator", "🟢" if s.get('typing_delay') else "🔴"),
                    ("2", "Fake typing", "🟢" if s.get('fake_typing') else "🔴"),
                    ("3", "Random delay", "🟢" if s.get('randomize_delay') else "🔴"),
                    ("4", "Rate limit", f"{s.get('rate_per_min')}/min"),
                    ("5", "Delay tin", f"{s.get('delay')}s"),
                    ("6", "Stealth", "🟢" if s.get('stealth') else "🔴"),
                    ("7", "Emoji", "🟢" if s.get('emoji') else "🔴"),
                    ("8", "Keepalive base", f"{s.get('keepalive_base')}s"),
                    ("9", "Keepalive jitter", f"±{s.get('keepalive_jitter')}s"),
                    ("10", "Watchdog timeout", f"{s.get('watchdog_timeout')}s"),
                    ("11", "Retry max", str(s.get('retry_max'))),
                    ("12", "Reconnect max", str(s.get('reconnect_max'))),
                    ("13", "Reconnect cap", f"{s.get('reconnect_cap')}s"),
                    ("14", "Circuit breaker", "🟢" if s.get('circuit_break') else "🔴"),
                    ("15", "Circuit threshold", str(s.get('circuit_threshold'))),
                    ("16", "Circuit cooldown", f"{s.get('circuit_cooldown')}s"),
                    ("17", "Auto-resume", "🟢" if s.get('auto_resume') else "🔴"),
                    ("18", "Reset mặc định", "♻️"),
                    ("0", "Quay lại", "←"),
                ]
                for r in rows:
                    t.add_row(f"❯ {r[0]}", r[1], r[2])
                console.print(t)
            except Exception:
                pass
        else:
            print("\n⚙️ TỐC ĐỘ & CHỐNG RỚT")
            for k in ("typing_delay", "fake_typing", "randomize_delay",
                      "rate_per_min", "delay", "stealth", "emoji",
                      "keepalive_base", "keepalive_jitter", "watchdog_timeout",
                      "retry_max", "reconnect_max", "reconnect_cap",
                      "circuit_break", "circuit_threshold", "circuit_cooldown",
                      "auto_resume"):
                print(f"  {k}: {s.get(k)}")

        c = rinput("> Chọn: ")
        if c == '0':
            return
        elif c == '1':
            s['typing_delay'] = not s.get('typing_delay', False)
        elif c == '2':
            s['fake_typing'] = not s.get('fake_typing', False)
        elif c == '3':
            s['randomize_delay'] = not s.get('randomize_delay', False)
        elif c == '4':
            v = rinput("Rate (tin/phút): ")
            if v.isdigit() and int(v) > 0:
                s['rate_per_min'] = int(v)
                client.rate_limiter.max = int(v)
        elif c == '5':
            try:
                d = float(rinput("Delay (giây): ") or "0")
                if d >= 0:
                    s['delay'] = d
            except ValueError:
                pass
        elif c == '6':
            s['stealth'] = not s.get('stealth', True)
        elif c == '7':
            s['emoji'] = not s.get('emoji', False)
        elif c == '8':
            v = rinput("Keepalive base (giây, >=5): ")
            if v.isdigit() and int(v) >= 5:
                s['keepalive_base'] = int(v)
        elif c == '9':
            v = rinput("Keepalive jitter (giây): ")
            if v.isdigit() and int(v) >= 0:
                s['keepalive_jitter'] = int(v)
        elif c == '10':
            v = rinput("Watchdog timeout (giây, >=30): ")
            if v.isdigit() and int(v) >= 30:
                s['watchdog_timeout'] = int(v)
                client.watchdog.timeout = int(v)
        elif c == '11':
            v = rinput("Retry max (1-10): ")
            if v.isdigit() and 1 <= int(v) <= 10:
                s['retry_max'] = int(v)
        elif c == '12':
            v = rinput("Reconnect max (1-50): ")
            if v.isdigit() and 1 <= int(v) <= 50:
                s['reconnect_max'] = int(v)
        elif c == '13':
            try:
                v = float(rinput("Reconnect cap (giây, >=10): ") or "0")
                if v >= 10:
                    s['reconnect_cap'] = v
            except ValueError:
                pass
        elif c == '14':
            s['circuit_break'] = not s.get('circuit_break', True)
        elif c == '15':
            v = rinput("Circuit threshold (2-20): ")
            if v.isdigit() and 2 <= int(v) <= 20:
                s['circuit_threshold'] = int(v)
                client.breaker.threshold = int(v)
        elif c == '16':
            v = rinput("Circuit cooldown (giây, >=60): ")
            if v.isdigit() and int(v) >= 60:
                s['circuit_cooldown'] = int(v)
                client.breaker.cooldown = int(v)
        elif c == '17':
            s['auto_resume'] = not s.get('auto_resume', True)
        elif c == '18':
            s = DEFAULT_SETTINGS.copy()
            client.rate_limiter.max = s['rate_per_min']
            client.watchdog.timeout = s['watchdog_timeout']
            client.watchdog.interval = s['watchdog_interval']
            client.breaker.threshold = s['circuit_threshold']
            client.breaker.cooldown = s['circuit_cooldown']
            rprint("[green]♻️ Đã reset.[/green]")
        save_settings(s)
        client.settings = s


# ============================================================
# MAIN
# ============================================================
def main():
    install_signal_handler()
    print_interface()

    rprint("[bold yellow]🔒 NHẬP MẬT KHẨU[/bold yellow]")
    while True:
        try:
            p = input("🔑 Mật Khẩu: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        if not p:
            rprint("[red]❌ Chưa nhập.[/red]")
            continue
        if hashlib.sha256(normalize_password(p).encode()).hexdigest() in PWD_HASHES:
            rprint("[bold green]✅ Đúng.[/bold green]")
            break
        rprint("[bold red]❌ Sai![/bold red]")

    imei = cookies = None
    si, sc, sat = load_session()
    if si and sc:
        rprint("\n[cyan]📁 SESSION CÓ SẴN[/cyan]")
        rprint(f"   {sat} • IMEI {si}")
        ans = input("[cyan]👉 Dùng? (Enter/Y = có, N = mới): [/cyan]").strip().lower()
        if ans in ('', 'y', 'yes', 'c', 'có'):
            imei, cookies = si, sc
        else:
            clear_session()

    if not imei or not cookies:
        rprint("\n[green]===== KẾT NỐI ZALO =====[/green]")
        imei = input("🍏 IMEI: ").strip()
        while True:
            cookies = parse_cookie_string(input("🖥️ Cookie: ").strip())
            if cookies:
                break
            rprint("[red]❌ Cookie lỗi![/red]")
        save_session(imei, cookies)

    try:
        rprint("[cyan]🔄 Đang kết nối Zalo...[/cyan]")
        client = ZaloWarClient(imei, cookies,
                               rate_per_min=load_settings().get("rate_per_min", 120))
        rprint("[bold green]✅ Kết nối Zalo thành công![/bold green]\n")
    except Exception as e:
        rprint(f"[bold red]❌ Kết nối lỗi: {e}[/bold red]")
        return

    while True:
        print_interface()
        print_main_menu()
        try:
            choice = input("\n👉 Lựa chọn: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if choice == '12':
            rprint("[yellow]👋 Tạm biệt![/yellow]")
            sys.exit()
        if choice == '3':
            clear_session()
            rprint("[yellow]🗑️ Xoá session. Chạy lại tool.[/yellow]")
            sys.exit()
        if choice == '4':
            export_targets(client)
            input("Enter...")
            continue
        if choice == '5':
            fr = client.fetch_friends()
            if HAS_RICH:
                try:
                    t = Table(title=f"[bold cyan]👥 {len(fr)} BẠN BÈ[/bold cyan]",
                              border_style="bright_blue")
                    t.add_column("#", style="bold yellow", width=4)
                    t.add_column("Tên", style="bright_white")
                    t.add_column("ID", style="dim cyan")
                    for i, f in enumerate(fr[:30], 1):
                        t.add_row(str(i), f['name'], f['id'])
                    if len(fr) > 30:
                        t.add_row("...", f"và {len(fr)-30} người khác", "")
                    console.print(t)
                except Exception:
                    pass
            else:
                print(f"\n=> {len(fr)} bạn bè\n")
                for i, f in enumerate(fr[:30], 1):
                    print(f"   {i:2d}. {f['name']} ({f['id']})")
            input("Enter...")
            continue
        if choice == '6':
            sub = input("1. Bạn bè    2. Member 1 nhóm: ").strip()
            if sub == '1':
                blocked = client.scan_blocked()
            elif sub == '2':
                gid, _ = select_group(client)
                blocked = client.scan_blocked(gid) if gid else []
            else:
                continue
            if blocked:
                rprint(f"\n[red]🚫 {len(blocked)} người có thể block:[/red]")
                for b in blocked:
                    rprint(f"   • {b['name']} ({b['id']})")
            else:
                rprint("\n[green]✅ Không ai block.[/green]")
            input("Enter...")
            continue
        if choice == '7':
            mg = input("Giới hạn nhóm (Enter = hết): ").strip()
            try:
                mg = int(mg) if mg else None
            except ValueError:
                mg = None
            client.scan_all_groups_info(mg)
            input("Enter...")
            continue
        if choice == '8':
            proxies = load_proxies()
            rprint(f"\n[cyan]🌐 PROXY MANAGER[/cyan]")
            rprint(f"Hiện tại: {ProxyManager._current or 'không'}")
            rprint(f"Đã lưu: {len(proxies)}")
            sub = input("1. Set  2. Tắt  3. Xem  4. Xoá: ").strip()
            if sub == '1':
                name = input("Tên: ").strip()
                url = input("URL: ").strip()
                if name and url:
                    proxies[name] = url
                    save_proxies(proxies)
                    ProxyManager.set(url)
            elif sub == '2':
                ProxyManager.set(None)
            elif sub == '3':
                for n, u in proxies.items():
                    rprint(f"   [cyan]{n}[/cyan]: {u}")
            elif sub == '4':
                save_proxies({})
                rprint("[yellow]🗑️ Xoá hết.[/yellow]")
            input("Enter...")
            continue
        if choice == '9':
            rprint("[cyan]🖥️ Đang mở GUI...[/cyan]")
            launch_gui(client)
            continue
        if choice == '10':
            speed_menu(client)
            continue
        if choice == '11':
            client.force_reconnect("manual")
            input("Đã kích hoạt reconnect. Enter...")
            continue
        if choice not in ('1', '2'):
            rprint("[red]❌ Lỗi![/red]")
            input("Enter...")
            continue

        print_level2_menu(choice)
        level2 = input("👉 Chọn: ").strip()
        valid = ['1', '3'] if choice == '2' else ['1', '2', '3', '4']
        if level2 not in valid:
            rprint("[red]❌ Lỗi![/red]")
            input("Enter...")
            continue

        use_color = rconfirm("Màu?")
        font_size = "40"
        if use_color:
            fs = input("Cỡ chữ (40-300): ").strip()
            if fs.isdigit() and 40 <= int(fs) <= 300:
                font_size = fs

        stealth = rconfirm("Chống trùng tin?")
        emoji = rconfirm("Chèn emoji?")

        di = input("> Delay (bé nhất 0.05): ").strip()
        try:
            delay_time = max(0.05, float(di) if di else 0.1)
        except ValueError:
            delay_time = 0.1

        is_single = level2 in ('1', '2')
        need_tag = level2 in ('2', '4')
        client.running.clear()

        if choice == '1':
            gid, gname = select_group(client)
            if not gid:
                input("Enter...")
                continue
            uids, all_mode = [], False
            if need_tag:
                uids, all_mode = select_members(client, gid)

            if is_single:
                text = input("📝 Nội dung: ").strip()
                if not text:
                    input("Enter...")
                    continue
                rprint(f"\n[green]🚀 Gửi... (delay {delay_time}s)[/green]")
                rprint("[dim]⏹️ 'stop' để dừng[/dim]\n")
                client.running.set()
                def sender_g():
                    while client.running.is_set():
                        client._wait_if_reconnecting()
                        if not client.running.is_set():
                            break
                        client.send_to_group(gid, text, uids, all_mode,
                                             use_color, font_size, stealth, emoji)
                        client._sleep(delay_time)
                t = threading.Thread(target=sender_g, daemon=True)
                t.start()
                wait_for_stop(client, [t])
            else:
                fn, mode, fd = ask_file_input()
                rprint(f"\n[green]🚀 Spam file...[/green]")
                t = threading.Thread(target=client.loop_spam_group,
                    args=(gid, fn, mode, uids, all_mode, use_color,
                          font_size, delay_time, fd, stealth, emoji), daemon=True)
                t.start()
                wait_for_stop(client, [t])
        else:
            rprint("\n[cyan]==== • LEVEL 4 • ====[/cyan]")
            print("1. Người trong box")
            print("2. Người từng nhắn")
            print("3. Bạn bè")
            print("4. SĐT")
            lv4 = input("> ").strip()
            uids = []

            if lv4 == '1':
                gid, _ = select_group(client)
                if not gid:
                    input("Enter...")
                    continue
                members = client.fetch_members(gid)
                if not members:
                    input("Enter...")
                    continue
                for i, m in enumerate(members, 1):
                    print(f"  {i}. {m['name']} ({m['id']})")
                idxs = parse_multi_input(input("👉 STT (dấu phẩy): ").strip(),
                                         len(members))
                uids = [members[i-1]['id'] for i in idxs]
            elif lv4 == '2':
                convs = [c for c in client.fetch_all_conversations() if c.get('type') == 'user']
                if not convs:
                    input("Không có. Enter...")
                    continue
                for i, c in enumerate(convs, 1):
                    print(f"  {i}. {c['name']} ({c['id']})")
                raw = input("👉 STT: ").strip()
                if raw.isdigit() and 1 <= int(raw) <= len(convs):
                    uids = [convs[int(raw)-1]['id']]
            elif lv4 == '3':
                friends = client.fetch_friends()
                if not friends:
                    input("Không có. Enter...")
                    continue
                print(f"\n👫 {len(friends)} bạn bè:")
                for i, f in enumerate(friends, 1):
                    print(f"  {i}. {f['name']} ({f['id']})")
                idxs = parse_multi_input(input("👉 STT (dấu phẩy): ").strip(),
                                         len(friends))
                uids = [friends[i-1]['id'] for i in idxs]
            elif lv4 == '4':
                input("❌ Zalo không hỗ trợ SĐT. Enter...")
                continue
            else:
                rprint("[red]❌ Lỗi![/red]")
                input("Enter...")
                continue

            if not uids:
                rprint("[red]❌ Không có người nhận![/red]")
                input("Enter...")
                continue

            if is_single:
                text = input("📝 Nội dung: ").strip()
                if not text:
                    input("Enter...")
                    continue
                rprint(f"\n[green]🚀 Gửi riêng... (delay {delay_time}s)[/green]")
                rprint("[dim]⏹️ 'stop' để dừng[/dim]\n")
                client.running.set()
                def sender_u():
                    while client.running.is_set():
                        for uid in uids:
                            if not client.running.is_set():
                                break
                            client._wait_if_reconnecting()
                            if not client.running.is_set():
                                break
                            client.send_to_user(uid, text, use_color, font_size,
                                                stealth, emoji)
                            client._sleep(delay_time)
                t = threading.Thread(target=sender_u, daemon=True)
                t.start()
                wait_for_stop(client, [t])
            else:
                fn, mode, fd = ask_file_input()
                rprint(f"\n[green]🚀 Spam file riêng...[/green]")
                threads = []
                for uid in uids:
                    t = threading.Thread(target=client.loop_spam_user,
                        args=(uid, fn, mode, use_color, font_size,
                              delay_time, fd, stealth, emoji), daemon=True)
                    t.start()
                    threads.append(t)
                wait_for_stop(client, threads)


# ... (giữ nguyên toàn bộ code bên trên)

def run_console():
    main()

if __name__ == "__main__":
    run_console()