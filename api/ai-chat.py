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
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are BudgetMind AI, a friendly personal finance assistant."},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.7
        )

        ai_reply = response.choices[0].message.content.strip()

    except Exception as e:
        print("AI Chat error:", e)
        ai_reply = "⚠️ I couldn't reach the AI service right now."

    return jsonify({"reply": ai_reply})
