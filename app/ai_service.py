import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List

from .pytorch_vision_engine import vision_engine

logger = logging.getLogger("uvicorn.error")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "llama-3.3-70b-versatile")


class AIService:
    def __init__(self):
        self.vision_engine = vision_engine
        self.client = None

        # Print AgriNex AI Initialization Logs
        logger.info("[AgriNex ML] Scanner ready (Powered by trained PyTorch ResNet18 V2-B model)")

        if GROQ_API_KEY:
            try:
                from groq import Groq
                self.client = Groq(api_key=GROQ_API_KEY)
                logger.info(f"[AgriNex AI] Chat provider: Groq")
                logger.info(f"[AgriNex AI] Chat model: {LLAMA_MODEL}")
            except Exception as e:
                logger.warning(f"[AgriNex AI Warning] Failed to initialize Groq client: {e}")
        else:
            logger.warning("[AgriNex AI Warning] GROQ_API_KEY not found in environment variables")

        logger.info("[AgriNex AI] Gemini disabled")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Disease Detection (MY TRAINED ML MODEL ONLY)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    async def detect_disease(self, image_input: str) -> Dict[str, Any]:
        """
        Runs plant disease detection using ONLY the trained PyTorch ML model.
        Does NOT send images to Gemini, Groq LLM, or any external generative API.
        """
        try:
            # Run local inference in threadpool to avoid blocking async event loop
            result = await asyncio.to_thread(self.vision_engine.predict, image_input)
            return result
        except Exception as e:
            logger.error(f"[AgriNex ML Error] Disease inference failed: {e}")
            raise e

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # AI Chat / Agronomist (LLAMA VIA GROQ ONLY)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    async def get_chat_response(self, message: str, history: list = [], scan_context: str = "") -> str:
        if not self.client:
            return self._fallback_chat_response(message)

        try:
            system_prompt = (
                "You are **AgriNex AI**, a world-class agricultural expert assistant. "
                "You provide detailed, practical, farmer-friendly advice on all aspects of agriculture.\n\n"
                "## Response Formatting Rules:\n"
                "- ALWAYS use **bold headings** with emojis for each section\n"
                "- Keep responses SHORT, PRACTICAL, and STRUCTURED\n"
                "- Use bullet points for lists\n"
                "- Include specific quantities, dosages, timings, and actionable steps\n"
                "- Be professional yet warm and encouraging\n\n"
                "## Response Structure (use relevant sections):\n"
                "🌱 **Crop Diagnosis** — identify the issue\n"
                "💧 **Irrigation Advice** — watering recommendations\n"
                "🧪 **Fertilizer Suggestion** — specific products and dosage\n"
                "⚠️ **Disease Prevention** — preventive measures\n"
                "🌿 **Organic Solution** — natural/organic alternatives\n"
                "📈 **Expected Yield Impact** — how this affects harvest\n"
                "💡 **Pro Tip** — expert bonus advice\n\n"
                "## Expertise Areas:\n"
                "Fertilizers, irrigation, pesticides, crop rotation, weather effects, "
                "government schemes (India), soil health, crop selection, organic farming, "
                "hydroponics, livestock, seed selection, harvest timing, market prices.\n\n"
                "## Language Support:\n"
                "- Auto-detect the language of the user's message. If the user writes in English, Tamil, Telugu, Malayalam, or Hindi, you MUST respond fluently in that SAME language.\n"
                "- Ensure high-quality translations, using English technical terms in parentheses if necessary.\n\n"
                "## Important:\n"
                "- Never say 'I don't know' — always provide the best available advice\n"
                "- Include specific product names, dosages, and timings when relevant\n"
                "- Mention seasonal considerations for Indian agriculture\n"
                "- Keep responses under 300 words unless detailed analysis is needed"
            )

            if scan_context:
                system_prompt += f"\n\n## Context (The user has recently diagnosed these crops):\n{scan_context}\nUse this context if the user asks questions about their scans or how to follow up on treatments."

            messages = [{"role": "system", "content": system_prompt}]

            # Add history (last 10 messages)
            for msg in history[-10:]:
                role = "assistant" if getattr(msg, "is_ai", False) else "user"
                msg_text = getattr(msg, "message", str(msg))
                messages.append({"role": role, "content": msg_text})

            messages.append({"role": "user", "content": message})

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=LLAMA_MODEL,
                    messages=messages,
                    temperature=0.6,
                    max_tokens=1024,
                    top_p=0.9,
                ),
                timeout=20.0
            )

            result = response.choices[0].message.content
            return self._enhance_formatting(result)

        except asyncio.TimeoutError:
            logger.error("[AgriNex AI Error] Chat Llama timeout after 20s")
            return self._fallback_chat_response(message)
        except Exception as e:
            logger.error(f"[AgriNex AI Error] Groq Llama Chat Error: {e}")
            return self._fallback_chat_response(message)

    def _enhance_formatting(self, text: str) -> str:
        """Ensure AI responses have proper bold formatting."""
        if not text:
            return text

        replacements = {
            "Crop Diagnosis:": "🌱 **Crop Diagnosis**",
            "Diagnosis:": "🌱 **Crop Diagnosis**",
            "Irrigation Advice:": "💧 **Irrigation Advice**",
            "Irrigation:": "💧 **Irrigation Advice**",
            "Watering:": "💧 **Irrigation Advice**",
            "Fertilizer Suggestion:": "🧪 **Fertilizer Suggestion**",
            "Fertilizer:": "🧪 **Fertilizer Suggestion**",
            "Fertilizers:": "🧪 **Fertilizer Suggestion**",
            "Disease Prevention:": "⚠️ **Disease Prevention**",
            "Prevention:": "⚠️ **Disease Prevention**",
            "Organic Solution:": "🌿 **Organic Solution**",
            "Organic Treatment:": "🌿 **Organic Solution**",
            "Treatment:": "💊 **Treatment**",
            "Symptoms:": "🔍 **Symptoms**",
            "Causes:": "📋 **Causes**",
            "Expected Yield Impact:": "📈 **Expected Yield Impact**",
            "Yield Impact:": "📈 **Expected Yield Impact**",
            "Pro Tip:": "💡 **Pro Tip**",
            "Tip:": "💡 **Pro Tip**",
            "Recommendation:": "✅ **Recommendation**",
            "Recommendations:": "✅ **Recommendations**",
            "Pesticide:": "🧴 **Pesticide Recommendation**",
            "Recovery:": "🔄 **Recovery Plan**",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        return text

    def _fallback_chat_response(self, message: str) -> str:
        """Provide intelligent fallback responses when Groq API is unavailable."""
        msg = message.lower()

        if any(w in msg for w in ['blight', 'disease', 'fungus', 'infection', 'rust']):
            return (
                "🌱 **Crop Diagnosis**\n"
                "Based on your description, this could be a fungal infection. "
                "Here's what I recommend:\n\n"
                "💊 **Treatment**\n"
                "- Apply Mancozeb 75% WP at 2g/liter\n"
                "- Spray early morning for best absorption\n"
                "- Repeat every 7-10 days\n\n"
                "🌿 **Organic Solution**\n"
                "- Neem oil spray (2%) as preventive\n"
                "- Copper-based fungicide (Bordeaux mixture)\n\n"
                "💡 **Pro Tip**\n"
                "Remove and destroy infected leaves immediately to prevent spread."
            )
        elif any(w in msg for w in ['fertilizer', 'nutrient', 'npk', 'growth']):
            return (
                "🧪 **Fertilizer Suggestion**\n"
                "For optimal growth, use a balanced approach:\n\n"
                "- **Nitrogen (N)**: Urea 46% — 50kg/acre for leafy growth\n"
                "- **Phosphorus (P)**: DAP — 25kg/acre for root development\n"
                "- **Potassium (K)**: MOP — 25kg/acre for fruit/grain quality\n\n"
                "💧 **Irrigation Advice**\n"
                "Water immediately after fertilizer application. Use drip irrigation for 30% better absorption.\n\n"
                "💡 **Pro Tip**\n"
                "Do a soil test every season to adjust nutrient ratios. Contact your local agriculture office for free testing."
            )
        elif any(w in msg for w in ['water', 'irrigation', 'drip', 'sprinkler']):
            return (
                "💧 **Irrigation Advice**\n"
                "Proper watering is critical for crop health:\n\n"
                "- **Drip irrigation**: Most efficient, saves 40-60% water\n"
                "- **Morning watering**: 6-9 AM is optimal\n"
                "- **Frequency**: Depends on soil type and crop stage\n\n"
                "📈 **Expected Yield Impact**\n"
                "Proper irrigation can increase yields by 30-50%.\n\n"
                "💡 **Pro Tip**\n"
                "Check soil moisture at 6-inch depth. If dry, water immediately."
            )
        else:
            return (
                "🌱 **AgriNex AI Assistant**\n"
                "I'm here to help with all your farming needs! I can assist with:\n\n"
                "- 🔬 Crop disease diagnosis\n"
                "- 🧪 Fertilizer recommendations\n"
                "- 💧 Irrigation planning\n"
                "- 🌿 Organic farming tips\n"
                "- 📊 Yield optimization\n"
                "- 🛡️ Pest control strategies\n\n"
                "💡 **Pro Tip**\n"
                "For best results, describe your crop type, growth stage, and specific symptoms you're observing."
            )


ai_service = AIService()
