# 参与贡献

从仓库根目录执行命令。

## 安装

```bash
uv sync --group dev
pnpm --dir frontend install
```

## 检查

```bash
uv run pytest
pnpm --dir frontend build
```

前端开发（另开终端跑 `uv run knowhow serve`）：

```bash
pnpm --dir frontend dev
```

## 不要提交

- `.env`：本地密钥。对照 `.env.example` 在本机填写，不要把真实密钥写进仓库。
- `.knowhow/`：会话、记忆等本机数据。
