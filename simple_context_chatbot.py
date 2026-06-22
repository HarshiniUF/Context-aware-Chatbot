"""
Simple context-aware agricultural chatbot: uses only location, crop, and today's date.
Uses NaviGator API key from .env (same as main project).
"""
import os
from datetime import datetime, timezone
from langchain_core.prompts import ChatPromptTemplate
from wsp_config import DEFAULT_LOCATION_NAME, extract_crop_and_date_json, get_llm

# Minimal prompt template
SIMPLE_PROMPT = ChatPromptTemplate.from_template("""
You are a helpful agricultural assistant for farmers.
You will answer the user's question using only the following context:

 Location: {location}
 Crop: {crop}
 Date: {context_date}

IMPORTANT: Your answer must not exceed 250 words. Aim for 200-250 words if the topic requires detail, but shorter answers are fine if appropriate. Never go above 250 words.

FARMER'S QUESTION: "{user_question}"

Your answer must be in well-structured, crisp paragraphs (not bullet points). Be clear, concise, and directly address the question, using only the context above. Do not reference unavailable data (like soil or weather). If the question cannot be answered with this context, politely explain what is missing.
""")

def simple_chatbot_answer(user_question: str, location: str, crop: str, context_date: str) -> str:
    llm = get_llm()
    result = llm.invoke(SIMPLE_PROMPT.format_messages(
        location=location,
        crop=crop,
        context_date=context_date,
        user_question=user_question,
    ))
    return result.content.strip()

if __name__ == "__main__":
    print("=" * 60)
    print("  Minimal Agricultural Chatbot (Location, Crop, Date only)")
    print("=" * 60)
    location = DEFAULT_LOCATION_NAME
    print(f"Location: {location}")
    while True:
        user_question = input("\n🌾 Your question: ").strip()
        if user_question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        extraction = extract_crop_and_date_json(user_question)
        crop = extraction["extracted_crop"]
        context_date = extraction["context_date"]
        date_source = extraction["date_source"]
        if crop:
            print(f"📌 Detected crop: {crop}")
        else:
            print("⚠️  I don't see a specific crop mentioned in your question.")
            print("   Could you please specify which crop you're asking about?")
            print("   (e.g., maize, wheat, potato, beans, sesame, tomato, etc.)")
            crop_input = input("\n🌾 Which crop? ").strip()
            if crop_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break
            # Re-extract using the crop input
            extraction2 = extract_crop_and_date_json(crop_input)
            crop = extraction2["extracted_crop"] if extraction2["extracted_crop"] else crop_input.capitalize()
            print(f"📌 Got it! Working with {crop}...")
        print(f"🗓️  Context date: {context_date} (source: {date_source})")
        print(f"📝 Extraction JSON: {extraction}")
        answer = simple_chatbot_answer(user_question, location, crop, context_date)
        print("\n" + answer + "\n")
