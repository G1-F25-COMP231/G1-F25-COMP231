import os
from openai import OpenAI
from flask import request, jsonify
from app import app, login_required

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()

    if not user_msg:
        return jsonify({"reply": "Please type something to chat!"})

    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": "You are BudgetMind AI, a friendly personal finance assistant."
                },
                {
                    "role": "user",
                    "content": user_msg
                }
            ]
        )

        ai_reply = response.output_text   # <-- this is the correct field

    except Exception as e:
        print("AI Chat error:", e)
        return jsonify({
            "reply": "⚠️ I couldn't reach the AI service right now.",
            "error": str(e)
        }), 500

    return jsonify({"reply": ai_reply})
