# -*- coding: utf-8 -*-
"""
修复 dsh(DeepSeek Harness) 与 WorkBuddy 的图片输入能力声明。

问题本质：
  Codex++ 网关接管 dsh 配置时，每次启动都会重写
  %USERPROFILE%\\.dsh\\cordis.patch.yml 里带托管标记的那一段，
  把手工加的 defaultInput / models[].input 抹掉；
  WorkBuddy 的 %USERPROFILE%\\.workbuddy\\models.json 里
  qwen3.5-397b 的 supportsImages 被写死为 false。

本脚本做两件事，均幂等（重复运行无副作用）：
  1. cordis.patch.yml —— 给 codexplus / haiwen 两条路由补上
     defaultInput: [text, image] 与 models[].input: [text, image]
  2. models.json —— 把 qwen3.5-397b 的 supportsImages 置为 true

每次修改前自动备份为 <文件名>.bak.YYYYmmddHHMMSS。
纯标准库实现，不依赖 pyyaml，便于打包成单文件 EXE。
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
DSH_PATCH = HOME / ".dsh" / "cordis.patch.yml"
WB_MODELS = HOME / ".workbuddy" / "models.json"

TARGET_PROVIDERS = ("codexplus", "haiwen")
IMAGE_DECL = "[text, image]"


def stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def backup(path: Path) -> Path:
    dest = path.with_name(f"{path.name}.bak.{stamp()}")
    shutil.copy2(path, dest)
    return dest


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


# --------------------------------------------------------------------------
# cordis.patch.yml —— 基于行的结构化修复
# --------------------------------------------------------------------------


def fix_dsh_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """
    返回 (新行列表, 变更说明)。逐行扫描，用缩进栈判断上下文归属。
    YAML 结构：
        - id: llm-pi-ai
          config:
            providers:
              codexplus:          <- provider 键
                models:           <- models 列表
                  - id: xxx       <- 模型条目
                    name: xxx
                    input: [...]  <- 要补的行
    """
    out: list[str] = []
    changes: list[str] = []

    # 当前上下文状态
    cur_provider = None          # 正在处理的 provider 名
    provider_indent = -1         # provider 键的缩进
    models_indent = -1           # models: 键的缩进
    item_indent = -1             # "- id:" 行的缩进
    item_start = -1              # 当前条目在 out 中的起始索引
    item_has_input = False
    item_id = ""
    provider_has_default = False
    default_indent = -1
    provider_start = -1          # provider 块在 out 中的起始索引

    def close_item():
        """当前模型条目结束时，若缺 input 则补一行。"""
        nonlocal item_has_input, item_start
        if item_start < 0 or item_has_input or not item_id:
            return
        cont = " " * (item_indent + 2)
        out.append(f"{cont}input: {IMAGE_DECL}")
        changes.append(f"  + {cur_provider}.models[{item_id}].input: {IMAGE_DECL}")
        item_start = -1

    def close_provider():
        """provider 块结束时，若缺 defaultInput 则补一行（插在 models 之前）。"""
        nonlocal provider_has_default
        if provider_start < 0 or not cur_provider:
            return
        if not provider_has_default:
            ins = " " * (provider_indent + 2)
            # 找到 models: 行的位置，插到它前面
            pos = len(out)
            for i in range(provider_start, len(out)):
                if out[i].strip() == "models:":
                    pos = i
                    break
            out.insert(pos, f"{ins}defaultInput: {IMAGE_DECL}")
            changes.append(f"  + {cur_provider}.defaultInput: {IMAGE_DECL}")
        elif default_indent >= 0:
            # 已存在但不含 image → 修正
            for i in range(provider_start, len(out)):
                s = out[i].strip()
                if s.startswith("defaultInput:"):
                    if "image" not in s:
                        ins = " " * indent_of(out[i])
                        out[i] = f"{ins}defaultInput: {IMAGE_DECL}"
                        changes.append(
                            f"  ~ {cur_provider}.defaultInput 修正为 {IMAGE_DECL}"
                        )
                    break

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        ind = indent_of(line)

        # 空行 / 纯注释：原样保留
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue

        # 退出 provider 块
        if cur_provider and ind <= provider_indent:
            close_item()
            close_provider()
            cur_provider = None
            provider_indent = -1
            provider_start = -1
            models_indent = -1
            item_indent = -1
            provider_has_default = False
            default_indent = -1

        # 退出模型条目（缩进回到条目层或更浅）
        if item_indent >= 0 and ind <= item_indent and not stripped.startswith("- "):
            close_item()
            item_indent = -1

        # ---- 识别 provider 键 ----
        if stripped.endswith(":") and stripped[:-1] in TARGET_PROVIDERS:
            cur_provider = stripped[:-1]
            provider_indent = ind
            out.append(line)
            provider_start = len(out) - 1
            provider_has_default = False
            default_indent = -1
            models_indent = -1
            item_indent = -1
            item_start = -1
            item_has_input = False
            item_id = ""
            continue

        if not cur_provider:
            out.append(line)
            continue

        # ---- provider 块内部 ----
        if stripped == "models:":
            models_indent = ind
            out.append(line)
            continue

        if stripped.startswith("- id:") and models_indent >= 0 and ind > models_indent:
            close_item()
            item_indent = ind
            item_id = stripped.split("id:", 1)[1].strip().strip('"').strip("'")
            item_has_input = False
            out.append(line)
            item_start = len(out) - 1
            continue

        if stripped.startswith("defaultInput:"):
            provider_has_default = True
            default_indent = ind
            out.append(line)
            continue

        if stripped.startswith("input:") and item_start >= 0 and ind > item_indent:
            item_has_input = True
            if "image" not in stripped:
                ins = " " * ind
                out.append(f"{ins}input: {IMAGE_DECL}")
                changes.append(f"  ~ {cur_provider}.models[{item_id}].input 修正")
            else:
                out.append(line)
            continue

        out.append(line)

    # 收尾
    close_item()
    close_provider()
    return out, changes


def fix_dsh_patch(path: Path, dry: bool = False) -> list[str]:
    log: list[str] = []
    if not path.exists():
        return [f"[跳过] 未找到 {path}"]

    raw = path.read_bytes().decode("utf-8", errors="surrogateescape")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")

    new_lines, changes = fix_dsh_lines(lines)
    new_text = "\n".join(new_lines)

    if new_text == text:
        log.append(f"[无需改动] {path.name} 已是正确配置")
        return log

    if dry:
        log.append(f"[预演] {path.name}：")
        log.extend(changes or ["  (格式规范化)"])
        return log

    bak = backup(path)
    path.write_bytes(new_text.replace("\n", nl).encode("utf-8", errors="surrogateescape"))
    log.append(f"[已修复] {path}")
    log.append(f"         备份 → {bak.name}")
    log.extend(changes or ["  (已规范化)"])
    return log


# --------------------------------------------------------------------------
# models.json
# --------------------------------------------------------------------------


def fix_wb_models(path: Path, target_ids=("qwen3.5-397b",), dry: bool = False) -> list[str]:
    log: list[str] = []
    if not path.exists():
        return [f"[跳过] 未找到 {path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"[失败] {path.name} 不是合法 JSON：{exc}"]

    models = data if isinstance(data, list) else data.get("models", [])
    if not isinstance(models, list):
        return [f"[跳过] {path.name} 结构无法识别"]

    changes: list[str] = []
    touched = False
    for item in models:
        if not isinstance(item, dict) or item.get("id") not in target_ids:
            continue
        if item.get("supportsImages") is True:
            changes.append(f"  = {item['id']}.supportsImages 已是 true")
            continue
        item["supportsImages"] = True
        changes.append(f"  + {item['id']}.supportsImages: false → true")
        touched = True

    if not touched:
        log.append(f"[无需改动] {path.name}")
        log.extend(changes)
        return log

    if dry:
        log.append(f"[预演] {path.name}：")
        log.extend(changes)
        return log

    bak = backup(path)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    log.append(f"[已修复] {path}")
    log.append(f"         备份 → {bak.name}")
    log.extend(changes)
    return log


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def force_utf8_console() -> None:
    """让 Windows 控制台正确显示中文：切到 UTF-8 代码页并重绑 stdout。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    force_utf8_console()
    dry = "--dry-run" in sys.argv

    print("=" * 58)
    print("  图片输入修复工具  ·  dsh + WorkBuddy")
    print("=" * 58)

    print("\n[1/2] DeepSeek Harness —— cordis.patch.yml")
    log1 = fix_dsh_patch(DSH_PATCH, dry=dry)
    for line in log1:
        print("      " + line)

    print("\n[2/2] WorkBuddy —— models.json")
    log2 = fix_wb_models(WB_MODELS, dry=dry)
    for line in log2:
        print("      " + line)

    print("\n" + "-" * 58)
    changed = any(l.startswith("[已修复]") for l in log1 + log2)
    if dry:
        print("  预演完成，未写入任何文件。")
    elif changed:
        print("  完成。请重启 DSH Desktop / WorkBuddy 后生效。")
        print("\n  提示：Codex++ 网关每次启动都会重写 cordis.patch.yml")
        print("        的托管段，重启后若又失效，再运行本工具即可。")
    else:
        print("  当前配置已经正确，无需操作。")
    print()

    try:
        input("按回车键退出…")
    except (EOFError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
