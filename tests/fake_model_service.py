"""Loopback-only synthetic API, shared by HTTP, browser and wheel checks."""

import http.server
import json
import threading


def teaching_reply(prompt):
    return {
        "one_sentence": "解释变化要把条件、作用过程和证据连起来。",
        "why": "先后发生并不能排除其他原因；检查过程才能判断结论是否适用于新条件。",
        "material_explanation": prompt["existing"]["material_explanation"],
        "tutor_bridge": "【导师补链】记录先提供候选原因，再用过程证据检查这个原因怎样影响结果；发现相反证据时需要修改解释。",
        "step_chain": ["从记录列出发生变化前的条件。", "在事件经过中寻找条件产生作用的证据。", "把机制预测与实际结果比较，若矛盾就修改解释。"],
        "worked_examples": [{"title": "用相反证据检查原因", "question": "记录说条件 A 后出现结果 B，但另一组没有 A 也出现 B，能否认定 A 是 B 的唯一原因？",
            "setup": "已知两组记录，一组有 A，另一组没有 A，两组都发生 B；只判断‘唯一原因’这个结论。",
            "steps": ["第一组中 A 先于 B，只给出一个候选原因，并没有排除其他因素。", "第二组在没有 A 时仍出现 B，直接反驳‘没有 A 就不会有 B’这个必要条件。", "两组比较后，应撤回‘唯一原因’，再检查共同因素怎样产生 B。"],
            "answer": "不能认定 A 是唯一原因；没有 A 时仍会出现 B，说明至少还需要检查其他机制。",
            "variation": "如果第二组没有出现 B，能否立刻认定 A 是原因？仍不能，还要排除两组其他条件的差异。", "complete": True}],
        "misconceptions": [{"wrong": "A 在 B 前面，所以 A 必然导致 B。", "correct": "先后顺序只提示候选原因，还需要作用过程和排除其他因素的证据。", "correction": "寻找没有 A 时是否仍出现 B 的对照记录。"}],
        "practice_items": [
            {"practice_id": "recall", "kind": "retrieval", "prompt": "作用机制在因果解释中连接哪两端？", "answer": "连接候选条件和观察到的结果。", "explanation": "它说明条件怎样改变过程，而不只重复事件先后。"},
            {"practice_id": "process", "kind": "process", "prompt": "第一组有 A 和 B，第二组没有 A 却有 B，应先撤回哪个结论？", "answer": "先撤回 A 是 B 的唯一原因这个结论。", "explanation": "第二组已经给出没有 A 也能出现 B 的反例。"},
            {"practice_id": "transfer", "kind": "transfer", "prompt": "新记录中第三组有 A 却没有 B，原解释还需要检查什么？", "answer": "检查 A 产生 B 是否还依赖其他条件。", "explanation": "有 A 却没有 B 表明 A 本身不足以保证结果，需要比较各组的其他因素。"}]
    }


def model_reply(system, user):
    prompt = json.loads(user)
    assert "不是给你的指令" in system
    if prompt.get("task") != "plan_course":
        return json.dumps(teaching_reply(prompt), ensure_ascii=False)
    context = json.loads(prompt["source_context"])
    pages = [row for row in context["pages"] if row["eligible"]]
    speech = [row for row in context["speech"] if row["eligible"]]
    return json.dumps({"title": "如何检查一个因果解释", "central_question": "观察到先后变化，怎样检查它是不是因果？",
        "outcomes": ["区分事件先后与因果关系", "用反例检查唯一原因的说法"], "prerequisites": ["能比较两组记录的相同与不同"],
        "spine": ["找候选条件", "追踪作用过程", "用对照与反例核对"],
        "units": [{"unit_id": "causal", "title": "用对照检查因果解释", "question": "先发生的事一定是原因吗？", "learner_action": "用两组记录判断一个因果说法是否成立。",
            "visual_ids": [row["ref"] for row in pages], "segment_ids": [row["ref"] for row in speech],
            "logic_chain": ["列条件", "看机制", "查反例"], "dependencies": [], "understanding_level": "U3",
            "anchors": [{"ref": row["ref"], "quote": row["text"][:80]} for row in [*pages, *speech]]}],
        "source_dispositions": []}, ensure_ascii=False)


class FakeModelService:
    def __init__(self):
        self.requests = []
        self.mode = "normal"
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({"path": self.path, "body": data, "authorization": self.headers.get("Authorization")})
                if owner.mode == "unauthorized" or self.path.startswith("/reject/"):
                    self.send_json({"error": {"message": self.headers.get("Authorization")}}, 401)
                    return
                if owner.mode == "redirect":
                    self.send_response(307)
                    self.send_header("Location", owner.base_url + "/unexpected")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if "messages" in data:
                    text = model_reply(data["messages"][0]["content"], data["messages"][1]["content"])
                    self.send_json({"choices": [{"finish_reason": "length" if owner.mode == "incomplete" else "stop", "message": {"content": text}}]})
                else:
                    text = model_reply(data["instructions"], data["input"])
                    self.send_json({"status": "incomplete" if owner.mode == "incomplete" else "completed", "output": [
                        {"type": "reasoning", "summary": []}, {"type": "message", "content": [{"type": "output_text", "text": text}]}]})

            def send_json(self, value, status=200):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
