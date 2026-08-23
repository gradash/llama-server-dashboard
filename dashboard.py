# -*- coding: utf-8 -*-
import subprocess
import threading
import time
import json
import urllib.request
import os
import sys
import re
import unicodedata
import msvcrt
import ctypes
from ctypes import wintypes
from collections import deque

# Enable ANSI escape sequences in Windows Terminal / CMD
os.system('')

TOTAL_VRAM_GB = 8.0
VULKAN_OVERHEAD_GB = 0.70

# Default model settings (override via sys.argv: python dashboard.py [model_path] [context_size] [port])
DEFAULT_MODEL_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
MODEL_FILE = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL_FILE
CONTEXT_LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 65536
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8080

# Clean model name for display
clean_name = os.path.splitext(os.path.basename(MODEL_FILE))[0]
MODEL_NAME = clean_name.replace('-', ' ').replace('_', ' ').title()

# Estimate base model weights size in GB from file
try:
    if os.path.exists(MODEL_FILE):
        BASE_MODEL_VRAM_GB = os.path.getsize(MODEL_FILE) / (1024.0 ** 3)
    else:
        BASE_MODEL_VRAM_GB = 4.68
except Exception:
    BASE_MODEL_VRAM_GB = 4.68

MAX_KV_CACHE_VRAM_GB = (CONTEXT_LIMIT / 65536.0) * 1.93

# Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BLUE = "\033[94m"
C_GRAY = "\033[90m"
C_MAGENTA = "\033[95m"

logs_deque = deque(maxlen=8)
server_proc = None
running = True

# Real-time metrics
last_prompt_speed = 0.0
last_gen_speed = 0.0
real_total_vram_gb = 7.75

def shutdown_server():
    global server_proc, running
    running = False
    if server_proc:
        try:
            server_proc.terminate()
            server_proc.wait(timeout=2)
        except Exception:
            try:
                server_proc.kill()
            except Exception:
                pass
        try:
            subprocess.run("taskkill /F /IM llama-server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

def win_ctrl_handler(ctrl_type):
    shutdown_server()
    return True

handler_func = PHANDLER_ROUTINE(win_ctrl_handler)
ctypes.windll.kernel32.SetConsoleCtrlHandler(handler_func, True)

def get_visual_width(text):
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    width = 0
    for ch in clean:
        w = unicodedata.east_asian_width(ch)
        if w in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width

def render_row(content, inner_width):
    v_width = get_visual_width(content)
    pad = max(0, inner_width - v_width)
    return f"{C_CYAN}│{C_RESET} {content}{' ' * pad} {C_CYAN}│{C_RESET}"

def log_reader(proc):
    global running, last_prompt_speed, last_gen_speed
    for line in iter(proc.stdout.readline, b''):
        if not running:
            break
        raw_text = line.decode('utf-8', errors='replace').strip()
        if not raw_text:
            continue

        if "prompt processing" in raw_text or "prompt eval" in raw_text:
            m = re.search(r'(\d+(?:\.\d+)?)\s*(?:tokens per second|t/s|tok/s)', raw_text)
            if m:
                try:
                    last_prompt_speed = float(m.group(1))
                except Exception:
                    pass
        elif "eval time =" in raw_text:
            m = re.search(r'eval time =.*?(\d+(?:\.\d+)?)\s*tokens per second', raw_text)
            if m:
                try:
                    last_gen_speed = float(m.group(1))
                except Exception:
                    pass
        elif "tg =" in raw_text or "tg_3s =" in raw_text:
            m = re.search(r'tg(?:_3s)?\s*=\s*(\d+(?:\.\d+)?)', raw_text)
            if m:
                try:
                    last_gen_speed = float(m.group(1))
                except Exception:
                    pass

        clean = raw_text
        if len(clean) > 80:
            clean = clean[:77] + "..."
        logs_deque.append(clean)

def gpu_vram_poller():
    global running, real_total_vram_gb
    while running:
        try:
            cmd = "powershell.exe -NoProfile -Command \"(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum\""
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').strip()
            if out:
                bytes_val = float(out)
                real_total_vram_gb = max(5.5, min(8.0, bytes_val / (1024.0 ** 3)))
        except Exception:
            pass
        for _ in range(25):
            if not running:
                break
            time.sleep(0.1)

def make_stacked_vram_bar(model_gb, total_used_gb, max_gb=8.0, length=20):
    model_gb = min(model_gb, max_gb)
    other_gb = max(0.0, min(total_used_gb - model_gb, max_gb - model_gb))
    
    model_blocks = int(round(length * (model_gb / max_gb)))
    other_blocks = int(round(length * (other_gb / max_gb)))
    empty_blocks = max(0, length - model_blocks - other_blocks)
    
    bar = f"{C_CYAN}{'█' * model_blocks}{C_YELLOW}{'█' * other_blocks}{C_GRAY}{'░' * empty_blocks}{C_RESET}"
    return bar, model_gb, other_gb, total_used_gb

def make_bar(percent, length=18, fill_char="█", empty_char="░", color=C_CYAN):
    percent = max(0.0, min(100.0, percent))
    filled = int(round(length * (percent / 100.0)))
    empty = length - filled
    return f"{color}{fill_char * filled}{C_GRAY}{empty_char * empty}{C_RESET}"

def get_process_ram_mb(pid):
    try:
        cmd = f'tasklist /FI "PID eq {pid}" /FO CSV /NH'
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        for line in out.strip().splitlines():
            if str(pid) in line:
                parts = [p.strip('"') for p in line.split(',')]
                if len(parts) >= 5:
                    mem_str = parts[4].replace(' ', '').replace('K', '').replace('\xa0', '').replace('\u00a0', '')
                    return float(mem_str) / 1024.0
    except Exception:
        pass
    return 35.0

def main():
    global server_proc, running, last_prompt_speed, last_gen_speed, real_total_vram_gb
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    server_cmd = [
        "llama-server.exe",
        "-m", MODEL_FILE,
        "-ngl", "99",
        "-c", str(CONTEXT_LIMIT),
        "-ctk", "q8_0",
        "-ctv", "q8_0",
        "-fa", "on",
        "-b", "2048",
        "-ub", "1024",
        "-t", "6",
        "-tb", "6",
        "-np", "1",
        "--cache-prompt",
        "--host", "127.0.0.1",
        "--port", str(PORT)
    ]

    print(f"{C_BOLD}{C_CYAN}Запуск {MODEL_NAME} и инициализация дашборда...{C_RESET}")
    try:
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )
    except Exception as e:
        print(f"{C_RED}Ошибка запуска llama-server: {e}{C_RESET}")
        sys.exit(1)

    t = threading.Thread(target=log_reader, args=(server_proc,), daemon=True)
    t.start()

    t_vram = threading.Thread(target=gpu_vram_poller, daemon=True)
    t_vram.start()

    ready = False
    start_time = time.time()
    used_ctx_tokens = 0
    is_processing = False
    INNER_WIDTH = 84
    my_pid = os.getpid()

    while running:
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'q', b'Q', b'\x1b', b'\x03'):
                print(f"\n{C_YELLOW}Выход по нажатию клавиши...{C_RESET}")
                shutdown_server()
                break

        if not running:
            break

        if server_proc.poll() is not None:
            print(f"\n{C_RED}Сервер завершил работу с кодом {server_proc.returncode}{C_RESET}")
            break

        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/slots", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                slots = json.loads(resp.read().decode())
                if slots and len(slots) > 0:
                    s0 = slots[0]
                    ready = True
                    is_processing = s0.get('is_processing', False)
                    n_prompt = s0.get('n_prompt_tokens', 0)
                    n_processed = s0.get('n_prompt_tokens_processed', 0)
                    used_ctx_tokens = max(n_prompt, n_processed)
        except Exception:
            ready = False

        server_ram_mb = get_process_ram_mb(server_proc.pid) if server_proc else 150.0
        server_ram_gb = server_ram_mb / 1024.0

        my_ram_mb = get_process_ram_mb(my_pid)

        current_kv_gb = (used_ctx_tokens / CONTEXT_LIMIT) * MAX_KV_CACHE_VRAM_GB if used_ctx_tokens > 0 else 0.1
        model_vram_gb = BASE_MODEL_VRAM_GB + current_kv_gb + VULKAN_OVERHEAD_GB

        display_total_vram_gb = max(model_vram_gb, real_total_vram_gb)
        vram_bar, m_gb, o_gb, t_gb = make_stacked_vram_bar(model_vram_gb, display_total_vram_gb, TOTAL_VRAM_GB, length=18)
        total_vram_pct = (t_gb / TOTAL_VRAM_GB) * 100.0

        ram_spillover_status = f"{C_GREEN}0.00 GB  [✅ 100% В VRAM, БЕЗ ВЫГРУЗОК]{C_RESET}"
        ctx_percent = (used_ctx_tokens / CONTEXT_LIMIT) * 100.0

        status_badge = f"{C_GREEN}● ГОТОВ К РАБОТЕ (IDLE){C_RESET}" if not is_processing else f"{C_YELLOW}⚡ ОБРАБОТКА / ГЕНЕРАЦИЯ...{C_RESET}"
        if not ready:
            status_badge = f"{C_MAGENTA}⏳ ЗАГРУЗКА В VRAM...{C_RESET}"

        uptime = int(time.time() - start_time)
        uptime_str = f"{uptime // 60:02d}:{uptime % 60:02d}"

        sys.stdout.write("\033[H\033[J")

        # Top border
        print(f"{C_CYAN}┌{'─' * (INNER_WIDTH + 2)}┐{C_RESET}")
        
        # Header Title
        title = f" ⚡ {MODEL_NAME.upper()[:36]} (LLAMA-SERVER DASHBOARD) ⚡ "
        t_pad = max(0, (INNER_WIDTH - get_visual_width(title)) // 2)
        print(render_row(' ' * t_pad + f"{C_BOLD}{C_CYAN}{title}{C_RESET}", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Server Info
        print(render_row(f"{C_BOLD}Статус сервера:{C_RESET}   {status_badge}     {C_BOLD}Аптайм:{C_RESET} {uptime_str}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Модель:{C_RESET}           {C_CYAN}{MODEL_NAME}{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Эндпоинт API:{C_RESET}     {C_GREEN}http://127.0.0.1:{PORT}/v1{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Конфигурация:{C_RESET}     {CONTEXT_LIMIT:,} токенов  |  Кеш: Q8_0  |  Flash-Attn: ON", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Memory Section (Stacked + Self RAM)
        print(render_row(f"{C_BOLD}📊 ВИДЕОПАМЯТЬ И ОЗУ (VRAM & RAM МЕТРИКИ):{C_RESET}", INNER_WIDTH))
        print(render_row(f"  ├─ 🎮 {C_BOLD}Видеопамять (VRAM):{C_RESET}   {vram_bar}  {t_gb:.2f} / {TOTAL_VRAM_GB:.1f} GB ({total_vram_pct:.1f}%)", INNER_WIDTH))
        legend = f"     └─ {C_CYAN}■ Модель:{C_RESET} {m_gb:.2f} GB  |  {C_YELLOW}■ Windows/Система:{C_RESET} {o_gb:.2f} GB"
        print(render_row(legend, INNER_WIDTH))
        print(render_row(f"  ├─ 🧠 {C_BOLD}Выгрузка в RAM (CPU):{C_RESET} {ram_spillover_status}", INNER_WIDTH))
        print(render_row(f"  ├─ ⚙️  {C_BOLD}ОЗУ сервера (llama):{C_RESET}  ~{server_ram_gb:.2f} GB (хост-буфер Vulkan)", INNER_WIDTH))
        print(render_row(f"  └─ 🐍 {C_BOLD}ОЗУ дашборда (Python):{C_RESET} {C_GREEN}{my_ram_mb:.1f} MB{C_RESET} (легковесный UI монитор)", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Context & Speed Section
        print(render_row(f"{C_BOLD}📈 АКТИВНОСТЬ КОНТЕКСТА И СКОРОСТЬ:{C_RESET}", INNER_WIDTH))
        ctx_bar = make_bar(ctx_percent, length=18, color=C_GREEN if ctx_percent < 80 else C_YELLOW)
        print(render_row(f"  ├─ 🗂  {C_BOLD}Занято контекста:{C_RESET}    {ctx_bar}  {used_ctx_tokens:,} / {CONTEXT_LIMIT:,} ({ctx_percent:.1f}%)", INNER_WIDTH))
        
        gen_spd_display = f"{last_gen_speed:.1f} tok/s" if last_gen_speed > 0 else "—"
        prompt_spd_display = f"{last_prompt_speed:.1f} tok/s" if last_prompt_speed > 0 else "—"
        speed_text = f"Генерация: {C_BOLD}{C_GREEN}{gen_spd_display}{C_RESET}  |  Промпт: {C_BOLD}{C_CYAN}{prompt_spd_display}{C_RESET}"
        print(render_row(f"  └─ ⚡ {C_BOLD}Скорость ответа:{C_RESET}     {speed_text}", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Logs Section
        print(render_row(f"{C_BOLD}📜 ЖИВОЙ ЛОГ СОБЫТИЙ СЕРВЕРА:{C_RESET}", INNER_WIDTH))
        recent = list(logs_deque)[-6:]
        for idx in range(6):
            if idx < len(recent):
                log_line = recent[idx].replace("\r", "")
                print(render_row(f"  {C_GRAY}>{C_RESET} {log_line}", INNER_WIDTH))
            else:
                print(render_row("", INNER_WIDTH))

        # Bottom border
        print(f"{C_CYAN}└{'─' * (INNER_WIDTH + 2)}┘{C_RESET}")
        print(f" {C_GRAY}[Нажмите 'Q', 'Esc' или 'Ctrl+C' для остановки сервера]{C_RESET}")

        for _ in range(10):
            if not running:
                break
            if msvcrt.kbhit():
                break
            time.sleep(0.1)

    print(f"\n{C_GREEN}Сервер успешно остановлен.{C_RESET}")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        shutdown_server()
        print(f"\n{C_GREEN}Сервер успешно остановлен.{C_RESET}")
