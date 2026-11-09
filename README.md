# DSH / WorkBuddy 图片输入修复

一个双击即用的修复工具，解决 **DeepSeek Harness (dsh)** 和 **WorkBuddy** 提示「当前模型不支持图片」的问题。

## 问题

两套客户端对自定义模型（如 `qwen3.5-397b`）的**图片能力声明默认是关闭的**，导致附图片时直接被拒：

```
cannot read "xxx.png" as an image: model "qwen3.5-397b" does not declare image input
switch to an image-capable model to read images
```

| 客户端 | 声明位置 | 字段 |
|---|---|---|
| DeepSeek Harness | `~/.dsh/cordis.patch.yml` | `providers.<route>.defaultInput`、`models[].input` |
| WorkBuddy | `~/.workbuddy/models.json` | 模型条目 `supportsImages` |

模型不在 `pi-ai` 内置 catalog 里时，dsh 的模态解析链（`条目的 input` → `catalog 条目` → `路由的 defaultInput`）落到默认值 `["text"]`，于是 `dsh-tool-fs` 的 `inputModalities.includes("image")` 校验直接拒收。

## 用法

```bash
# 直接修复
FixImageSupport.exe

# 只看会改什么，不动文件
FixImageSupport.exe --dry-run
```

改完**必须重启** DSH Desktop / WorkBuddy 才生效（配置在启动时读取）。

## 为什么需要反复运行

Codex++ 网关每次启动都会**重写** `~/.dsh/cordis.patch.yml` 里带 `# >>> codex-plus-gateway` 标记的那一段，把手工加的 `defaultInput` / `models[].input` 抹掉。

所以这是持久性问题：**每次重启电脑后，再运行一次本工具即可。**

工具是幂等的 —— 配置已经正确时显示「无需改动」，不会重复插入。

## 特性

- **幂等**：重复运行无副作用
- **预演模式**：`--dry-run` 只看改动
- **自动备份**：修改前存为 `<文件名>.bak.YYYYmmddHHMMSS`
- **部分修复**：识别「只被抹掉一半」的情况（如保留 `defaultInput` 但删了 `models[].input`）
- **纯标准库**：无第三方依赖，便于打包
- **正确的中文控制台输出**：处理了 Windows 中文代码页 GBK 乱码

## 从源码构建

```bash
pip install pyinstaller
pyinstaller --clean --noconfirm build.spec
```

产物在 `dist/FixImageSupport.exe`。

## 注意

- EXE 未签名，首次运行 Windows SmartScreen 可能拦截 → 点「更多信息」→「仍要运行」
- 修改 `cordis.patch.yml` 依赖固定的文本结构；若上游大版本改了配置格式，脚本会**跳过并提示**，不会写坏文件
- 只改 `qwen3.5-397b` 的目标模型，其他模型（如 `deepseek-v4-*`）的 `supportsImages` 保持原样

## 免责

本工具只修改上述两个配置文件，不触碰其他任何数据。所有修改均有时间戳备份，可自行回滚。
