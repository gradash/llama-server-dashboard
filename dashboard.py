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
import datetime
import winreg
from ctypes import wintypes
from collections import deque

# Enable ANSI escape sequences in Windows Terminal / CMD
os.system('')

def detect_gpu_hardware():
    """
    Universal GPU & VRAM Detector:
    Auto-detects NVIDIA (CUDA), AMD (Vulkan), and Intel GPUs with exact total VRAM capacity.
    """
    gpu_name = "Generic GPU"
    total_vram_gb = 16.0
    vendor_type = "AMD Vulkan"
    is_nvidia = False

    # 1. Try NVIDIA via nvidia-smi
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.2
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().splitlines()[0].split(",")
            gpu_name = parts[0].strip()
            total_vram_gb = round(float(parts[1].strip()) / 1024.0, 1)
            vendor_type = "NVIDIA CUDA"
            is_nvidia = True
            return gpu_name, total_vram_gb, vendor_type, is_nvidia
    except Exception:
        pass

    # 2. Try Windows Registry for exact 64-bit VRAM size (AMD & Intel & NVIDIA fallback)
    try:
        reg_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as base_key:
            subkeys_count = winreg.QueryInfoKey(base_key)[0]
            for i in reversed(range(subkeys_count)):
                subkey_name = winreg.EnumKey(base_key, i)
                if not subkey_name.isdigit():
                    continue
                with winreg.OpenKey(base_key, subkey_name) as subkey:
                    try:
                        desc, _ = winreg.QueryValueEx(subkey, "DriverDesc")
                    except Exception:
                        continue
                    try:
                        qw_mem, _ = winreg.QueryValueEx(subkey, "HardwareInformation.qwMemorySize")
                        mem_gb = round(qw_mem / (1024.0 ** 3), 1)
                        if mem_gb > 0:
                            gpu_name = desc.strip()
                            total_vram_gb = mem_gb
                            name_u = gpu_name.upper()
                            if "NVIDIA" in name_u:
                                vendor_type = "NVIDIA"
                                is_nvidia = True
                            elif "AMD" in name_u or "RADEON" in name_u:
                                vendor_type = "AMD Vulkan"
                            elif "INTEL" in name_u:
                                vendor_type = "Intel"
                            return gpu_name, total_vram_gb, vendor_type, is_nvidia
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Fallback to Windows CIM
    try:
        cmd = "powershell.exe -NoProfile -Command \"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $g = Get-CimInstance Win32_VideoController | Select-Object -First 1; Write-Output ($g.Name + '|' + $g.AdapterRAM)\""
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=2.0).decode('utf-8', errors='ignore').strip()
        if "|" in out:
            name, ram = out.split("|", 1)
            gpu_name = name.strip()
            name_u = gpu_name.upper()
            if "NVIDIA" in name_u:
                vendor_type = "NVIDIA"
                is_nvidia = True
            elif "AMD" in name_u or "RADEON" in name_u:
                vendor_type = "AMD Vulkan"
            elif "INTEL" in name_u:
                vendor_type = "Intel"
    except Exception:
        pass

    return gpu_name, total_vram_gb, vendor_type, is_nvidia

# Auto-detect hardware
GPU_NAME, TOTAL_VRAM_GB, GPU_VENDOR, IS_NVIDIA = detect_gpu_hardware()
VULKAN_OVERHEAD_GB = 0.70 if not IS_NVIDIA else 0.40

def parse_cli_args(argv):
    """
    Universal Argument Parser:
    1. Supports default zero-config launch
    2. Supports positional shorthand: python dashboard.py [model] [context] [port]
    3. Supports FULL native llama-server flags: python dashboard.py -m model.gguf -c 131072 -ngl 33 --temp 0.2 --jinja
    """
    meta = {
        "model_file": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "context_limit": 65536,
        "port": 8080,
        "ngl": "99",
        "ctk": "q8_0",
        "ctv": "q8_0",
        "fa": "on",
        "b": "2048",
        "ub": "1024",
        "t": "6",
        "tb": "6",
        "np": "1",
        "draft_file": None
    }
    passthrough_args = []
    
    if argv and not argv[0].startswith('-'):
        # Positional shorthand mode
        if len(argv) >= 1:
            meta["model_file"] = argv[0]
        if len(argv) >= 2:
            try:
                meta["context_limit"] = int(argv[1])
            except ValueError:
                pass
        if len(argv) >= 3:
            try:
                meta["port"] = int(argv[2])
            except ValueError:
                pass
        passthrough_args = argv[3:]
    else:
        # Full native flag mode
        i = 0
        while i < len(argv):
            arg = argv[i]
            val = argv[i+1] if (i + 1 < len(argv) and not argv[i+1].startswith('-')) else None
            
            if arg in ('-m', '--model') and val:
                meta["model_file"] = val
                i += 2
                continue
            elif arg in ('-c', '--ctx-size') and val:
                try:
                    meta["context_limit"] = int(val)
                except ValueError:
                    pass
                i += 2
                continue
            elif arg in ('--port',) and val:
                try:
                    meta["port"] = int(val)
                except ValueError:
                    pass
                i += 2
                continue
            elif arg in ('-ngl', '--n-gpu-layers', '--gpu-layers') and val:
                meta["ngl"] = val
                i += 2
                continue
            elif arg in ('-ctk', '--cache-type-k') and val:
                meta["ctk"] = val
                i += 2
                continue
            elif arg in ('-ctv', '--cache-type-v') and val:
                meta["ctv"] = val
                i += 2
            elif arg in ('-md', '--model-draft', '--spec-draft-model') and val:
                meta["draft_file"] = val
                passthrough_args.extend([arg, val])
                i += 2
                continue
            elif arg in ('-t', '--threads') and val:
                meta["t"] = val
                i += 2
                continue
            elif arg in ('-tb', '--threads-batch') and val:
                meta["tb"] = val
                i += 2
                continue
            elif arg in ('-b', '--batch-size') and val:
                meta["b"] = val
                i += 2
                continue
            elif arg in ('-ub', '--ubatch-size') and val:
                meta["ub"] = val
                i += 2
                continue
            elif arg in ('-fa', '--flash-attn') and val:
                meta["fa"] = val
                i += 2
                continue
            else:
                passthrough_args.append(arg)
                if val and i + 1 < len(argv) and argv[i+1] == val:
                    passthrough_args.append(val)
                    i += 2
                    continue
                i += 1
    server_bin = "llama-server.exe"
    # Auto-detect if Bonsai / Prism model requires prism fork binary
    if "bonsai" in meta["model_file"].lower() or any("dspark" in str(x).lower() for x in passthrough_args):
        prism_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prism", "llama-server.exe")
        if os.path.exists(prism_bin):
            server_bin = prism_bin

    cmd = [
        server_bin,
        "-m", meta["model_file"],
        "-ngl", str(meta["ngl"]),
        "-c", str(meta["context_limit"]),
        "-ctk", meta["ctk"],
        "-ctv", meta["ctv"],
        "-fa", meta["fa"],
        "-b", str(meta["b"]),
        "-ub", str(meta["ub"]),
        "-t", str(meta["t"]),
        "-tb", str(meta["tb"]),
        "-np", str(meta["np"]),
        "--jinja",
        "--cache-prompt",
        "--host", "127.0.0.1",
        "--port", str(meta["port"])
    ]
    cmd.extend(passthrough_args)
    return meta, cmd

# Parse CLI
CLI_META, SERVER_CMD = parse_cli_args(sys.argv[1:])

MODEL_FILE = CLI_META["model_file"]
CONTEXT_LIMIT = CLI_META["context_limit"]
PORT = CLI_META["port"]

# Clean model name for display
MODEL_DRAFT_FILE = CLI_META.get("draft_file")
clean_name = os.path.splitext(os.path.basename(MODEL_FILE))[0]
MODEL_NAME = clean_name.replace('-', ' ').replace('_', ' ').title()

def sync_active_model_to_omp(model_file, active_ctx):
    """
    Automatically sets the project's and global default model role in Oh My Pi
    to the currently running local model with the exact running context window.
    Also cleans SQLite model_cache so OMP immediately re-reads models.yml without stale cache.
    """
    model_id = os.path.basename(model_file)
    config_paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".omp", "config.yml")),
        r"G:\Мой диск\LLM\.omp\config.yml",
        r"G:\My Drive\LLM\.omp\config.yml"
    ]
    yaml_content = f"modelRoles:\n  default: llama.cpp/{model_id}\nimages:\n  urls:\n    enabled: false\n"
    for cp in config_paths:
        try:
            if os.path.exists(os.path.dirname(cp)):
                with open(cp, "w", encoding="utf-8") as f:
                    f.write(yaml_content)
        except Exception:
            pass

    # Build dynamic model list where the active model gets the exact launched contextWindow
    all_models = [
        ("Ternary-Bonsai-27B-Q2_0.gguf", "Bonsai 27B (Ternary Q2_0)", 65536),
        ("Bonsai-27B-Q1_0.gguf", "Bonsai 27B (Ternary Q1_0)", 65536),
        ("gpt-oss-20b-UD-Q6_K_XL.gguf", "GPT-OSS 20B (UD Q6_K_XL)", 32768),
        ("qwen2.5-coder-7b-instruct-q4_k_m.gguf", "Qwen 2.5 Coder 7B (Local Q4_K_M)", 65536),
        ("qwen3-4b-thinking-2507.Q8_0.gguf", "Qwen 3 4B Thinking (Q8_0)", 65536),
        ("qwen3.5-4B-super-coder.Q4_0.gguf", "Qwen 3.5 4B Super Coder (Q4_0)", 65536)
    ]

    lines = [
        "providers:",
        "  llama.cpp:",
        "    baseUrl: http://127.0.0.1:8080/v1",
        "    api: openai-completions",
        "    auth: none",
        "    models:"
    ]
    for mid, mname, def_ctx in all_models:
        ctx = active_ctx if mid == model_id else def_ctx
        max_tok = min(8192, ctx)
        lines.append(f"      - id: {mid}")
        lines.append(f"        name: {mname}")
        lines.append(f"        contextWindow: {ctx}")
        lines.append(f"        maxTokens: {max_tok}")

    models_content = "\n".join(lines) + "\n"

    models_yaml_paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".omp", "models.yml")),
        os.path.expanduser("~/.omp/agent/models.yml"),
        r"G:\Мой диск\LLM\.omp\models.yml",
        r"G:\Мой диск\LLM\models.yml",
        r"G:\My Drive\LLM\.omp\models.yml",
        r"G:\My Drive\LLM\models.yml"
    ]
    for mp in models_yaml_paths:
        try:
            if os.path.exists(os.path.dirname(mp)):
                with open(mp, "w", encoding="utf-8") as f:
                    f.write(models_content)
        except Exception:
            pass

    try:
        import sqlite3
        db_path = os.path.expanduser("~/.omp/agent/models.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.execute("DELETE FROM model_cache WHERE provider_id LIKE '%llama%';")
            conn.commit()
            conn.close()
    except Exception:
        pass

# Sync OMP config immediately on launch with exact active context
sync_active_model_to_omp(MODEL_FILE, CONTEXT_LIMIT)
# Estimate base model weights + draft weights size in GB from files
try:
    base_sz = os.path.getsize(MODEL_FILE) if os.path.exists(MODEL_FILE) else 4.68 * (1024.0**3)
    draft_sz = os.path.getsize(MODEL_DRAFT_FILE) if (MODEL_DRAFT_FILE and os.path.exists(MODEL_DRAFT_FILE)) else 0.0
    BASE_MODEL_VRAM_GB = (base_sz + draft_sz) / (1024.0 ** 3)
except Exception:
    BASE_MODEL_VRAM_GB = 6.67

MAX_KV_CACHE_VRAM_GB = (CONTEXT_LIMIT / 65536.0) * 1.93
offload_ram_gb = 0.0
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BLUE = "\033[94m"
C_GRAY = "\033[90m"
C_MAGENTA = "\033[95m"
# Human-readable event history (max 8 entries)
events_deque = deque(maxlen=8)
server_proc = None
running = True

# Real-time metrics
last_prompt_speed = 0.0
last_gen_speed = 0.0
real_total_vram_gb = TOTAL_VRAM_GB * 0.95
cpu_offload_detected = False
cpu_layers_count = 0
def format_llama_log_to_human_event(raw_line):
    """
    Parses noisy raw llama-server internal debug lines into clean, informative activity cards.
    """
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    
    if "HTTP server listening on" in raw_line:
        m = re.search(r'http://[^\s]+', raw_line)
        url = m.group(0) if m else f"http://127.0.0.1:{PORT}"
        return f"{C_GREEN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_GREEN}Server Ready:{C_RESET} Listening on {C_CYAN}{url}{C_RESET}"
    
    if "prompt processing" in raw_line:
        m_tok = re.search(r'n_tokens\s*=\s*(\d+)', raw_line)
        m_spd = re.search(r'(\d+(?:\.\d+)?)\s*tokens per second', raw_line)
        tok = f"{int(m_tok.group(1)):,}" if m_tok else "—"
        spd = m_spd.group(1) if m_spd else "—"
        return f"{C_CYAN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_CYAN}Prompt Processing:{C_RESET} {tok} tokens @ {C_CYAN}{spd} tok/s{C_RESET}"
        
    if "prompt eval time =" in raw_line:
        m_tok = re.search(r'/\s*(\d+)\s*tokens', raw_line)
        m_spd = re.search(r'(\d+(?:\.\d+)?)\s*tokens per second', raw_line)
        tok = f"{int(m_tok.group(1)):,}" if m_tok else "—"
        spd = m_spd.group(1) if m_spd else "—"
        return f"{C_CYAN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_CYAN}Prompt Evaluated:{C_RESET} {tok} tokens @ {C_CYAN}{spd} tok/s{C_RESET}"

    if "eval time =" in raw_line and "prompt" not in raw_line:
        m_tok = re.search(r'/\s*(\d+)\s*tokens', raw_line)
        m_spd = re.search(r'(\d+(?:\.\d+)?)\s*tokens per second', raw_line)
        m_ms = re.search(r'eval time\s*=\s*([\d\.]+)\s*ms', raw_line)
        tok = f"{int(m_tok.group(1)):,}" if m_tok else "—"
        spd = m_spd.group(1) if m_spd else "—"
        sec = f"{float(m_ms.group(1))/1000.0:.1f}s" if m_ms else "—"
        return f"{C_GREEN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_GREEN}Generated Output:{C_RESET} {tok} tokens @ {C_GREEN}{spd} tok/s{C_RESET} in {C_YELLOW}{sec}{C_RESET}"

    if "launch_slot_" in raw_line or "processing task" in raw_line:
        m_task = re.search(r'task\s+(\d+)', raw_line)
        task_id = m_task.group(1) if m_task else "?"
        return f"{C_YELLOW}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_YELLOW}Task #{task_id} Started:{C_RESET} Slot 0 processing request..."

    if "stop processing" in raw_line or "release:" in raw_line:
        m_task = re.search(r'task\s+(\d+)', raw_line)
        task_id = m_task.group(1) if m_task else "?"
        return f"{C_GRAY}● [{now_str}] Task #{task_id} Completed: Slot returned to idle{C_RESET}"

    if "error" in raw_line.lower() and not "unavailable_error" in raw_line:
        clean = raw_line.replace("\r", "")
        return f"{C_RED}✖ [{now_str}] Notice: {clean[:65]}{C_RESET}"

    return None

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
    """Accurately calculate visible terminal column width ignoring ANSI codes and accounting for wide emojis."""
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    width = 0
    for ch in clean:
        w = unicodedata.east_asian_width(ch)
        if w in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width

def truncate_to_visual_width(text, max_width):
    """Truncates styled text so that its visual character width does not exceed max_width."""
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    if get_visual_width(text) <= max_width:
        return text
    # Hard strip styling for overly long lines to guarantee crisp frame alignment
    truncated_clean = clean[:max_width]
    return truncated_clean

def render_row(content, inner_width):
    """Render a table row with exact right border alignment and overflow protection."""
    v_width = get_visual_width(content)
    if v_width > inner_width:
        content = truncate_to_visual_width(content, inner_width)
        v_width = get_visual_width(content)
    pad = max(0, inner_width - v_width)
    return f"{C_CYAN}│{C_RESET} {content}{' ' * pad} {C_CYAN}│{C_RESET}"
def log_reader(proc):
    global running, last_prompt_speed, last_gen_speed, cpu_offload_detected, cpu_layers_count
    for line in iter(proc.stdout.readline, b''):
        if not running:
            break
        raw_text = line.decode('utf-8', errors='replace').strip()
        if not raw_text:
            continue

        # Detect CPU offloaded layers
        if "offloaded" in raw_text and ("layers to CPU" in raw_text or "layers to GPU" in raw_text):
            m_cpu = re.search(r'(\d+)\s*layers to CPU', raw_text)
            if m_cpu and int(m_cpu.group(1)) > 0:
                cpu_offload_detected = True
                cpu_layers_count = int(m_cpu.group(1))
        elif "layer 0 is assigned to device CPU" in raw_text:
            cpu_offload_detected = True

        # Extract speed metrics
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

        event = format_llama_log_to_human_event(raw_text)
        if event:
            events_deque.append(event)
def gpu_vram_poller():
    global running, real_total_vram_gb, IS_NVIDIA, TOTAL_VRAM_GB
    while running:
        if IS_NVIDIA:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=0.8
                )
                if res.returncode == 0 and res.stdout.strip():
                    used_mb = float(res.stdout.strip().splitlines()[0])
                    real_total_vram_gb = max(1.0, min(TOTAL_VRAM_GB, used_mb / 1024.0))
            except Exception:
                pass
        else:
            try:
                cmd = "powershell.exe -NoProfile -Command \"(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum\""
                out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').strip()
                if out:
                    bytes_val = float(out)
                    real_total_vram_gb = max(1.0, min(TOTAL_VRAM_GB, bytes_val / (1024.0 ** 3)))
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
    global server_proc, running, last_prompt_speed, last_gen_speed, real_total_vram_gb, GPU_NAME, TOTAL_VRAM_GB, GPU_VENDOR
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print(f"{C_BOLD}{C_CYAN}Launching {MODEL_NAME} on {GPU_NAME} ({TOTAL_VRAM_GB} GB VRAM)...{C_RESET}")
    try:
        server_proc = subprocess.Popen(
            SERVER_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )
    except Exception as e:
        print(f"{C_RED}Failed to start llama-server: {e}{C_RESET}")
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

    # Initial event
    events_deque.append(f"{C_CYAN}● [{datetime.datetime.now().strftime('%H:%M:%S')}] Server Process Started: PID {server_proc.pid}{C_RESET}")

    while running:
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'q', b'Q', b'\x1b', b'\x03'):
                print(f"\n{C_YELLOW}Exit requested via keypress...{C_RESET}")
                shutdown_server()
                break

        if not running:
            break

        if server_proc.poll() is not None:
            print(f"\n{C_RED}Server exited with code {server_proc.returncode}{C_RESET}")
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

        if cpu_offload_detected and cpu_layers_count > 0:
            ram_spillover_status = f"{C_YELLOW}{cpu_layers_count} layers in CPU RAM  [⚠️ PARTIAL OFFLOAD]{C_RESET}"
        else:
            ram_spillover_status = f"{C_GREEN}0.00 GB  [✅ 100% IN VRAM, NO OFFLOAD]{C_RESET}"

        ctx_percent = (used_ctx_tokens / CONTEXT_LIMIT) * 100.0

        status_badge = f"{C_GREEN}● READY (IDLE){C_RESET}" if not is_processing else f"{C_YELLOW}⚡ PROCESSING / GENERATING...{C_RESET}"
        if not ready:
            status_badge = f"{C_MAGENTA}⏳ LOADING TO VRAM...{C_RESET}"

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
        print(render_row(f"{C_BOLD}Server Status:{C_RESET}    {status_badge}     {C_BOLD}Uptime:{C_RESET} {uptime_str}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Model:{C_RESET}            {C_CYAN}{MODEL_NAME}{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}GPU Hardware:{C_RESET}     {C_GREEN}{GPU_NAME}{C_RESET} ({GPU_VENDOR}, {TOTAL_VRAM_GB} GB VRAM)", INNER_WIDTH))
        print(render_row(f"{C_BOLD}API Endpoint:{C_RESET}     {C_GREEN}http://127.0.0.1:{PORT}/v1{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Configuration:{C_RESET}    {CONTEXT_LIMIT:,} tokens  |  Cache: {CLI_META['ctk']}  |  Flash-Attn: {CLI_META['fa']}", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Memory Section (Stacked + Self RAM)
        print(render_row(f"{C_BOLD}📊 VRAM & SYSTEM RAM METRICS:{C_RESET}", INNER_WIDTH))
        print(render_row(f"  ├─ 🎮 {C_BOLD}GPU Memory (VRAM):{C_RESET}   {vram_bar}  {t_gb:.2f} / {TOTAL_VRAM_GB:.1f} GB ({total_vram_pct:.1f}%)", INNER_WIDTH))
        legend = f"     └─ {C_CYAN}■ Model:{C_RESET} {m_gb:.2f} GB  |  {C_YELLOW}■ Windows/System:{C_RESET} {o_gb:.2f} GB"
        print(render_row(legend, INNER_WIDTH))
        print(render_row(f"  ├─ 🧠 {C_BOLD}CPU RAM Spillover:{C_RESET}   {ram_spillover_status}", INNER_WIDTH))
        server_ram_label = "Vulkan host buffer" if not IS_NVIDIA else "CUDA runtime buffer"
        print(render_row(f"  ├─ ⚙️  {C_BOLD}Server RAM (llama):{C_RESET}  ~{server_ram_gb:.2f} GB ({server_ram_label})", INNER_WIDTH))
        print(render_row(f"  └─ 🐍 {C_BOLD}Dashboard RAM (Py):{C_RESET} {C_GREEN}{my_ram_mb:.1f} MB{C_RESET} (lightweight UI monitor)", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Context & Speed Section
        print(render_row(f"{C_BOLD}📈 CONTEXT ACTIVITY & THROUGHPUT:{C_RESET}", INNER_WIDTH))
        ctx_bar = make_bar(ctx_percent, length=18, color=C_GREEN if ctx_percent < 80 else C_YELLOW)
        print(render_row(f"  ├─ 🗂  {C_BOLD}Context Occupied:{C_RESET}    {ctx_bar}  {used_ctx_tokens:,} / {CONTEXT_LIMIT:,} ({ctx_percent:.1f}%)", INNER_WIDTH))
        
        gen_spd_display = f"{last_gen_speed:.1f} tok/s" if last_gen_speed > 0 else "—"
        prompt_spd_display = f"{last_prompt_speed:.1f} tok/s" if last_prompt_speed > 0 else "—"
        speed_text = f"Generation: {C_BOLD}{C_GREEN}{gen_spd_display}{C_RESET}  |  Prompt: {C_BOLD}{C_CYAN}{prompt_spd_display}{C_RESET}"
        print(render_row(f"  └─ ⚡ {C_BOLD}Response Speed:{C_RESET}      {speed_text}", INNER_WIDTH))
        print(f"{C_CYAN}├{'─' * (INNER_WIDTH + 2)}┤{C_RESET}")

        # Structured Activity History Section
        print(render_row(f"{C_BOLD}📋 RECENT TASKS & SERVER ACTIVITY:{C_RESET}", INNER_WIDTH))
        recent_events = list(events_deque)[-6:]
        for idx in range(6):
            if idx < len(recent_events):
                ev_str = recent_events[idx]
                print(render_row(f"  {ev_str}", INNER_WIDTH))
            else:
                print(render_row(f"  {C_GRAY}— Waiting for next task...{C_RESET}", INNER_WIDTH))

        # Bottom border
        print(f"{C_CYAN}└{'─' * (INNER_WIDTH + 2)}┘{C_RESET}")
        print(f" {C_GRAY}[Press 'Q', 'Esc' or 'Ctrl+C' to cleanly stop the server]{C_RESET}")

        for _ in range(10):
            if not running:
                break
            if msvcrt.kbhit():
                break
            time.sleep(0.1)

    print(f"\n{C_GREEN}Server stopped cleanly.{C_RESET}")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        shutdown_server()
        print(f"\n{C_GREEN}Server stopped cleanly.{C_RESET}")
