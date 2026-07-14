import os
import time
import json
import requests
import io
import sys

# ==========================================
# 强制禁用系统代理 (防止 Clash/V2Ray 拦截本地请求导致卡死)
# ==========================================
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
os.environ['no_proxy'] = '127.0.0.1,localhost'

# ==========================================
# 配置区
# ==========================================
BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 60


# 颜色打印
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    RESET = '\033[0m'


def print_step(desc):
    print(f"\n{Colors.CYAN}▶ [测试步骤] {desc}{Colors.RESET}")


def print_pass(desc):
    print(f"{Colors.GREEN}  ✅ PASS: {desc}{Colors.RESET}")


def print_fail(desc, detail=""):
    print(f"{Colors.RED}  ❌ FAIL: {desc}{Colors.RESET}")
    if detail:
        print(f"     详情: {detail}")


def print_warn(desc):
    print(f"{Colors.YELLOW}  ⚠️ WARN: {desc}{Colors.RESET}")


# ==========================================
# 前置检查：拒绝 Mock
# ==========================================
def check_env_no_mock():
    print_step("检查环境变量配置 (拒绝 Mock)")
    mock_vlm = os.getenv("USE_MOCK_VLM", "false").lower()
    mock_int = os.getenv("USE_MOCK_INTEGRATION", "false").lower()

    if mock_vlm == "true" or mock_int == "true":
        print_fail("环境处于 Mock 模式", "请确保 .env 中 USE_MOCK_VLM=false 和 USE_MOCK_INTEGRATION=false")
        return False

    print_pass("环境已配置为真实 API 调用模式")
    return True


# ==========================================
# 辅助：解析 SSE 流
# ==========================================
def parse_sse_response(response):
    events = []
    current_event = None
    current_data = []

    for line in response.iter_lines(decode_unicode=True):
        if not line:
            if current_event:
                data_str = "".join(current_data)
                try:
                    data_json = json.loads(data_str)
                except:
                    data_json = data_str

                if current_event == "step":
                    step_name = data_json.get("step", "unknown") if isinstance(data_json, dict) else ""
                    print(f"  💡 收到 SSE 事件: step ({step_name})")
                elif current_event == "progress":
                    stage = data_json.get("step", data_json.get("stage", "unknown")) if isinstance(data_json,
                                                                                                   dict) else "unknown"
                    print(f"  💡 收到 SSE 事件: progress ({stage})")
                elif current_event == "result":
                    print(f"  💡 收到 SSE 事件: result (最终报告)")
                elif current_event == "done":
                    print(f"  💡 收到 SSE 事件: done (入库完成)")
                elif current_event == "error":
                    print(f"  💡 收到 SSE 事件: error")

                events.append({"event": current_event, "data": data_json})
                current_event = None
                current_data = []
            continue

        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].strip())

    return events


# ==========================================
# 测试模块 1: 主多模态诊断管线
# ==========================================
def test_core_pipeline():
    print_step("=== 测试主多模态诊断管线 (纯病历推理) ===")

    print_step("POST /upload (提交纯病历文本)")
    clinical_text = "患者男，65岁，左足底发现黑色不规则斑块约半年，近期增大明显，伴有溃疡和出血。无家族史。"
    lab_json = json.dumps({"breslow_thickness": 2.5, "ulceration": True, "braf_mutation": "突变型"})

    # 必须使用 files 字典强制 multipart/form-data，避免 Windows 下 requests 卡死
    files = {
        'clinical_text': (None, clinical_text),
        'lab_json': (None, lab_json)
    }
    try:
        res = requests.post(f"{BASE_URL}/upload", files=files, timeout=TIMEOUT)
        res.raise_for_status()
        task_id = res.json().get("task_id")
        if not task_id:
            print_fail("未获取到 task_id")
            return
        print_pass(f"获取 task_id: {task_id}")
    except Exception as e:
        print_fail("上传失败", str(e))
        return

    print_step(f"GET /stream/{task_id} (监听 SSE 诊断流，请耐心等待 1-2 分钟...)")
    try:
        with requests.get(f"{BASE_URL}/stream/{task_id}", stream=True, timeout=300) as r:
            events = parse_sse_response(r)

            has_step = False
            has_result = False
            final_report = None

            for ev in events:
                if ev["event"] == "step":
                    has_step = True
                elif ev["event"] == "result":
                    has_result = True
                    final_report = ev["data"]
                elif ev["event"] == "error":
                    print_fail("收到 error 事件", ev['data'])
                    return

            if not has_step:
                print_fail("未收到任何 step 事件")

            if has_result and final_report:
                risk = final_report.get("risk_level", "")
                recs = final_report.get("recommendations", [])
                if not risk or not recs:
                    print_fail("报告内容为空", final_report)
                else:
                    print_pass(f"风险分级: {risk}")
                    print_pass(f"建议条目数: {len(recs)} (证明 LLM 真实生成)")
                    if "T2b" in str(final_report):
                        print_pass("病理分期逻辑正确 (T2b: 2.5mm+溃疡)")

            print_step(f"GET /features/{task_id} (查询历史诊断)")
            res_feat = requests.get(f"{BASE_URL}/features/{task_id}", timeout=TIMEOUT)
            if res_feat.status_code == 200 and res_feat.json().get("task_id"):
                print_pass("历史诊断查询成功")
            else:
                print_fail("历史诊断查询失败", res_feat.text)

    except Exception as e:
        print_fail("SSE 流获取失败", str(e))


# ==========================================
# 测试模块 2: KB-RAG 模块全量接口
# ==========================================
def test_kb_rag_module():
    print_step("=== 测试 KB-RAG 知识库问答模块 ===")

    print_step("POST /rag/index/create")
    try:
        res = requests.post(f"{BASE_URL}/rag/index/create", data={"kb_id": 999}, timeout=TIMEOUT)
        if res.status_code == 200:
            print_pass("索引空间就绪")
        else:
            print_fail("创建索引失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/ingest?stream=true (真实文档入库)")
    test_doc_content = "黑色素瘤的预后取决于Breslow厚度。厚度小于1mm为T1期，预后较好；厚度大于4mm为T4期，预后较差，易发生淋巴结转移。"

    try:
        files = {'file': ('test_doc.txt', io.BytesIO(test_doc_content.encode('utf-8')), 'text/plain')}
        data = {
            'task_id': 9001, 'task_code': 'E2E_TEST', 'kb_id': 999,
            'doc_id': 888, 'doc_version_id': 1, 'chunk_size': 100, 'chunk_overlap': 20
        }
        with requests.post(f"{BASE_URL}/rag/ingest?stream=true", files=files, data=data, stream=True, timeout=120) as r:
            events = parse_sse_response(r)
            stages = [ev['data'].get('stage') for ev in events if ev['event'] == 'progress']
            done_event = next((ev['data'] for ev in events if ev['event'] == 'done'), None)

            if "parsing" in stages and "splitting" in stages and "embedding" in stages and "indexing" in stages:
                print_pass(f"SSE 进度完整: {' -> '.join(stages)}")
            else:
                print_fail("SSE 进度不完整", str(stages))

            if done_event and done_event.get("chunk_count", 0) > 0:
                print_pass(f"入库成功，生成 chunk 数: {done_event['chunk_count']}")
            else:
                print_fail("入库未完成", str(events))
    except Exception as e:
        print_fail("入库请求异常", str(e))

    print_step("POST /rag/debug/retrieval")
    try:
        payload = {"query": "黑色素瘤预后因素", "kb_ids": [999], "top_k": 3, "threshold": 0.3}
        res = requests.post(f"{BASE_URL}/rag/debug/retrieval", json=payload, timeout=TIMEOUT)
        if res.status_code == 200 and len(res.json()) > 0:
            print_pass(f"检索命中: {len(res.json())} 条")
        else:
            print_fail("检索失败或未命中", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/debug/rewrite")
    try:
        payload = {"query": "那个病怎么治", "history": [{"role": "user", "content": "黑色素瘤怎么分期？"}]}
        res = requests.post(f"{BASE_URL}/rag/debug/rewrite", json=payload, timeout=TIMEOUT)
        if res.status_code == 200 and res.json().get("route"):
            print_pass(f"意图路由: {res.json().get('route')}, 改写: {res.json().get('rewritten_query')}")
        else:
            print_fail("改写失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/chat (非流式真实问答)")
    try:
        payload = {
            "conversation_id": 1, "question": "Breslow厚度大于4mm是什么分期？",
            "kb_ids": [999], "options": {"stream": False, "enable_agent": False}
        }
        res = requests.post(f"{BASE_URL}/rag/chat", json=payload, timeout=TIMEOUT)
        if res.status_code == 200:
            resp = res.json()
            if "T4" in resp.get("answer", ""):
                print_pass("LLM 回答正确包含 T4")
            else:
                print_warn("LLM 回答未包含 T4，请人工核查回答质量", resp.get("answer"))

            if resp.get("sources"):
                print_pass(f"返回引用来源: {len(resp['sources'])} 条")
            else:
                print_fail("未返回引用来源")
        else:
            print_fail("问答失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("GET /rag/stream/{conversation_id} (流式真实问答)")
    try:
        params = {
            "question": "T4期黑色素瘤预后如何？", "kb_ids": "999",
            "top_k": 3, "similarity_threshold": 0.3, "enable_agent": "true"
        }
        with requests.get(f"{BASE_URL}/rag/stream/2", params=params, stream=True, timeout=TIMEOUT) as r:
            events = parse_sse_response(r)
            has_intent = any(ev['data'].get('step') == 'intent_route' for ev in events if ev['event'] == 'progress')
            has_result = any(ev['event'] == 'result' for ev in events)
            if has_intent: print_pass("SSE 包含 intent_route 阶段")
            if has_result: print_pass("SSE 流式问答完成")
    except Exception as e:
        print_fail("流式问答异常", str(e))

    print_step("POST /rag/chat/completions (OpenAI 兼容格式)")
    try:
        headers = {"X-KB-IDS": "999"}
        payload = {"messages": [{"role": "user", "content": "简述黑色素瘤"}], "stream": False,
                   "model": "deepseek-v4-flash"}
        res = requests.post(f"{BASE_URL}/rag/chat/completions", json=payload, headers=headers, timeout=TIMEOUT)
        if res.status_code == 200 and res.json().get("choices"):
            print_pass("OpenAI 格式响应正常")
        else:
            print_fail("OpenAI 格式失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/agents/run (Agent 工作流)")
    try:
        payload = {"question": "分析黑色素瘤", "kb_ids": [999], "workflow_name": "langgraph_rag_agent"}
        res = requests.post(f"{BASE_URL}/rag/agents/run", json=payload, timeout=TIMEOUT)
        resp_data = res.json()
        # 校验状态为 completed，且 agent_trace 必须不为空且包含节点
        if res.status_code == 200 and resp_data.get("status") == "completed":
            if resp_data.get("agent_trace") and len(resp_data["agent_trace"].get("nodes", [])) > 0:
                print_pass(f"Agent 工作流执行完成，返回节点轨迹数: {len(resp_data['agent_trace']['nodes'])}")
            else:
                print_fail("Agent trace 为空", resp_data)
        else:
            print_fail("Agent 执行失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("GET /rag/tools & POST /rag/tools/run")
    try:
        res = requests.get(f"{BASE_URL}/rag/tools", timeout=TIMEOUT)
        if res.status_code == 200 and len(res.json()) >= 4:
            print_pass(f"获取到 {len(res.json())} 个内置工具")
        else:
            print_fail("工具列表获取失败", res.text)

        payload = {"tool_name": "kb_lookup_debug", "arguments": {"query": "Breslow", "kb_ids": [999]}}
        res_run = requests.post(f"{BASE_URL}/rag/tools/run", json=payload, timeout=TIMEOUT)
        # 校验服务端真实返回的是 completed
        if res_run.status_code == 200 and res_run.json().get("status") in ["completed", "success", "succeeded"]:
            print_pass("工具 kb_lookup_debug 执行成功")
        else:
            print_fail("工具执行失败", res_run.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/etl/run & GET /rag/etl/jobs/{job_id}")
    try:
        files = {'file': ('etl_test.csv', io.BytesIO(b'name,age\nJohn,30\nJane,25'), 'text/csv')}
        data = {'kb_id': 999, 'doc_id': 889, 'doc_version_id': 1}
        res = requests.post(f"{BASE_URL}/rag/etl/run", files=files, data=data, timeout=TIMEOUT)
        if res.status_code == 202:
            job_id = res.json().get("job_id")
            print_pass(f"ETL 任务已提交: {job_id}")

            time.sleep(5)
            res_job = requests.get(f"{BASE_URL}/rag/etl/jobs/{job_id}", timeout=TIMEOUT)
            if res_job.status_code == 200 and res_job.json().get("status") in ["succeeded", "running"]:
                print_pass(f"ETL 任务状态: {res_job.json().get('status')}")
            else:
                print_fail("查询 ETL 状态失败", res_job.text)
        else:
            print_fail("ETL 提交失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("POST /rag/feedback/export")
    try:
        payload = {"conversations": [{"conversation_id": 1, "question": "Q1", "answer": "A1", "feedback": "positive"}]}
        res = requests.post(f"{BASE_URL}/rag/feedback/export", json=payload, timeout=TIMEOUT)
        if res.status_code == 200 and "application/jsonl" in res.headers.get("content-type", ""):
            print_pass("JSONL 导出成功")
        else:
            print_fail("导出失败", res.text)
    except Exception as e:
        print_fail("请求异常", str(e))

    print_step("DELETE /rag/index/delete (清理测试数据)")
    try:
        res = requests.delete(f"{BASE_URL}/rag/index/delete", data={"kb_id": 999}, timeout=TIMEOUT)
        if res.status_code == 200:
            print_pass("测试索引已清理")
        else:
            print_warn("清理失败，请手动删除 Qdrant 中 kb_id=999 的数据")
    except Exception as e:
        print_fail("请求异常", str(e))


if __name__ == "__main__":
    print(f"{Colors.CYAN}====================================")
    print(" DermaIntegrate AI 端到端真实环境测试")
    print("====================================" + Colors.RESET)

    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v

    if not check_env_no_mock():
        sys.exit(1)

    test_core_pipeline()
    test_kb_rag_module()

    print(f"\n{Colors.CYAN}====================================")
    print(" 测试执行完毕，请检查上方是否有 FAIL 项")
    print("====================================" + Colors.RESET)