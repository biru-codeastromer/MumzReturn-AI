from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from src.schema import ClassificationResult

BASE_DIR = Path(__file__).resolve().parents[1]
PROMPT_PATH = BASE_DIR / "prompts" / "system_prompt.txt"
MODEL_NAME = "meta-llama/llama-3.3-70b-instruct:free"
HEALTH_MODEL_NAME = "llama-3.3-70b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

load_dotenv(BASE_DIR / ".env")


@dataclass
class ClassifierRun:
    result: ClassificationResult
    schema_valid: bool
    used_fallback: bool
    raw_response: Optional[str] = None
    error: Optional[str] = None


class ReturnReasonClassifier:
    def __init__(self, api_key: Optional[str] = None, prompt_path: Path = PROMPT_PATH) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.fallback_mode = not bool(self.api_key)
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def classify(self, text: str, language: str = "auto") -> ClassificationResult:
        return self.classify_with_metadata(text=text, language=language).result

    def classify_with_metadata(self, text: str, language: str = "auto") -> ClassifierRun:
        if not text.strip():
            return self._uncertain_run(
                reason="Empty input",
                detail_en="There is no return reason to classify.",
                detail_ar="ما فيه سبب إرجاع واضح عشان يتم تصنيفه.",
                confidence=0.1,
                used_fallback=True,
            )

        if self.fallback_mode:
            return self._classify_with_fallback(text=text)

        try:
            llm_run = self._classify_with_llm(text=text, language=language)
            if llm_run.schema_valid:
                return llm_run
            return llm_run
        except requests.RequestException as exc:
            fallback_run = self._classify_with_fallback(text=text)
            fallback_run.error = f"OpenRouter request failed: {exc}"
            return fallback_run
        except Exception as exc:  # pragma: no cover - defensive fallback
            fallback_run = self._classify_with_fallback(text=text)
            fallback_run.error = f"Unexpected LLM error: {exc}"
            return fallback_run

    def _classify_with_llm(self, text: str, language: str) -> ClassifierRun:
        payload = {
            "model": MODEL_NAME,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "language_hint": language,
                            "customer_text": text,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mumzreturn.local",
            "X-Title": "MumzReturn AI",
        }
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        content = self._coerce_message_content(response_json)
        return self._validate_response_payload(
            payload_text=content,
            used_fallback=False,
        )

    def _classify_with_fallback(self, text: str) -> ClassifierRun:
        normalized = self._normalize(text)

        uncertain_signal = self._detect_uncertain_signal(normalized)
        if uncertain_signal is not None:
            return self._uncertain_run(
                reason=uncertain_signal,
                detail_en=self._uncertain_reasoning_en(uncertain_signal),
                detail_ar=self._uncertain_reasoning_ar(uncertain_signal),
                confidence=0.18 if uncertain_signal != "Empty input" else 0.1,
                used_fallback=True,
            )

        category_matches = {
            "ESCALATE": self._collect_matches(normalized, ESCALATE_PATTERNS),
            "REFUND": self._collect_matches(normalized, REFUND_PATTERNS),
            "EXCHANGE": self._collect_matches(normalized, EXCHANGE_PATTERNS),
            "STORE_CREDIT": self._collect_matches(normalized, STORE_CREDIT_PATTERNS),
        }

        present_categories = {key: value for key, value in category_matches.items() if value}
        if not present_categories:
            return self._uncertain_run(
                reason="Insufficient information to classify safely",
                detail_en="The message does not clearly describe damage, a variant swap, change of mind, or a safety issue.",
                detail_ar="الرسالة ما توضح بشكل كافي إذا كانت المشكلة تلف أو تبديل أو تغيير رأي أو ملاحظة سلامة.",
                confidence=0.22,
                used_fallback=True,
            )

        # Safety and fraud language should always override lower-risk routes.
        if present_categories.get("ESCALATE"):
            top_matches = present_categories["ESCALATE"]
            evidence_en, evidence_ar = top_matches[0]
            result = ClassificationResult(
                action="ESCALATE",
                confidence=0.92,
                reasoning_en=ACTION_REASONING_EN["ESCALATE"].format(evidence=evidence_en),
                reasoning_ar=ACTION_REASONING_AR["ESCALATE"].format(evidence=evidence_ar),
                suggested_reply_en=ACTION_REPLY_EN["ESCALATE"],
                suggested_reply_ar=ACTION_REPLY_AR["ESCALATE"],
                is_uncertain=False,
                uncertainty_reason=None,
            )
            return ClassifierRun(result=result, schema_valid=True, used_fallback=True)

        scored = sorted(
            (
                (action, len(matches), matches)
                for action, matches in present_categories.items()
            ),
            key=lambda item: (item[1], ACTION_PRIORITY[item[0]]),
            reverse=True,
        )

        top_action, top_score, top_matches = scored[0]
        if len(scored) > 1 and scored[0][1] == scored[1][1]:
            return self._uncertain_run(
                reason="Conflicting signals across multiple actions",
                detail_en="The message points to more than one return path and needs a clearer description before routing.",
                detail_ar="الرسالة فيها مؤشرات لأكثر من مسار، وتحتاج وصف أوضح قبل توجيهها بشكل صحيح.",
                confidence=0.3,
                used_fallback=True,
            )

        confidence = min(0.8 + (0.06 * min(top_score, 3)), 0.98)
        if top_action == "ESCALATE":
            confidence = max(confidence, 0.92)

        evidence_en, evidence_ar = top_matches[0]
        reasoning_en = ACTION_REASONING_EN[top_action].format(evidence=evidence_en)
        reasoning_ar = ACTION_REASONING_AR[top_action].format(evidence=evidence_ar)

        result = ClassificationResult(
            action=top_action,
            confidence=round(confidence, 2),
            reasoning_en=reasoning_en,
            reasoning_ar=reasoning_ar,
            suggested_reply_en=ACTION_REPLY_EN[top_action],
            suggested_reply_ar=ACTION_REPLY_AR[top_action],
            is_uncertain=False,
            uncertainty_reason=None,
        )
        return ClassifierRun(result=result, schema_valid=True, used_fallback=True)

    def _validate_response_payload(self, payload_text: str, used_fallback: bool) -> ClassifierRun:
        try:
            payload = json.loads(self._extract_json_object(payload_text))
            result = ClassificationResult.model_validate(payload)
            if result.is_uncertain:
                result.action = None
            return ClassifierRun(
                result=result,
                schema_valid=True,
                used_fallback=used_fallback,
                raw_response=payload_text,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            uncertain = self._uncertain_run(
                reason="Model output failed schema validation",
                detail_en="The model response could not be validated safely, so the result is marked uncertain.",
                detail_ar="تعذر التحقق من استجابة النموذج بشكل آمن، لذلك تم وسم النتيجة كحالة غير مؤكدة.",
                confidence=0.0,
                used_fallback=used_fallback,
            )
            uncertain.schema_valid = False
            uncertain.raw_response = payload_text
            uncertain.error = str(exc)
            return uncertain

    @staticmethod
    def _coerce_message_content(response_json: dict[str, Any]) -> str:
        content = response_json["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts)
        raise ValueError("Unsupported content format from OpenRouter")

    @staticmethod
    def _extract_json_object(content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in model output")
        return cleaned[start : end + 1]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _detect_uncertain_signal(self, normalized: str) -> Optional[str]:
        if not normalized:
            return "Empty input"

        if re.search(r"\b(drop|select|delete|insert|union|table|alter)\b", normalized):
            return "Adversarial or non-customer text"

        if normalized in GENERIC_VAGUE_INPUTS:
            return "Too vague to classify"

        if len(normalized) <= 3:
            return "Too vague to classify"

        if re.search(r"\b(asdf|qwer|zzzz|lorem ipsum)\b", normalized):
            return "Gibberish or non-meaningful text"

        if self._looks_like_gibberish(normalized):
            return "Gibberish or non-meaningful text"

        if any(re.search(pattern, normalized) for pattern in OUT_OF_SCOPE_PATTERNS):
            return "Unrelated or insufficient information"

        return None

    @staticmethod
    def _looks_like_gibberish(normalized: str) -> bool:
        if re.search(r"[a-z]", normalized):
            tokens = re.findall(r"[a-z]+", normalized)
            if tokens and all(token in {"asdf", "qwer", "zzzz", "test"} for token in tokens):
                return True
            if tokens and len(tokens) <= 2 and all(len(token) > 3 and not re.search(r"[aeiouy]", token) for token in tokens):
                return True
        return False

    @staticmethod
    def _collect_matches(normalized: str, patterns: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
        matches: list[tuple[str, str]] = []
        for pattern, label_en, label_ar in patterns:
            if re.search(pattern, normalized):
                matches.append((label_en, label_ar))
        return matches

    def _uncertain_run(
        self,
        reason: str,
        detail_en: str,
        detail_ar: str,
        confidence: float,
        used_fallback: bool,
    ) -> ClassifierRun:
        result = ClassificationResult(
            action=None,
            confidence=round(confidence, 2),
            reasoning_en=detail_en,
            reasoning_ar=detail_ar,
            suggested_reply_en="Please share the return issue itself in a bit more detail so I can classify it safely.",
            suggested_reply_ar="فضلاً شارك سبب الإرجاع نفسه بتفصيل بسيط أكثر عشان أقدر أصنفه بشكل آمن.",
            is_uncertain=True,
            uncertainty_reason=reason,
        )
        return ClassifierRun(result=result, schema_valid=True, used_fallback=used_fallback)

    @staticmethod
    def _uncertain_reasoning_en(reason: str) -> str:
        mapping = {
            "Empty input": "There is no return reason to classify.",
            "Adversarial or non-customer text": "The text does not look like a genuine customer return reason, so it should not be force-classified.",
            "Too vague to classify": "The message is too short or vague to distinguish between refund, exchange, store credit, or escalation.",
            "Gibberish or non-meaningful text": "The text does not contain a reliable customer issue to classify.",
            "Unrelated or insufficient information": "The message is about something other than a return reason, or it lacks the details needed to route it safely.",
        }
        return mapping.get(reason, "There is not enough information to classify this return safely.")

    @staticmethod
    def _uncertain_reasoning_ar(reason: str) -> str:
        mapping = {
            "Empty input": "ما فيه سبب إرجاع واضح عشان يتم تصنيفه.",
            "Adversarial or non-customer text": "النص ما يبدو كأنه سبب إرجاع حقيقي من عميل، لذلك ما ينفع ينصنف بشكل قسري.",
            "Too vague to classify": "الرسالة قصيرة أو عامة زيادة، وما تكفي للتمييز بين استرجاع أو استبدال أو رصيد متجر أو تصعيد.",
            "Gibberish or non-meaningful text": "النص ما يحتوي على مشكلة واضحة وموثوقة عشان يتم تصنيفها.",
            "Unrelated or insufficient information": "الرسالة تتكلم عن موضوع مختلف أو ما فيها تفاصيل كافية لتوجيهها بشكل آمن.",
        }
        return mapping.get(reason, "ما فيه معلومات كافية لتصنيف هذه الحالة بشكل آمن.")


ACTION_PRIORITY = {
    "ESCALATE": 4,
    "REFUND": 3,
    "EXCHANGE": 2,
    "STORE_CREDIT": 1,
}

GENERIC_VAGUE_INPUTS = {
    "bad",
    "no",
    "need help",
    "help",
    "issue with order",
    "issue",
    "problem",
    "wrong",
    "مو مناسب",
    "مشكلة",
    "سيء",
}

OUT_OF_SCOPE_PATTERNS = [
    r"\bwhen will\b.*\barrive\b",
    r"\bwhere is my order\b",
    r"\btrack\b.*\border\b",
    r"\border status\b",
    r"\bdelivery time\b",
    r"كيف أضيف عنوان",
    r"وين طلبي",
    r"متى يوصل",
    r"كيف أتتبع",
]

REFUND_PATTERNS = [
    (
        r"\bbroken\b|\bcracked\b|\bdamaged\b|\bbent\b",
        "damage on arrival",
        "وجود تلف عند وصول المنتج",
    ),
    (
        r"\bdefective\b|\bfaulty\b|\bwon't turn on\b|\bnot working\b|خربان|معطوب",
        "a defective or non-working item",
        "وجود عطل أو أن المنتج لا يعمل",
    ),
    (
        r"\bwrong item\b|\breceived .* instead\b|منتج غير|وصلني غير",
        "the wrong item being sent",
        "وصول منتج غير المطلوب",
    ),
    (
        r"\bnever arrived\b|\bdid not arrive\b|\bnothing actually arrived\b|\bnothing arrived\b|ما وصلني|لم يصل",
        "the item never arriving",
        "عدم وصول الطلب",
    ),
    (
        r"مكسور|كسر|متضرر|تالف",
        "damage on arrival",
        "وجود تلف عند وصول المنتج",
    ),
]

EXCHANGE_PATTERNS = [
    (
        r"\btoo small\b|\btoo big\b|\bone size up\b|\bsize \d+\b|مقاس",
        "a request for a different size",
        "وجود طلب لمقاس مختلف",
    ),
    (
        r"\bwrong color\b|\bcolor\b|\bpink\b|\bbeige\b|\bgray\b|\bgrey\b|لون|الرمادي|الوردي|البيج",
        "a request for a different color",
        "وجود طلب للون مختلف",
    ),
    (
        r"\bvariant\b|\bversion\b|\bglass version\b|\b6-12 months\b|بدل",
        "a request for a different variant",
        "وجود طلب لنسخة أو نوع مختلف",
    ),
    (
        r"\bexchange\b|\bswap\b|أبدل|أبغى أبدل",
        "an explicit request for an exchange",
        "وجود طلب صريح للاستبدال",
    ),
]

STORE_CREDIT_PATTERNS = [
    (
        r"\bchanged my mind\b|غيرت رأيي",
        "a change of mind",
        "أن العميل غيّر رأيه",
    ),
    (
        r"\baccidentally bought two\b|\bduplicate\b|\bordered by mistake\b|بالغلط|مرتين",
        "an accidental or duplicate order",
        "أن الطلب تم بالخطأ أو بشكل مكرر",
    ),
    (
        r"\bdon't need\b|\bno longer need\b|\bgift list changed\b|ما أحتاج|ما عاد أحتاج|هدية",
        "the item no longer being needed",
        "أن المنتج لم يعد مطلوبًا",
    ),
    (
        r"\bkeep credit\b|\bcredit for later\b",
        "a preference for store credit",
        "وجود تفضيل لرصيد المتجر",
    ),
]

ESCALATE_PATTERNS = [
    (
        r"\brash\b|\ballergic\b|\ballergy\b|\bvomit\b|\bmedical\b|حساسية|طفح|استفرغ",
        "a medical or allergic reaction",
        "وجود تفاعل تحسسي أو حالة طبية",
    ),
    (
        r"\bcut my child\b|\bsharp edge\b|\binjury\b|\bhurt my baby\b|\balmost got hurt\b|\bgot hurt\b|\bpiece is sharp\b|جرحت|انجرح|قطعة حادة",
        "an injury or safety incident",
        "وجود إصابة أو حادثة تتعلق بالسلامة",
    ),
    (
        r"\bfraud\b|\bcharged twice\b|\bunauthorized\b|احتيال|خصم",
        "possible fraud or a payment issue",
        "احتمال وجود احتيال أو مشكلة دفع",
    ),
    (
        r"\bsafety issue\b|\bchoking\b|\bunsafe\b|سلامة|خطر",
        "a safety concern",
        "وجود ملاحظة تتعلق بالسلامة",
    ),
]

ACTION_REASONING_EN = {
    "REFUND": "The message points to {evidence}, which fits the refund rules.",
    "EXCHANGE": "The message points to {evidence}, which fits the exchange rules.",
    "STORE_CREDIT": "The message points to {evidence}, which fits the store credit rules.",
    "ESCALATE": "The message points to {evidence}, so the case should be escalated instead of auto-routed.",
}

ACTION_REASONING_AR = {
    "REFUND": "الرسالة تشير إلى {evidence}، وهذا يطابق قواعد الاسترجاع المالي.",
    "EXCHANGE": "الرسالة تشير إلى {evidence}، وهذا يطابق قواعد الاستبدال.",
    "STORE_CREDIT": "الرسالة تشير إلى {evidence}، وهذا يطابق حالات رصيد المتجر.",
    "ESCALATE": "الرسالة تشير إلى {evidence}، لذلك لازم تتحول للتصعيد بدل التوجيه التلقائي.",
}

ACTION_REPLY_EN = {
    "REFUND": "Thanks for explaining. This looks like a refund case based on the issue described. Please share any relevant photo or delivery detail so support can review the next step.",
    "EXCHANGE": "Thanks for the details. This looks like an exchange request. Please confirm the preferred size, color, or variant so support can guide you correctly.",
    "STORE_CREDIT": "Thanks for letting us know. This sounds like a store credit case based on the reason shared. Support can help you with the next step.",
    "ESCALATE": "I’m sorry to hear that. Because this may involve safety, health, injury, or fraud, the case should be reviewed by the support team as soon as possible.",
}

ACTION_REPLY_AR = {
    "REFUND": "شكرًا على التوضيح. هذي أقرب لحالة استرجاع مالي بحسب المشكلة المذكورة. إذا أمكن شارك صورة أو تفاصيل التوصيل عشان الدعم يراجع الخطوة التالية.",
    "EXCHANGE": "شكرًا على التفاصيل. هذي تبدو كحالة استبدال. أكّد المقاس أو اللون أو النسخة المطلوبة عشان الدعم يوجّهك بشكل صحيح.",
    "STORE_CREDIT": "شكرًا لإبلاغنا. هذي أقرب لحالة رصيد متجر بناءً على السبب المذكور. فريق الدعم يقدر يساعدك بالخطوة التالية.",
    "ESCALATE": "آسفين على اللي صار. بما إن الحالة قد تتعلق بالسلامة أو الصحة أو إصابة أو احتيال، لازم يراجعها فريق الدعم بأسرع وقت ممكن.",
}
