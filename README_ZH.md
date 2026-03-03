# onyx-send2boox

一款与文石(Boox)电子书 send2boox 服务进行数据同步的 Python 命令行工具。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp config.example.toml config.toml
```

在 `config.toml` 中填写账号邮箱和服务器地址（如使用默认服务器可不改）：

```toml
server = "send2boox.com"
email = "your_email@example.com"
mobile = ""
```

`email` 和 `mobile` 都支持，二选一填写即可。

## 认证流程

```bash
send2boox auth login
send2boox auth code <6_digit_code>
send2boox auth login --mobile 13800138000
send2boox auth code <6_digit_code> --mobile 13800138000
```

拿到的 token 会保存回 `config.toml`。默认情况下，`auth code` 还会调用
`users/syncToken`，并将浏览器 cookies 写入 `session-cookies.json` 以便调试。
如果 cookie 同步为空，命令会给出警告并继续保留仅 token 的工作流。

## 常用命令

```bash
send2boox file list --limit 24 --offset 0
send2boox file send ./book1.epub ./book2.pdf
send2boox file delete <file_id_1> <file_id_2>
```

无需打开浏览器 DevTools 即可查看书库图书。默认 `book list` 输出 `ID/Name`
表格；如需完整元数据（包含 `unique_id`，可作为 `statistics/readInfoList` 的
`docIds`）可使用 `--json`：

```bash
send2boox book list
send2boox book list --json
send2boox book list --include-inactive --output ./library-books.json
```

如果你只需要 `unique_id`：

```bash
send2boox book list --json | jq -r '.[].unique_id' > book-ids.txt
```

查询单本书阅读统计（字段来自 `statistics/readInfoList`）：

```bash
send2boox book stats 0138a37b2e77444b9995913cca6a6351
send2boox book stats 0138a37b2e77444b9995913cca6a6351 --output ./read-stats.json
```

导出单本书的划线批注与书签（来自 `READER_LIBRARY`）：

```bash
send2boox book annotations 0138a37b2e77444b9995913cca6a6351 --output ./annotations.json
send2boox book bookmarks 0138a37b2e77444b9995913cca6a6351 --output ./bookmarks.json
```

以上命令默认返回有效记录（`status == 0`）。传入 `--include-inactive` 可包含
已删除/归档的历史记录。

## CLI 输出约定

- `stdout`：结构化命令数据（表格 / JSON）。
- `stderr`：状态与进度信息。
- 状态前缀统一如下：
  - `[OK]`：成功状态提示。
  - `[WARN]`：非致命告警或回退信息。
  - `[ERROR]`：致命错误（命令以非 0 退出）。

## 项目结构

- `src/send2boox/api.py`：HTTP API 层（超时与错误处理）。
- `src/send2boox/client.py`：业务逻辑（认证、列表、上传、删除）。
- `src/send2boox/config.py`：类型化 TOML 配置读写。
- `src/send2boox/cli.py`：基于 argparse 的 CLI 入口。
- `tests/`：pytest 测试套件。
- `.github/workflows/ci.yml`：CI 中执行 lint + type-check + test。

## 开发检查

```bash
ruff check .
mypy src
pytest
```

## 安全说明

- `config.toml` 可能包含敏感 token，已被 git ignore。
- 不要提交真实凭据。
