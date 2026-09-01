# -*- coding: utf-8 -*-
"""
Universal Llama Server Live Dashboard
High-Performance Interactive Terminal Dashboard for llama.cpp / llama-server
Compatible with NVIDIA (CUDA), AMD (Vulkan/ROCm), Intel (Arc/iGPU), Apple Silicon (Metal), and CPU.
"""

import subprocess
import threading
import time
import json
import urllib.request
import os
import sys
import re
import unicodedata
import datetime
import shutil
from collections import deque

# Enable ANSI escape sequences in Windows Terminal / CMD
os.system('')

# Cross-platform msvcrt / select for keyboard input
if sys.platform == "win32":
    import msvcrt
    import winreg
else:
    import select
    import tty
    import termios


def detect_gpu_hardware():
    """
    Universal GPU & VRAM Detector:
    Auto-detects NVIDIA (CUDA), AMD (Vulkan/ROCm), Intel (Arc/DirectX), Apple Silicon (Metal), and CPU.
    """
    gpu_name = "Generic GPU / CPU"
    total_vram_gb = 16.0
    vendor_type = "Vulkan"
    is_nvidia = False

    # 1. Try NVIDIA via nvidia-smi (Cross-platform)
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

    # 2. Windows Registry for exact 64-bit VRAM size (AMD Radeon & Intel & NVIDIA fallback)
    if sys.platform == "win32":
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
                                    vendor_type = "NVIDIA CUDA"
                                    is_nvidia = True
                                elif "AMD" in name_u or "RADEON" in name_u:
                                    vendor_type = "AMD Vulkan"
                                elif "INTEL" in name_u:
                                    vendor_type = "Intel Arc/DirectX"
                                return gpu_name, total_vram_gb, vendor_type, is_nvidia
                        except Exception:
                            pass
        except Exception:
            pass

        # 3. Windows CIM Fallback
        try:
            cmd = "powershell.exe -NoProfile -Command \"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $g = Get-CimInstance Win32_VideoController | Select-Object -First 1; Write-Output ($g.Name + '|' + $g.AdapterRAM)\""
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=2.0).decode('utf-8', errors='ignore').strip()
            if "|" in out:
                name, ram = out.split("|", 1)
                gpu_name = name.strip()
                name_u = gpu_name.upper()
                if "NVIDIA" in name_u:
                    vendor_type = "NVIDIA CUDA"
                    is_nvidia = True
                elif "AMD" in name_u or "RADEON" in name_u:
                    vendor_type = "AMD Vulkan"
                elif "INTEL" in name_u:
                    vendor_type = "Intel"
                if ram.strip() and ram.strip().isdigit():
                    ram_gb = round(int(ram.strip()) / (1024.0 ** 3), 1)
                    if ram_gb > 0:
                        total_vram_gb = ram_gb
                return gpu_name, total_vram_gb, vendor_type, is_nvidia
        except Exception:
            pass

    # 4. Linux sysfs / ROCm / Apple Silicon
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
            mem = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            gpu_name = f"Apple Silicon ({out})"
            total_vram_gb = round(int(mem) / (1024.0 ** 3), 1)
            vendor_type = "Apple Metal (Unified)"
            return gpu_name, total_vram_gb, vendor_type, False
        except Exception:
            pass

    elif sys.platform.startswith("linux"):
        # Check AMD sysfs
        try:
            vram_total_file = "/sys/class/drm/card0/device/mem_info_vram_total"
            if os.path.exists(vram_total_file):
                with open(vram_total_file, "r") as f:
                    bytes_val = int(f.read().strip())
                    total_vram_gb = round(bytes_val / (1024.0 ** 3), 1)
                    vendor_type = "AMD ROCm / Vulkan"
                    gpu_name = "AMD Radeon GPU"
                    return gpu_name, total_vram_gb, vendor_type, False
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
    3. Supports FULL native llama-server flags: python dashboard.py -m model.gguf -c 131072 -ngl 99 --temp 0.2 --jinja --no-mmap
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

    # Positional shorthand
    if argv and not argv[0].startswith('-'):
        meta["model_file"] = argv[0]
        if len(argv) > 1 and argv[1].isdigit():
            meta["context_limit"] = int(argv[1])
        if len(argv) > 2 and argv[2].isdigit():
            meta["port"] = int(argv[2])
        if len(argv) > 3:
            passthrough_args.extend(argv[3:])
    else:
        i = 0
        while i < len(argv):
            arg = argv[i]
            val = argv[i+1] if i + 1 < len(argv) and not argv[i+1].startswith('-') else None

            if arg in ('-m', '--model') and val:
                meta["model_file"] = val
                i += 2
                continue
            elif arg in ('-md', '--model-draft') and val:
                meta["draft_file"] = val
                passthrough_args.extend([arg, val])
                i += 2
                continue
            elif arg in ('-c', '--ctx-size') and val:
                meta["context_limit"] = int(val)
                i += 2
                continue
            elif arg in ('-p', '--port') and val:
                meta["port"] = int(val)
                i += 2
                continue
            elif arg in ('-ngl', '--n-gpu-layers') and val:
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

    # Universal Binary Locator (Cross-platform & multi-environment)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # 1. Prism custom builds (Vulkan / MTP / Bonsai)
        os.path.join(script_dir, "prism", "llama-server.exe"),
        os.path.join(script_dir, "prism", "llama-server"),
        # 2. Local directory
        os.path.join(script_dir, "llama-server.exe"),
        os.path.join(script_dir, "llama-server"),
        # 3. System PATH
        shutil.which("llama-server.exe"),
        shutil.which("llama-server"),
    ]
    server_bin = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for c in candidates:
        if c and os.path.exists(c):
            server_bin = c
            break

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

    # Build dynamic model list
    PRESETS = [
        ("Qwen3.8-27B-UD-Q3_K_XL.gguf", "Qwen 3.8 27B (UD Q3_K_XL)", 65536),
        ("Qwen3.8-27B-UD-Q2_K_XL.gguf", "Qwen 3.8 27B (UD Q2_K_XL)", 65536),
        ("gpt-oss-20b-UD-Q6_K_XL.gguf", "GPT-OSS 20B (UD Q6_K_XL)", 65536),
        ("gemma-4-31B-it-UD-IQ2_XXS.gguf", "Gemma 4 31B IT (UD-IQ2_XXS - 128k)", 131072),
        ("DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf", "DeepSeek Coder V2 Lite (Q4_K_M MoE)", 65536),
        ("qwen2.5-coder-14b-instruct-q4_k_m.gguf", "Qwen 2.5 Coder 14B (Q4_K_M)", 65536),
        ("qwen2.5-coder-7b-instruct-q4_k_m.gguf", "Qwen 2.5 Coder 7B (Q4_K_M)", 65536),
        ("Qwen2.5-7B-Instruct-Q4_K_M.gguf", "Qwen 2.5 7B Instruct (Q4_K_M)", 65536),
    ]

    models_yml_lines = ["providers:", "  llama.cpp:", "    name: llama.cpp", f"    baseUrl: http://127.0.0.1:{PORT}/v1", "    models:"]
    found_active = False

    for fname, dname, def_ctx in PRESETS:
        ctx = active_ctx if fname.lower() == model_id.lower() else def_ctx
        if fname.lower() == model_id.lower():
            found_active = True
        models_yml_lines.extend([
            f"      - id: {fname}",
            f"        name: {dname}",
            "        reasoning: true",
            "        inputPrice: 0",
            "        outputPrice: 0",
            f"        contextWindow: {ctx}",
            "        maxTokens: 8192"
        ])

    if not found_active:
        models_yml_lines.extend([
            f"      - id: {model_id}",
            f"        name: {MODEL_NAME}",
            "        reasoning: true",
            "        inputPrice: 0",
            "        outputPrice: 0",
            f"        contextWindow: {active_ctx}",
            "        maxTokens: 8192"
        ])

    models_yaml_content = "\n".join(models_yml_lines) + "\n"
    models_paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".omp", "models.yml")),
        r"G:\Мой диск\LLM\.omp\models.yml",
        r"G:\My Drive\LLM\.omp\models.yml"
    ]
    for mp in models_paths:
        try:
            if os.path.exists(os.path.dirname(mp)):
                with open(mp, "w", encoding="utf-8") as f:
                    f.write(models_yaml_content)
        except Exception:
            pass

    # Flush local OMP SQLite cache
    try:
        import sqlite3
        user_home = os.path.expanduser("~")
        db_paths = [
            os.path.join(user_home, ".omp", "agent", "models.db"),
            r"G:\Мой диск\LLM\.omp\models.db",
            r"G:\My Drive\LLM\.omp\models.db"
        ]
        for db_path in db_paths:
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
    BASE_MODEL_VRAM_GB = 4.80

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
real_total_vram_gb = BASE_MODEL_VRAM_GB + 2.0
real_llama_vram_gb = 0.0
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
        spd = f"{float(m_spd.group(1)):.1f}" if m_spd else "—"
        return f"{C_CYAN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_CYAN}Prompt Processing:{C_RESET} {tok} tokens @ {C_CYAN}{spd} tok/s{C_RESET}"

    if "generation" in raw_line and "tokens per second" in raw_line:
        m_tok = re.search(r'n_tokens\s*=\s*(\d+)', raw_line)
        m_spd = re.search(r'(\d+(?:\.\d+)?)\s*tokens per second', raw_line)
        tok = f"{int(m_tok.group(1)):,}" if m_tok else "—"
        spd = f"{float(m_spd.group(1)):.1f}" if m_spd else "—"
        return f"{C_GREEN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_GREEN}Token Generation:{C_RESET} {tok} tokens @ {C_GREEN}{spd} tok/s{C_RESET}"

    if "loading model" in raw_line or "load_all_data" in raw_line:
        return f"{C_MAGENTA}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_MAGENTA}Loading Model Weights into VRAM...{C_RESET}"

    if "all tensors loaded" in raw_line or "model loaded" in raw_line or "llama_model_loader: loaded" in raw_line:
        return f"{C_GREEN}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_GREEN}VRAM Staging Complete:{C_RESET} Tensors Mapped Successfully"

    if "slot update_slots: id" in raw_line and "task" in raw_line:
        m_task = re.search(r'task\s+(\d+)', raw_line)
        task_id = m_task.group(1) if m_task else "active"
        return f"{C_YELLOW}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_YELLOW}Active Inference Request:{C_RESET} Task #{task_id}"

    if "slot release_slot" in raw_line:
        return f"{C_BLUE}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_BLUE}Context Released:{C_RESET} Slot Ready for Next Query"

    if "error" in raw_line.lower() and not "0 error" in raw_line.lower():
        clean_err = raw_line.strip()[:65]
        return f"{C_RED}●{C_RESET} {C_GRAY}[{now_str}]{C_RESET} {C_BOLD}{C_RED}Warning/Notice:{C_RESET} {clean_err}"

    return None


def get_display_width(text):
    clean = re.sub(r'\033\[[0-9;]*m', '', text)
    width = 0
    for ch in clean:
        w = unicodedata.east_asian_width(ch)
        width += 2 if w in ('F', 'W') else 1
    return width


def render_row(content, inner_width=84):
    content_width = get_display_width(content)
    pad = max(0, inner_width - content_width)
    return f"│ {content}{' ' * pad} │"


def log_reader(proc):
    global running, last_prompt_speed, last_gen_speed, cpu_offload_detected, cpu_layers_count
    for line in iter(proc.stdout.readline, b''):
        if not running:
            break
        try:
            raw_text = line.decode('utf-8', errors='ignore')
        except Exception:
            continue

        if "offloaded" in raw_text and "layers to CPU" in raw_text:
            m = re.search(r'offloaded\s+(\d+)\s+layers to CPU', raw_text)
            if m:
                cpu_layers_count = int(m.group(1))
                if cpu_layers_count > 0:
                    cpu_offload_detected = True

        if "prompt processing" in raw_text or "prompt eval" in raw_text:
            m = re.search(r'pp(?:_3s)?\s*=\s*(\d+(?:\.\d+)?)', raw_text)
            if not m:
                m = re.search(r'(\d+(?:\.\d+)?)\s*tokens per second', raw_text)
            if m:
                try:
                    last_prompt_speed = float(m.group(1))
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
    global running, real_total_vram_gb, real_llama_vram_gb, IS_NVIDIA, TOTAL_VRAM_GB, server_proc
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
        elif sys.platform == "win32":
            try:
                ps = "$tot = (Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum; if ($tot) { Write-Output $tot }"
                out = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", ps], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').strip()
                if out:
                    val_bytes = float(out)
                    if val_bytes > 0:
                        real_total_vram_gb = max(1.0, min(TOTAL_VRAM_GB, val_bytes / (1024.0 ** 3)))
            except Exception:
                pass
        elif sys.platform.startswith("linux"):
            try:
                vram_used_file = "/sys/class/drm/card0/device/mem_info_vram_used"
                if os.path.exists(vram_used_file):
                    with open(vram_used_file, "r") as f:
                        bytes_val = int(f.read().strip())
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
        if sys.platform == "win32":
            cmd = f"powershell.exe -NoProfile -Command \"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).WorkingSet64 / 1MB\""
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=0.6).decode().strip()
            if out:
                return float(out.replace(',', '.'))
        else:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 35.0


def shutdown_server():
    global running, server_proc
    running = False
    if server_proc:
        try:
            if sys.platform == "win32":
                subprocess.run(f"taskkill /F /T /PID {server_proc.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                server_proc.terminate()
        except Exception:
            pass


def main():
    global server_proc, running, last_prompt_speed, last_gen_speed, real_total_vram_gb, GPU_NAME, TOTAL_VRAM_GB, GPU_VENDOR

    print(f"{C_BOLD}{C_CYAN}Launching {MODEL_NAME} on {GPU_NAME} ({TOTAL_VRAM_GB} GB VRAM)...{C_RESET}")
    try:
        server_proc = subprocess.Popen(
            SERVER_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0
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
        if sys.platform == "win32":
            while msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'q', b'Q', b'\x1b', b'\x03'):
                    print(f"\n{C_YELLOW}Exit requested via keypress...{C_RESET}")
                    shutdown_server()
                    break
        else:
            dr, _, _ = select.select([sys.stdin], [], [], 0)
            if dr:
                ch = sys.stdin.read(1)
                if ch in ('q', 'Q', '\x1b', '\x03'):
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
                    if is_processing:
                        n_prompt = s0.get('n_prompt_tokens', 0)
                        n_processed = s0.get('n_prompt_tokens_processed', 0)
                        used_ctx_tokens = max(n_prompt, n_processed)
                    else:
                        n_prompt = s0.get('n_prompt_tokens', 0)
                        used_ctx_tokens = n_prompt
        except Exception:
            ready = False

        server_ram_mb = get_process_ram_mb(server_proc.pid) if server_proc else 150.0
        server_ram_gb = server_ram_mb / 1024.0
        dash_ram_mb = get_process_ram_mb(my_pid)

        # Exact Llama VRAM vs Windows VRAM
        current_kv_gb = (used_ctx_tokens / CONTEXT_LIMIT) * MAX_KV_CACHE_VRAM_GB if used_ctx_tokens > 0 else 0.1
        calc_llama_gb = BASE_MODEL_VRAM_GB + current_kv_gb + VULKAN_OVERHEAD_GB
        m_gb = real_llama_vram_gb if real_llama_vram_gb > 2.0 else calc_llama_gb
        t_gb = max(real_total_vram_gb, m_gb)
        vram_bar, m_gb, o_gb, t_gb = make_stacked_vram_bar(m_gb, t_gb, TOTAL_VRAM_GB, length=18)
        total_vram_pct = (t_gb / TOTAL_VRAM_GB) * 100.0

        ctx_pct = (used_ctx_tokens / CONTEXT_LIMIT) * 100.0
        ctx_bar = make_bar(ctx_pct, length=18, color=C_CYAN)

        if cpu_offload_detected:
            ram_spillover_status = f"{C_RED}{server_ram_gb:.2f} GB  [⚠️ {cpu_layers_count} LAYERS OFFLOADED TO RAM]{C_RESET}"
        else:
            ram_spillover_status = f"{C_GREEN}0.00 GB  [✅ 100% IN VRAM, NO OFFLOAD]{C_RESET}"

        uptime_sec = int(time.time() - start_time)
        m, s = divmod(uptime_sec, 60)
        h, m = divmod(m, 60)
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        if not ready:
            status_badge = f"{C_MAGENTA}⏳ LOADING TO VRAM...{C_RESET}"
        elif is_processing:
            status_badge = f"{C_YELLOW}⚡ INFERENCE ACTIVE{C_RESET}"
        else:
            status_badge = f"{C_GREEN}● READY (IDLE){C_RESET}"

        spd_gen_str = f"{last_gen_speed:.1f} tok/s" if last_gen_speed > 0 else "—"
        spd_pp_str = f"{last_prompt_speed:.1f} tok/s" if last_prompt_speed > 0 else "—"

        title = f" ⚡ {MODEL_NAME.upper()[:36]} (LLAMA-SERVER DASHBOARD) ⚡ "
        title_width = get_display_width(title)
        border_top = f"┌{'─' * ((INNER_WIDTH - title_width)//2)}{title}{'─' * (INNER_WIDTH - title_width - (INNER_WIDTH - title_width)//2)}┐"
        border_div = f"├{'─' * INNER_WIDTH}┤"
        border_bot = f"└{'─' * INNER_WIDTH}┘"

        # ANSI clear screen & home cursor
        sys.stdout.write("\033[2J\033[H")

        print(border_top)
        print(render_row(f"{C_BOLD}Server Status:{C_RESET}    {status_badge}     {C_BOLD}Uptime:{C_RESET} {uptime_str}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Model:{C_RESET}            {C_CYAN}{MODEL_NAME}{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}GPU Hardware:{C_RESET}     {C_GREEN}{GPU_NAME}{C_RESET} ({GPU_VENDOR}, {TOTAL_VRAM_GB} GB VRAM)", INNER_WIDTH))
        print(render_row(f"{C_BOLD}API Endpoint:{C_RESET}     {C_CYAN}http://127.0.0.1:{PORT}/v1{C_RESET}", INNER_WIDTH))
        print(render_row(f"{C_BOLD}Configuration:{C_RESET}    {CONTEXT_LIMIT:,} tokens  |  Cache: {CLI_META['ctk']}  |  Flash-Attn: {CLI_META['fa']}", INNER_WIDTH))
        print(border_div)
        print(render_row(f"{C_BOLD}📊 VRAM & SYSTEM RAM METRICS:{C_RESET}", INNER_WIDTH))
        print(render_row(f"  ├─ 🎮 {C_BOLD}GPU Memory (VRAM):{C_RESET}   {vram_bar}  {t_gb:.2f} / {TOTAL_VRAM_GB:.1f} GB ({total_vram_pct:.1f}%)", INNER_WIDTH))
        legend = f"     └─ {C_CYAN}■ LLM (Model+KV):{C_RESET} {m_gb:.2f} GB  |  {C_YELLOW}■ Windows/DWM/Apps:{C_RESET} {o_gb:.2f} GB"
        print(render_row(legend, INNER_WIDTH))
        print(render_row(f"  ├─ 🧠 {C_BOLD}CPU RAM Spillover:{C_RESET}   {ram_spillover_status}", INNER_WIDTH))
        print(render_row(f"  ├─ ⚙️  {C_BOLD}Server RAM (llama):{C_RESET}  ~{server_ram_gb:.2f} GB (Vulkan host buffer)", INNER_WIDTH))
        print(render_row(f"  └─ 🐍 {C_BOLD}Dashboard RAM (Py):{C_RESET} {dash_ram_mb:.1f} MB (lightweight UI monitor)", INNER_WIDTH))
        print(border_div)
        print(render_row(f"{C_BOLD}📈 CONTEXT ACTIVITY & THROUGHPUT:{C_RESET}", INNER_WIDTH))
        print(render_row(f"  ├─ 🗂  {C_BOLD}Context Occupied:{C_RESET}    {ctx_bar}  {used_ctx_tokens:,} / {CONTEXT_LIMIT:,} ({ctx_pct:.1f}%)", INNER_WIDTH))
        print(render_row(f"  └─ ⚡ {C_BOLD}Response Speed:{C_RESET}      Generation: {C_GREEN}{spd_gen_str}{C_RESET}  |  Prompt: {C_CYAN}{spd_pp_str}{C_RESET}", INNER_WIDTH))
        print(border_div)
        print(render_row(f"{C_BOLD}📋 RECENT TASKS & SERVER ACTIVITY:{C_RESET}", INNER_WIDTH))

        events_list = list(events_deque)
        while len(events_list) < 5:
            events_list.append(f"{C_GRAY}— Waiting for next task...{C_RESET}")

        for ev in events_list[-5:]:
            print(render_row(f"  {ev}", INNER_WIDTH))

        print(border_bot)
        print(f" {C_GRAY}[Press 'Q', 'Esc' or 'Ctrl+C' to cleanly stop the server]{C_RESET}")

        for _ in range(8):
            if not running:
                break
            time.sleep(0.1)

    print(f"\n{C_GREEN}Server stopped cleanly.{C_RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown_server()
        print(f"\n{C_GREEN}Dashboard closed.{C_RESET}")
