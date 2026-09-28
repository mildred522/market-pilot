# Minimal Plan–Execute Demo

This isolated demo reads the repository's single operating sample (`orders.csv` and
`menu_items.csv`) and demonstrates the project's core safety chain without starting
the full application, requiring a model key, or copying data.

```powershell
python -m plan_execute_demo "做一次完整经营体检" --mode full
python -m plan_execute_demo "哪些菜品需要优化？" --json
python -m unittest plan_execute_demo.test_demo
python -m plan_execute_demo.server
```

The supported execution surface is intentionally small: `revenue`, `menu`, and
`survival`. Focused planning chooses exactly one of them using a deterministic policy;
full planning uses all three. Each output metric becomes an `E*` evidence fact, and a
report finding cannot contain a numeric claim unsupported by its cited facts.

Open `http://127.0.0.1:8765` after starting the local server. The page can use the
built-in sample or accept an orders CSV and a menu-cost CSV. It recognizes the common
English and Chinese headers shown in the demo, produces a mapping before analysis, and
keeps the uploaded rows in memory only.

## 配置 LLM API Key

最方便的方式是在本地网页展开“配置 DeepSeek（可选）”，填写 API Key、接口地址和模型后点击
“保存到本次服务”。Key 只存在当前本地服务进程内，关闭服务即清除。

也可填写在 Demo 目录的 `.env` 文件中，供一键启动脚本加载。首次配置：

```powershell
Copy-Item .\plan_execute_demo\.env.example .\plan_execute_demo\.env
notepad .\plan_execute_demo\.env
```

DeepSeek 的默认配置为：

```dotenv
PLAN_EXECUTE_LLM_URL=https://api.deepseek.com/chat/completions
PLAN_EXECUTE_LLM_API_KEY=sk-你的真实密钥
PLAN_EXECUTE_LLM_MODEL=deepseek-v4-flash
```

`PLAN_EXECUTE_LLM_API_KEY` 只作为服务端请求的 `Authorization: Bearer` 请求头；不会写入报告或
持久化到数据库。`.env` 已被局部 `.gitignore` 忽略，不能提交。未创建 `.env`、模型调用失败或模型
返回的证据不合法时，系统自动使用确定性报告。

## 一键构建并启动

```powershell
powershell -ExecutionPolicy Bypass -File .\plan_execute_demo\start-demo.ps1
```

脚本会编译 Demo、运行测试、加载本机 `.env`、安全复用或启动端口 `8765` 的本 Demo 服务，然后打开网页。
不想自动打开浏览器时，加 `-NoBrowser`。

The runtime permits one replan only. If `menu` or `survival` fails, it may substitute the
safe `revenue` capability only when that capability has not already run. It never retries
the failed tool and records the choice in the execution trace.
