# Git 操作记录与后续手册

更新时间：2026-10-07（Asia/Shanghai）  
适用项目：D:\pcb\AI_PCB  
目的：记录本项目开始 Git 版本管理前已完成的检查、已完成的忽略规则配置，以及后续由用户手动执行的 Git/GitHub 操作。

## 1. 当前原则

- 后续所有 Git 初始化、暂存、提交、创建远程仓库、连接 GitHub 和上传操作，均由用户手动执行。
- Agent 不会自行执行 Git 初始化、git add、git commit、git remote add、git push 或任何上传操作。
- 建议 GitHub 仓库初始设为私有仓库，完成资料版权、保密范围和提交内容审查后，再决定是否公开。
- Git 只用于记录代码、配置、词表、目录元数据、文档和可复现说明；不用于保存密钥、虚拟环境、模型、索引或未经确认可公开分发的原始资料。

## 2. 已完成的操作

### 2.1 Git 状态检查

已对 D:\pcb\AI_PCB 进行只读检查，结果如下：

- 项目根目录不存在 .git 目录。
- 当前目录尚未执行 Git 初始化，不是 Git 工作树。
- 不存在本地分支、提交历史或远程仓库配置。
- 当前尚未连接 GitHub。
- 检查过程没有执行 git init、git add、git commit、git remote add 或 git push。

### 2.2 既有忽略规则检查

在 Git 初始化前，项目根目录已经存在 .gitignore。原有规则已包含：

    .venv/
    .env
    __pycache__/
    *.py[cod]
    .pytest_cache/
    .ruff_cache/

    data/index/
    data/cache/
    data/models/
    data/parsed/
    data/chunks/
    logs/

    data/raw/*
    !data/raw/.gitkeep

    .vscode/
    .idea/
    Thumbs.db
    Desktop.ini

其中 .env 用于防止真实 API Key 被提交；data/raw/ 用于防止原始资料被默认纳入版本管理；缓存、模型和旧索引也已排除。

### 2.3 用户已手动补充的忽略规则

用户已在 .gitignore 文件末尾手动加入以下规则，随后已完成只读核对：

    # 项目独立 Python 运行环境
    .venv-d312/
    .runtime/

    # 通用硬件 RAG V2 的可再生产物
    data/hardware-v2/parsed/
    data/hardware-v2/chunks/
    data/hardware-v2/index/
    data/hardware-v2/logs/

    # 未审核候选资料：保留审查记录，但不提交候选原文件
    未入库资料/*
    !未入库资料/资料审查.md

核对结果：上述 8 条规则均存在。

### 2.4 忽略规则写法的说明

不同写法不是不同的 Git 命令，而是 .gitignore 的不同匹配模式：

| 写法 | 含义 | 本项目用途 |
|---|---|---|
| .env | 忽略名为 .env 的文件 | 防止 API Key 进入版本库 |
| .venv-d312/ | 忽略整个目录及全部内容 | 不提交独立虚拟环境 |
| data/hardware-v2/index/ | 忽略指定目录及全部内容 | 不提交可再生成的本地索引 |
| 未入库资料/* | 忽略目录内所有内容，但目录本身未被整体忽略 | 不提交候选 PDF、PPT 等资料 |
| !未入库资料/资料审查.md | 取消前面规则对该单一文件的忽略 | 保留可追溯的资料审查记录 |

未入库资料采用“目录内所有文件忽略，再为审查记录留例外”的方式，是因为若直接忽略整个未入库资料目录，Git 通常不会再进入该目录发现例外文件。

## 3. 版本管理范围建议

### 3.1 建议纳入 Git 的内容

    src/
    tests/
    scripts/
    prompts/
    evals/
    data/catalog/
    data/taxonomy/
    data/classification/
    项目说明文档/
    README.md
    AGENT.md
    plan.md
    pyproject.toml
    config*.yaml
    .env.example
    .gitignore

这些内容描述了程序逻辑、测试、资料元数据、词表、配置、评测契约、项目说明和可复现方式，适合进行版本管理。

### 3.2 默认不纳入 Git 的内容

    .env
    .venv/
    .venv-d312/
    .runtime/
    data/cache/
    data/models/
    data/raw/
    data/index/
    data/hardware-v2/parsed/
    data/hardware-v2/chunks/
    data/hardware-v2/index/
    data/hardware-v2/logs/
    未入库资料中的候选原文件

原因：

- .env 可能包含真实 API Key。
- 虚拟环境和运行时可重新建立，体积大且与机器相关。
- 模型、缓存、向量、Qdrant 和 BM25 索引可以由代码、配置和原始资料重新生成。
- 原始厂商资料、培训材料和候选文件可能受版权、分发许可或项目保密范围限制。
- 即使资料不保密，也应在公开上传前确认其再分发是否合适。

### 3.3 需要逐项判断的内容

以下内容不应一概自动提交：

- 含大段原文摘录的评测报告。
- 检索日志、在线回答日志和截图。
- 可能含外发证据正文的报告。
- 用户、客户、项目名称、内部路径或实际产品信息。
- 原厂 PDF、PPTX、DOCX 及其转换件。

对于这类内容，先判断是否含敏感信息、受版权保护内容或不希望公开的工程信息，再决定是否提交。

## 4. 敏感数据保护原则

### 4.1 防止泄露的四层措施

| 层级 | 做法 | 作用 |
|---|---|---|
| 不提交 | .gitignore | 防止未跟踪的敏感文件进入暂存区 |
| 本地检查 | 提交前使用密钥扫描工具 | 在提交前发现 Token、私钥、密码等 |
| GitHub 检查 | Secret Scanning 和 Push Protection | 推送时检测并可能拦截支持的密钥模式 |
| 泄露处置 | 吊销或轮换密钥，并清理 Git 历史 | 已提交过的真实凭据不能仅靠删除文件解决 |

### 4.2 必须注意的事实

- .gitignore 只对尚未被 Git 跟踪的文件有效。
- 如果真实 Key 已经提交，即使后来删除文件并加入 .gitignore，旧提交中仍可能保留该 Key。
- 私有仓库是访问控制，不等于允许提交真实密钥。
- Git LFS 用于大文件，不是敏感数据保护机制。
- 若真实凭据泄露，第一步应在提供方处吊销或轮换，而不是只修改 Git 历史。

### 4.3 本项目中的重点对象

绝不提交：

    .env
    真实 DeepSeek API Key
    私钥、Token、密码、连接字符串
    客户资料、保密资料或未获准公开的设计资料

应谨慎处理：

    原始 PDF/PPTX/DOCX
    未入库候选资料
    模型输出、检索日志、评测报告
    含原文长摘录的 Markdown
    工程截图或包含本地目录、用户名、产品信息的文件

## 5. 后续由用户手动完成的操作

以下顺序为建议流程。执行前请自行确认每一条命令的含义和影响。

### 5.1 初始化本地 Git 仓库

在项目根目录手动执行：

    git init

然后查看状态：

    git status --short --branch

预期：Git 创建 .git 目录，并显示当前初始分支；此时还没有提交。

### 5.2 实际验证忽略规则

初始化后，可手动执行：

    git status --ignored --short

该命令会显示被忽略文件。重点确认下列内容处于忽略状态：

    .env
    .venv-d312/
    .runtime/
    data/cache/
    data/models/
    data/raw/
    data/hardware-v2/parsed/
    data/hardware-v2/chunks/
    data/hardware-v2/index/
    data/hardware-v2/logs/
    未入库资料中的 PDF、PPT 等候选原文件

同时确认以下文件没有被忽略：

    .env.example
    未入库资料/资料审查.md
    项目说明文档/中的项目记录 Markdown
    data/catalog/、data/taxonomy/、data/classification/中的配置资料

如需查明某个具体文件为什么被忽略，可手动执行：

    git check-ignore -v "文件相对路径"

例如：

    git check-ignore -v "未入库资料/资料审查.md"

如果该文件没有输出，通常表示它没有被忽略；这是预期结果。

### 5.3 配置 Git 身份

建议只为当前项目设置身份，不修改全局 Git 配置：

    git config user.name "你的显示名称"
    git config user.email "你的邮箱地址"

检查：

    git config --local --list

邮箱会写入未来提交记录；如果仓库准备公开，可考虑使用 GitHub 提供的 noreply 邮箱地址保护个人邮箱。

### 5.4 首次暂存前进行人工审查

不建议第一次直接使用 git add .。建议先明确选择需要纳入版本管理的目录和文件，例如：

    git add src tests scripts prompts evals data/catalog data/taxonomy data/classification 项目说明文档 README.md AGENT.md plan.md pyproject.toml config.hardware-v2.yaml config.hardware-v2-online.yaml .env.example .gitignore

如果需要同时保留其他明确确认安全的文件，再单独添加。

暂存后检查文件名单：

    git diff --cached --name-only

检查内容差异：

    git diff --cached

检查常见空格错误：

    git diff --cached --check

在确认文件名单中没有 .env、模型、虚拟环境、原始资料、大型索引、候选资料和不应公开的报告前，不要创建首个提交。

### 5.5 提交前的敏感信息检查

建议在首次提交前使用本地密钥扫描工具，例如 Gitleaks、detect-secrets 或 TruffleHog 之一。

密钥扫描是补充措施，不是替代人工审核。特别要检查：

    DEEPSEEK_API_KEY=
    API_KEY=
    SECRET=
    TOKEN=
    PASSWORD=
    BEGIN PRIVATE KEY
    数据库连接字符串
    云服务访问密钥

扫描发现真实凭据时，不要提交；应先移至 .env 或安全的密钥管理方式。

### 5.6 创建首个本地提交

确认暂存内容安全后，手动执行：

    git commit -m "Initial commit: general hardware RAG V2"

提交后检查：

    git status
    git log --oneline --decorate -n 5

预期：工作区干净，且存在首个提交。

### 5.7 在 GitHub 创建远程仓库

建议先创建私有、空的 GitHub 仓库：

- 仓库名可使用 ai-pcb 或 general-hardware-rag。
- 创建时不要自动生成 README、.gitignore 或 License，以避免与本地首个提交产生不必要的初始分叉。
- 创建后复制 HTTPS 或 SSH 远程地址。
- 若使用 HTTPS，建议采用 GitHub CLI、系统凭据管理器或细粒度 Token；不要把 Token 写入仓库文件。

### 5.8 连接远程并首次推送

确认 GitHub 仓库地址无误后，手动执行：

    git branch -M main
    git remote add origin "GitHub 仓库地址"
    git remote -v
    git push -u origin main

推送前再次确认 remote -v 显示的是你自己的目标仓库，而不是陌生地址。

### 5.9 GitHub 侧安全设置

仓库创建并推送后，建议手动检查：

- 仓库保持 Private。
- Settings 中确认访问成员和权限。
- Security and quality 或 Advanced Security 中检查 Secret Scanning。
- 在可用的仓库和套餐条件下启用 Push Protection。
- 为主分支 main 设置分支保护规则；以后通过 Pull Request 合并重要修改。
- 不要绕过 GitHub 对疑似真实密钥的推送拦截；先确认并处理。

## 6. 若误提交敏感内容

如果误提交真实 API Key、Token、密码或私钥：

1. 先立即吊销或轮换该凭据。
2. 从当前文件中移除凭据，并改用 .env 或其他密钥管理方式。
3. 确认凭据出现在哪些提交和路径。
4. 使用专门的历史重写工具清理 Git 历史。
5. 若已推送，按重写后历史执行强制推送，并通知所有协作者重新同步。
6. 检查 GitHub 的 Pull Request、fork、已克隆副本和安全告警。

只删除工作区文件或只补充 .gitignore，不能消除已存在于历史提交中的真实密钥。

## 7. 当前状态摘要

| 项目 | 当前状态 |
|---|---|
| Git 是否初始化 | 否 |
| 是否存在 .git 目录 | 否 |
| 是否存在本地提交 | 否 |
| 是否存在 GitHub 远程地址 | 否 |
| .gitignore 是否已补充 | 是，由用户手动完成并已核对 |
| Agent 是否执行 Git 操作 | 否 |
| 后续 Git 操作执行者 | 用户手动执行 |

