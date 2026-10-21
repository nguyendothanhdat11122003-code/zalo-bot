import os
import time
import threading
import json
import io
import re
from flask import Flask, request, jsonify, render_template_string
from tool_tdatt import ZaloWarClient, parse_cookie_string

app = Flask(__name__)
bot_client = None
running_status = threading.Event()
logs_list = []

# Ghi đè hàm rprint để đẩy log lên web
import tool_tdatt
def web_rprint(*args, **kwargs):
    text = " ".join([str(a) for a in args])
    text = re.sub(r'\x1b\[[0-9;]*m', '', text) # Xoá màu ANSI
    logs_list.append(text)
    if len(logs_list) > 100: logs_list.pop(0)

tool_tdatt.rprint = web_rprint

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Zalo War Tool (Web)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #111; color: #fff; padding: 15px; }
        h2 { color: #00ff00; }
        .box { background: #222; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #333; }
        input, select, textarea { width: 100%; padding: 10px; margin: 5px 0; background: #000; color: #00ff00; border: 1px solid #444; box-sizing: border-box; font-family: monospace; }
        button { width: 100%; padding: 12px; margin-top: 5px; background: #00ff00; color: #000; border: none; font-weight: bold; cursor: pointer; border-radius: 4px; }
        button.stop { background: #ff0000; color: #fff; }
        pre { background: #000; color: #00ff00; padding: 10px; height: 250px; overflow-y: scroll; border: 1px solid #444; font-family: monospace; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        label { font-size: 14px; color: #aaa; }
    </style>
</head>
<body>
    <h2>⚡ Zalo War Tool ⚡</h2>
    
    <div class="box">
        <h3>1. Kết nối Zalo</h3>
        <label>IMEI</label>
        <input type="text" id="imei" placeholder="Nhập IMEI">
        <label>Cookie</label>
        <input type="text" id="cookie" placeholder="Nhập Cookie">
        <button onclick="login()">Kết nối</button>
    </div>

    <div class="box">
        <h3>2. Chọn Box (Nhóm)</h3>
        <button onclick="fetchGroups()">Tải danh sách nhóm</button>
        <select id="group_id"></select>
    </div>

    <div class="box">
        <h3>3. Chức năng</h3>
        <div class="grid">
            <div>
                <label>Nội dung tin nhắn (Text)</label>
                <textarea id="msg_text" rows="2"></textarea>
                <button onclick="startAction('msg')">Spam Tin Nhắn</button>
            </div>
            <div>
                <label>Tên mới (Đổi tên nhóm)</label>
                <input type="text" id="rename_text">
                <button onclick="startAction('rename')">Spam Đổi Tên</button>
            </div>
        </div>
        <div style="margin-top: 10px;">
            <label>Up File Ngôn (.txt)</label>
            <input type="file" id="file_input" accept=".txt">
            <button onclick="startAction('file')">Spam Theo File</button>
        </div>
        <div style="margin-top: 10px;">
            <label>Spam Vote (Câu hỏi)</label>
            <input type="text" id="vote_text">
            <button onclick="startAction('vote')">Spam Tạo Vote</button>
        </div>
        <button class="stop" style="margin-top: 15px;" onclick="stopBot()">DỪNG KHẨN CẤP</button>
    </div>

    <div class="box">
        <h3>Logs</h3>
        <pre id="logs"></pre>
    </div>

    <script>
        async function login() {
            const imei = document.getElementById('imei').value;
            const cookie = document.getElementById('cookie').value;
            const res = await fetch('/api/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({imei, cookie}) });
            alert(await res.text());
        }
        async function fetchGroups() {
            const res = await fetch('/api/groups');
            const data = await res.json();
            const sel = document.getElementById('group_id');
            sel.innerHTML = '';
            if(data.length === 0) sel.innerHTML = '<option>Chưa login hoặc không có nhóm</option>';
            data.forEach(g => { sel.innerHTML += `<option value="${g.id}">${g.name}</option>`; });
        }
        async function startAction(type) {
            const gid = document.getElementById('group_id').value;
            if (!gid) return alert("Chưa chọn nhóm!");
            
            if (type === 'file') {
                const fileInput = document.getElementById('file_input');
                if (!fileInput.files.length) return alert("Chưa chọn file!");
                const formData = new FormData();
                formData.append('gid', gid);
                formData.append('file', fileInput.files[0]);
                const res = await fetch('/api/start_file', { method: 'POST', body: formData });
                alert(await res.text());
            } else {
                let text = "";
                if (type === 'msg') text = document.getElementById('msg_text').value;
                if (type === 'rename') text = document.getElementById('rename_text').value;
                if (type === 'vote') text = document.getElementById('vote_text').value;
                
                const res = await fetch('/api/start', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({gid, text, type}) });
                alert(await res.text());
            }
        }
        async function stopBot() {
            const res = await fetch('/api/stop'); alert(await res.text());
        }
        setInterval(async () => {
            const res = await fetch('/api/logs');
            document.getElementById('logs').innerText = await res.text();
        }, 1500);
    </script>
</body>
</html>
"""

@app.route('/')
def home(): return render_template_string(HTML)

@app.route('/api/login', methods=['POST'])
def api_login():
    global bot_client
    data = request.json
    try:
        cookies = parse_cookie_string(data['cookie'])
        bot_client = ZaloWarClient(data['imei'], cookies)
        return "Kết nối Zalo thành công!"
    except Exception as e:
        return f"Lỗi kết nối: {e}"

@app.route('/api/groups')
def api_groups():
    if not bot_client: return jsonify([])
    return jsonify(bot_client.fetch_groups())

@app.route('/api/start', methods=['POST'])
def api_start():
    if not bot_client: return "Chưa kết nối Zalo!"
    if bot_client.running.is_set(): return "Bot đang chạy, hãy bấm Dừng!"
    
    data = request.json
    gid, text, typ = data['gid'], data['text'], data['type']
    
    def run():
        bot_client.running.set()
        if typ == 'msg':
            while bot_client.running.is_set():
                bot_client.send_to_group(gid, text, [], False, False, "40", False, False)
                time.sleep(2)
        elif typ == 'rename':
            while bot_client.running.is_set():
                try:
                    bot_client.rate_limiter.wait()
                    # Gọi thẳng API đổi tên
                    import requests
                    payload = {"grid": str(gid), "name": text, "imei": bot_client._imei}
                    res = requests.get("https://tt-group-wpa.chat.zalo.me/api/group/update", params={"zpw_ver": "233", "zpw_type": "30", "params": json.dumps(payload)}, cookies=bot_client._cookies)
                    if res.json().get("error_code") == 0: web_rprint(f"Đã đổi tên: {text}")
                except Exception as e: web_rprint(f"Lỗi đổi tên: {e}")
                time.sleep(5)
        elif typ == 'vote':
            while bot_client.running.is_set():
                try:
                    bot_client.rate_limiter.wait()
                    import requests
                    payload = {"grid": str(gid), "question": text, "options": json.dumps([{"content": "Có"}, {"content": "Không"}]), "imei": bot_client._imei}
                    res = requests.get("https://tt-group-wpa.chat.zalo.me/api/group/poll/create", params={"zpw_ver": "233", "zpw_type": "30", "params": json.dumps(payload)}, cookies=bot_client._cookies)
                    if res.json().get("error_code") == 0: web_rprint(f"Đã tạo vote: {text}")
                except Exception as e: web_rprint(f"Lỗi vote: {e}")
                time.sleep(5)
    threading.Thread(target=run, daemon=True).start()
    return "Đã bắt đầu!"

@app.route('/api/start_file', methods=['POST'])
def api_start_file():
    if not bot_client: return "Chưa kết nối Zalo!"
    if bot_client.running.is_set(): return "Bot đang chạy, hãy bấm Dừng!"
    
    gid = request.form.get('gid')
    file = request.files.get('file')
    if not file: return "Lỗi file!"
    
    lines = file.read().decode('utf-8').splitlines()
    lines = [l.strip() for l in lines if l.strip()]
    
    def run():
        bot_client.running.set()
        for line in lines:
            if not bot_client.running.is_set(): break
            bot_client.send_to_group(gid, line, [], False, False, "40", False, False)
            time.sleep(2)
    threading.Thread(target=run, daemon=True).start()
    return f"Đã bắt đầu spam {len(lines)} dòng!"

@app.route('/api/stop')
def api_stop():
    if bot_client: bot_client.running.clear()
    return "Đã dừng khẩn cấp!"

@app.route('/api/logs')
def api_logs():
    return "\n".join(logs_list[-50:])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)