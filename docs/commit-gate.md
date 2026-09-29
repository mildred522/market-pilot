# 提交前安全门禁

Market Pilot 使用本地 `pre-commit` hook 审查**已经 staged 的内容**。这样可以把一次计划中的 commit 与工作区里尚未准备好的修改分开，避免误把旧主题代码、临时文件或本地数据一起提交。

## 启用

在仓库根目录执行一次：

```bash
./scripts/install-git-hooks.sh
```

它只修改当前仓库的 Git 配置：

```text
core.hooksPath=.githooks
```

不会修改全局 Git 配置，也不会上传任何数据。

## 门禁行为

提交时 hook 会：

1. 列出本次 commit 的完整 staged 文件范围，帮助识别无关改动。
2. 执行 `git diff --cached --check`，阻断明显的 diff 错误。
3. 阻断环境文件、私钥、数据库、日志、备份、数据目录和未知二进制文件。
4. 对 CSV、TSV、JSONL、Parquet、Excel 等结构化数据文件给出人工复核警告，确认来源、脱敏和授权范围。
5. 扫描 staged 内容中的高置信度密钥、Token、内网地址、冲突标记、下载后直接执行和危险 shell 命令。
6. 对跨越多个顶层目录的宽范围修改给出警告，并要求操作者在终端明确确认。
7. 不打印疑似密钥的原文，只打印文件路径、风险类型和行号。

高风险发现会直接阻断 commit。门禁自身文件发生变化时属于高优先级警告：本地交互提交必须明确确认，CI 环境直接阻断。其他普通范围警告也会显示审查摘要并询问是否继续；非交互环境默认阻断。

如果终端环境无法提供 `/dev/tty`，在已经阅读完整审查报告并确认只有普通警告后，可以使用一次性显式确认：

```bash
COMMIT_GATE_APPROVED=1 git commit -m "<commit message>"
```

该变量不能绕过高风险错误；不要把它写入 shell 配置或自动化脚本。

## 推荐流程

```bash
git add <本次 commit 计划中的文件>
git diff --cached --stat
git diff --cached --name-status
git commit -m "<经过审查的 commit message>"
```

门禁只审查 staged 内容，不会替代人工审查，也不是病毒扫描器。新增平台连接器、权限模型、数据导入器等高风险模块时，仍需要人工检查业务授权、网络访问、数据脱敏和依赖来源。
