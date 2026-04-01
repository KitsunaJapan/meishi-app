from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import anthropic
import requests
import json
import re
import os

app = Flask(__name__)
CORS(app)

# 環境変数から取得（Renderの環境変数に設定する）
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
APP_PASSWORD       = os.environ.get("APP_PASSWORD", "password123")  # ← デフォルトは変更してください
app.secret_key     = os.environ.get("SECRET_KEY", "change-this-secret-key")


def check_auth():
    """セッションで認証済みか確認"""
    return session.get("authenticated") is True


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if data.get("password") == APP_PASSWORD:
        session["authenticated"] = True
        return jsonify({"success": True})
    return jsonify({"error": "パスワードが違います"}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/extract_batch", methods=["POST"])
def extract_batch():
    if not check_auth():
        return jsonify({"error": "認証が必要です"}), 401

    data = request.json
    images = data.get("images", [])

    if not images:
        return jsonify({"error": "画像がありません"}), 400

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    content = []
    for i, img in enumerate(images):
        content.append({"type": "text", "text": f"【名刺 {i+1}枚目】"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.get("media_type", "image/jpeg"),
                "data": img["image_b64"]
            }
        })

    content.append({
        "type": "text",
        "text": f"""上記{len(images)}枚の名刺画像それぞれから情報を抽出してください。
必ず以下の形式のJSONのみを返してください。マークダウンのコードブロックは不要です。

{{
  "results": [
    {{
      "company": "会社名",
      "department": "部署名",
      "title": "役職",
      "name": "氏名（フルネーム）",
      "phone": "電話番号",
      "mobile": "携帯番号",
      "fax": "FAX番号",
      "email": "メールアドレス",
      "address": "住所（郵便番号含む）",
      "url": "URLまたはウェブサイト"
    }}
  ]
}}

resultsの配列は名刺の枚数分（{len(images)}件）入れてください。値がない場合は空文字にしてください。"""
    })

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300 * len(images),
        messages=[{"role": "user", "content": content}]
    )

    text = message.content[0].text.strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return jsonify({"error": "レスポンスのパースに失敗しました", "raw": text}), 500

    try:
        result = json.loads(match.group())
        results = result.get("results", [])
        while len(results) < len(images):
            results.append({k: "" for k in ["company","department","title","name","phone","mobile","fax","email","address","url"]})
        return jsonify({"results": results})
    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSONパースエラー: {str(e)}", "raw": text}), 500


@app.route("/write_sheet_batch", methods=["POST"])
def write_sheet_batch():
    if not check_auth():
        return jsonify({"error": "認証が必要です"}), 401

    data = request.json
    token    = data.get("token")
    sheet_id = data.get("sheet_id")
    range_   = data.get("range")
    rows     = data.get("rows", [])

    if not rows:
        return jsonify({"error": "データがありません"}), 400

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/"
        f"{requests.utils.quote(range_, safe='')}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    res = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"values": rows}
    )

    if not res.ok:
        return jsonify({"error": res.json().get("error", {}).get("message", "書き込みエラー")}), 500

    return jsonify({"success": True, "written": len(rows)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
