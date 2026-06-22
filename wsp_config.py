#
# Unified crop and date extraction for both chatbot and config use:
# Use extract_crop_and_date_json(user_question) to get a JSON dict with:
#   {"extracted_crop": ..., "context_date": ..., "date_source": ...}
# This is reusable for both simple_context_chatbot.py and any WSP config logic.
def extract_crop_and_date_json(user_question: str) -> dict:
    """
    Extracts crop and date from user question and returns a JSON dict as specified:
    {
      "extracted_crop": "string or null",
      "context_date": "YYYY-MM-DD",
      "date_source": "user_explicit" | "default_today"
    }
    """
    extracted_crop = extract_crop_from_question(user_question)
    extracted_date = extract_date_from_question(user_question)
    # Use shared today definition so the default date matches operator expectations
    today_str = get_today_str()
    if extracted_date is not None:
        context_date = extracted_date.strftime("%Y-%m-%d")
        date_source = "user_explicit"
    else:
        context_date = today_str
        date_source = "default_today"
    return {
        "extracted_crop": extracted_crop if extracted_crop else None,
        "context_date": context_date,
        "date_source": date_source
    }
# """
# =============================================================
# SHARED CONFIGURATION — NaviGator API + Unified LLM Prompt
# Used by all 5 WSP prototypes

# FORECAST TYPE CONFIGURATION:
# - DAILY_FORECAST_WSP: Provider for daily forecasts (default: openmeteo)
# - SEASONAL_FORECAST_WSP: Provider for seasonal forecasts (default: noaacpc)

# Change these settings to switch between different weather providers easily.
# =============================================================
# """

# import os
# from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
# from langchain_core.prompts import ChatPromptTemplate

# load_dotenv()

# import re
# from datetime import datetime, timezone
# from typing import Optional, Literal
# from pydantic import BaseModel, Field
# import json

# # ─────────────────────────────────────────────────────────────
# # DEFAULT LOCATION SETTINGS
# # ─────────────────────────────────────────────────────────────
# DEFAULT_LATITUDE = 1.0157             # Default: Kitale, Kenya
# DEFAULT_LONGITUDE = 34.9865         # Default: Kitale, Kenya
# DEFAULT_LOCATION_NAME = "Kitale, Kenya"

# # Testing different coordinates in Kenya for soil data:
# # Kitale center:     lat=1.0,   lon=34.96
# # Kitale research:   lat=0.98,  lon=34.95
# # Cherangany:        lat=0.96,  lon=34.92
# # Kacheliba:         lat=1.15,  lon=35.05

# # ─────────────────────────────────────────────────────────────
# # CROP AND DATE EXTRACTION (Reusable for both chatbots)
# # ─────────────────────────────────────────────────────────────

# # ─── Allowed crops (normalized list) ───
# AllowedCrops = Literal[
#     'Maize', 'Rice', 'Wheat', 'Beans', 'Sorghum', 'Millet',
#     'Potato', 'Cassava', 'Sweet potato', 'Peanut', 'Chickpea',
#     'Lentil', 'Tomato', 'Onion', 'Cabbage', 'Sesame',
#     'Sunflower', 'Cotton', 'Soybean', 'Barley', 'Oats', 'Rye'
# ]

# # ─── Pydantic schema for LLM-based crop extraction ───
# class CropExtractionResult(BaseModel):
#     crop_found: bool = Field(description="True if an agricultural crop is explicitly or implicitly mentioned.")
#     crop_name: Optional[AllowedCrops] = Field(
#         default=None,
#         description="The standardized name of the crop. Must be normalized (e.g., 'groundnuts' -> 'Peanut', 'corn' -> 'Maize')."
#     )
#     confidence: str = Field(default="low", description="Confidence level: 'high', 'medium', or 'low'")

# def extract_crop_from_question(question: str) -> Optional[str]:
#     """
#     Extract crop name from user's question using LLM with structured output.
#     Handles synonyms, regional slang, typos, and context naturally.
#     Uses the NaviGator API (GPT-OSS-120B) via LangChain.
#     Falls back to simple pattern matching if LLM is unavailable.
#     """
#     try:
#         llm = get_llm()
        
#         # Create a prompt that guides the LLM to extract the crop
#         extraction_prompt = f"""You are an expert agricultural AI. Your job is to extract the primary crop being discussed in the user's question.

# Map regional synonyms accurately:
# - 'groundnuts', 'arachis', 'groundnut' → 'Peanut'
# - 'corn', 'maize' → 'Maize'
# - 'yam' → 'Sweet potato'
# - 'gram', 'chickpea' → 'Chickpea'
# - East African regional names → Standard names

# If no crop from the allowed list is mentioned, set crop_found to false.

# USER QUESTION: "{question}"

# Respond with a JSON object with these exact fields:
# - crop_found (boolean)
# - crop_name (one of: Maize, Rice, Wheat, Beans, Sorghum, Millet, Potato, Cassava, Sweet potato, Peanut, Chickpea, Lentil, Tomato, Onion, Cabbage, Sesame, Sunflower, Cotton, Soybean, Barley, Oats, Rye)
# - confidence (high, medium, or low)"""
        
#         # Call LLM
#         response = llm.invoke(extraction_prompt)
#         response_text = response.content.strip()
        
#         # Try to extract JSON from response
#         try:
#             # Handle markdown code blocks if LLM wraps response
#             if "```json" in response_text:
#                 response_text = response_text.split("```json")[1].split("```")[0].strip()
#             elif "```" in response_text:
#                 response_text = response_text.split("```")[1].split("```")[0].strip()
            
#             result_dict = json.loads(response_text)
#             result = CropExtractionResult(**result_dict)
            
#             if result.crop_found and result.crop_name:
#                 return result.crop_name
#             return None
#         except (json.JSONDecodeError, ValueError) as e:
#             # Fallback: try to extract crop name from response text
#             # if structured parsing fails
#             for crop in AllowedCrops.__args__:
#                 if crop.lower() in response_text.lower():
#                     return crop
#             return None
            
#     except Exception as e:
#         # Graceful fallback: use simple pattern matching if LLM is unavailable
#         # This ensures the chatbots keep working even if the API is down
#         return _extract_crop_fallback(question)


# def _extract_crop_fallback(question: str) -> Optional[str]:
#     """
#     Fallback crop extraction using simple pattern matching.
#     Used when LLM is unavailable or authentication fails.
#     """
#     crop_patterns = {
#         'Maize': [r'\bmaize\b', r'\bcorn\b'],
#         'Rice': [r'\brice\b'],
#         'Wheat': [r'\bwheat\b'],
#         'Beans': [r'\bbeans\b', r'\bbean\b'],
#         'Sorghum': [r'\bsorghum\b'],
#         'Millet': [r'\bmillet\b'],
#         'Potato': [r'\bpotato(?:es)?\b'],
#         'Cassava': [r'\bcassava\b'],
#         'Sweet potato': [r'\bsweet potato(?:es)?\b', r'\byam\b'],
#         'Peanut': [r'\bpeanut(?:s)?\b', r'\bgroundnut(?:s)?\b', r'\barachis\b'],
#         'Chickpea': [r'\bchickpea(?:s)?\b', r'\bgram\b'],
#         'Lentil': [r'\blentil(?:s)?\b'],
#         'Tomato': [r'\btomato(?:es)?\b'],
#         'Onion': [r'\bonion(?:s)?\b'],
#         'Cabbage': [r'\bcabbage\b'],
#         'Sesame': [r'\bsesame\b'],
#         'Sunflower': [r'\bsunflower\b'],
#         'Cotton': [r'\bcotton\b'],
#         'Soybean': [r'\bsoybean(?:s)?\b'],
#         'Barley': [r'\bbarley\b'],
#         'Oats': [r'\boats\b'],
#         'Rye': [r'\brye\b'],
#     }
    
#     question_lower = question.lower()
#     for crop_name, patterns in crop_patterns.items():
#         for pattern in patterns:
#             if re.search(pattern, question_lower):
#                 return crop_name
#     return None


# def extract_date_from_question(question: str) -> Optional[datetime]:
#     """
#     Extract date/timing context from user's question.
#     Looks for month references or seasonal phrases like 'middle of June'.
#     Returns datetime if found, else None.
#     """
#     question_lower = question.lower()
    
#     months = {
#         'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
#         'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
#         'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
#         'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
#     }
    
#     # First, look for timing words immediately before the month
#     timing_pattern = r'(?:(?:late|end|late|ending) )?(?:(?:beginning|start|early) )?(?:(?:mid|middle) )?\b(' + '|'.join(months.keys()) + r')\b'
    
#     # Also look for just the month without timing words in prefix
#     month_pattern = r'\b(' + '|'.join(months.keys()) + r')\b'
#     month_match = re.search(month_pattern, question_lower)
    
#     if month_match:
#         month_name = month_match.group(1)
#         month_num = months.get(month_name, None)
        
#         if month_num:
#             # Look for timing words BEFORE the month (in the previous 20 characters)
#             context_start = max(0, month_match.start() - 20)
#             context_before = question_lower[context_start:month_match.start()]
#             context_after = question_lower[month_match.end():month_match.end() + 20]
            
#             # Determine the day based on timing words
#             day = 15  # Default to mid-month
            
#             if re.search(r'\b(?:late|end|ending)\b', context_before):
#                 day = 25
#             elif re.search(r'\b(?:mid|middle)\b', context_before):
#                 day = 15
#             elif re.search(r'\b(?:beginning|start|early)\b', context_before):
#                 day = 5
#             else:
#                 # Check after the month too
#                 if re.search(r'\b(?:late|end|ending)\b', context_after):
#                     day = 25
#                 elif re.search(r'\b(?:mid|middle)\b', context_after):
#                     day = 15
#                 elif re.search(r'\b(?:beginning|start|early)\b', context_after):
#                     day = 5
#                 else:
#                     # Try to extract explicit day number
#                     day_match = re.search(r'\b(\d{1,2})\b', question)
#                     if day_match:
#                         try:
#                             day = int(day_match.group(1))
#                             # Validate day is reasonable
#                             if day < 1 or day > 31:
#                                 day = 15
#                         except ValueError:
#                             day = 15
            
#             year = datetime.now(timezone.utc).year
#             year_match = re.search(r'\b(20\d{2}|19\d{2})\b', question)
#             if year_match:
#                 year = int(year_match.group(1))
            
#             try:
#                 return datetime(year, month_num, day, tzinfo=timezone.utc)
#             except ValueError:
#                 return None
    
#     return None



"""
=============================================================
SHARED CONFIGURATION — NaviGator API + Unified LLM Prompt
Used by all 5 WSP prototypes

FORECAST TYPE CONFIGURATION:
- DAILY_FORECAST_WSP: Provider for daily forecasts (default: openmeteo)
- SEASONAL_FORECAST_WSP: Provider for seasonal forecasts (default: noaacpc)

Change these settings to switch between different weather providers easily.
=============================================================
"""

import os
import re
import json
from datetime import datetime, timezone
from typing import Optional, Literal
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

# Toggle whether 'today' should be calculated in UTC or using the system local time.
# By default we use local system time to match what operators see in their terminal.
# Set the environment variable USE_UTC_DATES=1 or true to force UTC behaviour.
USE_UTC_DATES = str(os.getenv("USE_UTC_DATES", "false")).lower() in ("1", "true", "yes")

def get_today_datetime():
    """Return 'today' as a datetime object. Respects USE_UTC_DATES toggle.

    - If USE_UTC_DATES is True, returns timezone-aware UTC now.
    - Otherwise returns local system time (naive datetime).
    """
    if USE_UTC_DATES:
        return datetime.now(timezone.utc)
    return datetime.now()


def get_today_str():
    """Return today's date string in ISO YYYY-MM-DD matching get_today_datetime()."""
    return get_today_datetime().strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────
# DEFAULT LOCATION SETTINGS
# ─────────────────────────────────────────────────────────────
DEFAULT_LATITUDE = 1.0157             # Default: Kitale, Kenya
DEFAULT_LONGITUDE = 34.9865         # Default: Kitale, Kenya
DEFAULT_LOCATION_NAME = "Kitale, Kenya"

# ─────────────────────────────────────────────────────────────
# LLM INSTANTIATION (Shared across all systems)
# ─────────────────────────────────────────────────────────────
def get_llm(temperature: float = 0.0):
    """
    Returns the shared ChatOpenAI instance. 
    Defaults to 0.0 for structured extraction tasks to preserve accuracy.
    """
    return ChatOpenAI(
        model="gpt-oss-120b",
        temperature=temperature,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_api_base="https://api.ai.it.ufl.edu/v1",
        default_headers={
            "Client-ID"    : os.getenv("CLIENT_ID"),
            "Client-Secret": os.getenv("CLIENT_SECRET"),
        }
    )

# ─────────────────────────────────────────────────────────────
# CROP AND DATE EXTRACTION (LLM-Powered / Structured)
# ─────────────────────────────────────────────────────────────

# Allowed crops (normalized list)
AllowedCrops = Literal[
    'Maize', 'Rice', 'Wheat', 'Beans', 'Sorghum', 'Millet',
    'Potato', 'Cassava', 'Sweet potato', 'Peanut', 'Chickpea',
    'Lentil', 'Tomato', 'Onion', 'Cabbage', 'Sesame',
    'Sunflower', 'Cotton', 'Soybean', 'Barley', 'Oats', 'Rye'
]

class CropExtractionResult(BaseModel):
    crop_found: bool = Field(description="True if an agricultural crop is explicitly or implicitly mentioned.")
    crop_name: Optional[AllowedCrops] = Field(
        default=None,
        description="The standardized name of the crop. Must be normalized (e.g., 'groundnuts' -> 'Peanut', 'corn' -> 'Maize')."
    )
    confidence: str = Field(default="low", description="Confidence level: 'high', 'medium', or 'low'")


class DateExtractionResult(BaseModel):
    time_mentioned: bool = Field(description="True if a specific timeframe, date, or season is explicitly or implicitly mentioned.")
    target_date_iso: str = Field(description="The calculated target date or start of the target period in YYYY-MM-DD format.")


def extract_crop_from_question(question: str) -> Optional[str]:
    """Extract crop name from user's question using LangChain's Structured Output."""
    try:
        llm = get_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(CropExtractionResult)
        extraction_prompt = f"""You are an expert agricultural AI. Your job is to extract the primary crop being discussed in the user's question.

        CRITICAL RULE: Even if the crop name is part of a regional geographic description or location identifier (e.g., 'Peanut Basin', 'Corn Belt'), 
        if it identifies what kind of grower they are or what they are planting, extract that crop!

        Map regional synonyms accurately:
        - 'groundnuts', 'arachis', 'groundnut', 'peanut grower' → 'Peanut'
        - 'corn', 'maize' → 'Maize'
        - 'yam' → 'Sweet potato'
        - 'gram', 'chickpea' → 'Chickpea'
        
        USER QUESTION: "{question}" """
        result = structured_llm.invoke(extraction_prompt)
        if result.crop_found and result.crop_name:
            return result.crop_name
        return None
    except Exception:
        return _extract_crop_fallback(question)


def extract_date_from_question(question: str) -> Optional[datetime]:
    """Extract date context from user's question.
  
    Strategy:
    1. Fast deterministic parsing for common patterns (e.g., "middle of June", "mid-June", "June 15th").
    2. If deterministic parsing fails, fall back to the LLM structured extractor as a last resort.

    Returns a timezone-aware datetime if a specific date or sub-month descriptor is found,
    otherwise returns None to indicate no explicit date was mentioned.
    """
    question_lower = question.lower()
    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y-%m-%d")
    current_year = today.year

    # Month name mapping
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
        'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    }

    # 1) Explicit day + month (e.g., '15 June', 'June 15th', 'June 15')
    day_month_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(months.keys()) + r")\b", question_lower)
    if not day_month_match:
        day_month_match = re.search(r"\b(" + "|".join(months.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", question_lower)
        if day_month_match:
            month_name = day_month_match.group(1)
            day = int(day_month_match.group(2))
            month_num = months.get(month_name.lower())
            year_match = re.search(r"\b(20\d{2}|19\d{2})\b", question)
            year = int(year_match.group(1)) if year_match else current_year
            try:
                return datetime(year, month_num, day, tzinfo=timezone.utc)
            except Exception:
                pass
    else:
        day = int(day_month_match.group(1))
        month_name = day_month_match.group(2)
        month_num = months.get(month_name.lower())
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", question)
        year = int(year_match.group(1)) if year_match else current_year
        try:
            return datetime(year, month_num, day, tzinfo=timezone.utc)
        except Exception:
            pass

    # 2) Relative sub-month phrases: 'beginning/mid/end of <month>' or 'mid-<month>'
    sub_month_pattern = re.search(r"\b(?:beginning|start|early|mid|middle|end|late|early-|mid-|late-)\s*(?:of\s*)?(" + "|".join(months.keys()) + r")\b", question_lower)
    if sub_month_pattern:
        timing = re.search(r"\b(beginning|start|early|mid|middle|end|late|early-|mid-|late-)\b", question_lower)
        month_name = sub_month_pattern.group(1)
        month_num = months.get(month_name.lower())
        # Default day mapping
        day = 15
        if timing:
            t = timing.group(1)
            if t.startswith('begin') or t.startswith('start') or t.startswith('early'):
                day = 5
            elif t.startswith('mid') or t.startswith('middle'):
                day = 15
            elif t.startswith('end') or t.startswith('late'):
                day = 25
        try:
            return datetime(current_year, month_num, day, tzinfo=timezone.utc)
        except Exception:
            pass

    # 2.b) Week-of-month phrases: 'first week of August', 'August first week', etc.
    week_match = re.search(r"\b(?:((?:first|1st|second|2nd|third|3rd|fourth|4th|last))\s+week\s+(?:of\s+)?(" + "|".join(months.keys()) + r")|(" + "|".join(months.keys()) + r")\s+((?:first|1st|second|2nd|third|3rd|fourth|4th|last))\s+week)\b", question_lower)
    if week_match:
        # week_match groups vary depending on which alternation matched
        grp_month = None
        grp_weekord = None
        if week_match.group(2):
            grp_month = week_match.group(2)
            grp_weekord = week_match.group(1)
        else:
            grp_month = week_match.group(3)
            grp_weekord = week_match.group(4)

        if grp_month and grp_weekord:
            month_num = months.get(grp_month.lower())
            wo = grp_weekord.lower()
            # Map ordinal to approximate day in the week
            if wo.startswith('first') or wo.startswith('1'):
                day = 4
            elif wo.startswith('second') or wo.startswith('2'):
                day = 11
            elif wo.startswith('third') or wo.startswith('3'):
                day = 18
            else:
                # fourth or last
                day = 25
            try:
                return datetime(current_year, month_num, day, tzinfo=timezone.utc)
            except Exception:
                pass

    # 2.c) Numeric date formats: MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD
    # Heuristics: if first group has 4 digits treat as year-first (YYYY-MM-DD).
    # If ambiguous (both day and month <= 12) prefer MM/DD/YYYY (US-style) but
    # if the first group > 12 then it's day-first.
    num_date_match = re.search(r"\b(\d{1,4})[\/-](\d{1,2})[\/-](\d{1,4})\b", question)
    if num_date_match:
        g1, g2, g3 = num_date_match.group(1), num_date_match.group(2), num_date_match.group(3)
        # Normalize as integers
        try:
            n1, n2, n3 = int(g1), int(g2), int(g3)
        except ValueError:
            n1 = n2 = n3 = None
        if n1 and n2 and n3:
            # Year-first, e.g., 2026-10-20 or 2026/10/20
            if len(g1) == 4:
                year, month, day = n1, n2, n3
            elif len(g3) == 4:
                # Assume g3 is year; ambiguous between MM/DD/YYYY and DD/MM/YYYY
                # If g1 > 12 then g1 is day -> DD/MM/YYYY
                if n1 > 12:
                    day, month, year = n1, n2, n3
                elif n2 > 12:
                    # if second > 12 then second must be day -> MM/DD/YYYY wouldn't occur; interpret as MM/DD/YYYY otherwise
                    day, month, year = n2, n1, n3
                else:
                    # Ambiguous; prefer MM/DD/YYYY
                    month, day, year = n1, n2, n3
            else:
                # No 4-digit year present; ignore as a full date
                month = day = year = None

            if month and day and year:
                try:
                    return datetime(year, month, day, tzinfo=timezone.utc)
                except Exception:
                    pass

    # 3) Single month mention without timing — treat as unspecified (no explicit date)
    month_only = re.search(r"\b(" + "|".join(months.keys()) + r")\b", question_lower)
    if month_only:
        # No explicit timing -> treat as not explicitly time-specified
        return None

    # 4) Fallback to LLM structured extraction if available
    try:
        llm = get_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(DateExtractionResult)
        date_prompt = f"""You are a precise time-extraction system. Today's current date anchor is strictly {today_str}.
        
        Analyze the user's question and determine the explicit or implicit target date window they are referencing.
        
        Rules:
        1. Exact Formats: Convert strings like '01/01/2026' or 'March 12th' cleanly to standard ISO strings.
        2. Vague Sub-monthly Terms: 
           - 'beginning of June' -> '{current_year}-06-01'
           - 'middle of June' or 'mid-June' -> '{current_year}-06-15'
           - 'end of June' or 'late June' -> '{current_year}-06-25'
        3. Relative Steps: Calculate offsets relative to today ({today_str}) dynamically.
        4. No Timeframe Specified: If they mean right now, set time_mentioned to false and return nothing.
        
        USER QUESTION: "{question}" """
        result = structured_llm.invoke(date_prompt)
        if result.time_mentioned and result.target_date_iso:
            return datetime.strptime(result.target_date_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        pass

    return None


def _extract_crop_fallback(question: str) -> Optional[str]:
    """Fallback crop extraction using simple pattern matching."""
    crop_patterns = {
        'Maize': [r'\bmaize\b', r'\bcorn\b'],
        'Rice': [r'\brice\b'],
        'Wheat': [r'\bwheat\b'],
        'Beans': [r'\bbeans\b', r'\bbean\b'],
        'Sorghum': [r'\bsorghum\b'],
        'Millet': [r'\bmillet\b'],
        'Potato': [r'\bpotato(?:es)?\b'],
        'Cassava': [r'\bcassava\b'],
        'Sweet potato': [r'\bsweet potato(?:es)?\b', r'\byam\b'],
        'Peanut': [r'\bpeanut(?:s)?\b', r'\bgroundnut(?:s)?\b', r'\barachis\b'],
        'Chickpea': [r'\bchickpea(?:s)?\b', r'\bgram\b'],
        'Lentil': [r'\blentil(?:s)?\b'],
        'Tomato': [r'\btomato(?:es)?\b'],
        'Onion': [r'\bonion(?:s)?\b'],
        'Cabbage': [r'\bcabbage\b'],
        'Sesame': [r'\bsesame\b'],
        'Sunflower': [r'\bsunflower\b'],
        'Cotton': [r'\bcotton\b'],
        'Soybean': [r'\bsoybean(?:s)?\b'],
        'Barley': [r'\bbarley\b'],
        'Oats': [r'\boats\b'],
        'Rye': [r'\brye\b'],
    }
    question_lower = question.lower()
    for crop_name, patterns in crop_patterns.items():
        for pattern in patterns:
            if re.search(pattern, question_lower):
                return crop_name
    return None      

# ─────────────────────────────────────────────────────────────
# UNIFIED PROMPT — GATE Context-Driven Agricultural Assistant
# (Kept intact exactly as you pasted)
# ─────────────────────────────────────────────────────────────
UNIFIED_PROMPT = ChatPromptTemplate.from_template("""
You are AU - Agent User, a friendly agricultural assistant for farmers.

Your task is to answer the farmer's question using COMPLETE GATE context synthesis.

You must internally reason over all available context dimensions when forming the answer.
Surface only the contextual signals that materially improve agricultural decision-making, safety, timing, feasibility, or actionability.
- Ground truth: farmer context, crop, location, soil properties, soil constraints, production regime, and seasonal forecast
- Actions: farming scale, socioeconomic limitations, available resources, feasibility, and risk tolerance
- Temporal context: today's date, daily forecast, rain timing, total rainfall, peak rainfall, and inferred crop growth stage
- End values: the farmer's stated or inferred objective, such as yield, sustainability, livelihood protection, biodiversity, or cost control

Important:
Use all provided context in reasoning, but do not mechanically list every value in the final answer.
Prefer synthesized agronomic insights over directly repeating raw contextual values.
The final response should sound natural, practical, farmer-friendly, and decision-oriented.
Do not ignore relevant contextual signals.
Less relevant signals may be used internally for confidence adjustment, risk estimation, or timing refinement without explicitly mentioning them in the final answer.

---
G - GROUND TRUTH CONTEXT:
FARMER CONTEXT: {farmer_context}
COORDINATES: Lat {latitude}, Lon {longitude}
SEASONAL WEATHER FORECAST: {seasonal_category}
SOIL PROPERTIES (iSDAsoil Data - 30m resolution): {soil_data_summary}
SOIL CONSTRAINTS: {soil_risk_flags}
PRODUCTION REGIME & RECOMMENDATIONS: {soil_recommendations}

T - TEMPORAL CONTEXT:
TODAY'S DATE: {today_date}
{daily_weather_section}

A - ACTIONS CONTEXT:
Scale & Socioeconomic Factors: Included inside farmer context. Infer practical constraints from the farmer profile.

E - END VALUES:
Farming Purpose: Infer from the farmer's question. If not explicit, assume a balanced goal of yield, sustainability, cost control, and livelihood protection.

---
FARMER'S QUESTION: "{user_question}"

════════════════════════════════════════════════════════════════════════════════
INTERNAL REASONING — COMPLETE CONTEXT SYNTHESIS
DO NOT OUTPUT THIS REASONING
════════════════════════════════════════════════════════════════════════════════

STEP 1: FULL CONTEXT ABSORPTION & CRITICAL OVERRIDES
Before answering, internally extract and use insights from every available context group. Pay extra attention to explicit overrides inside the user's question:
- Crop Extraction Override: Carefully scan the user's question for the target crop. Even if the crop name is tied to a geographic feature or location descriptor (e.g., "peanut grower in Peanut Basin"), extract the agricultural crop intent ("Peanut") directly from the text and override any missing pipeline configurations.
- Temporal Context Override: Scan the user's text for explicit timing descriptors (e.g., "It is the middle of June..."). If the user explicitly sets a scenario time context in their phrase, treat that timeframe as the operational baseline instead of the raw "{today_date}" value. Adjust all dynamic weather assumptions and growth stages to fit that mentioned timeline.

STEP 2: CROP GROWTH STAGE INFERENCE
Infer and naturally mention the crop growth stage when it materially affects the recommendation. Never ask the farmer to provide it.
Use this priority order:
1. Direct question clues (including relative or explicit date descriptions like 'middle of June')
2. Farmer context and crop information
3. Today's date and seasonal timing (or the user-defined date scenario override from Step 1)
4. Regional production regime
5. Weather pattern and agronomic logic

Question clue guide:
- "just planted", "germination", "emergence" → Early vegetative / establishment
- "seedling", "thinning", "first leaves" → Early vegetative
- "tillering", "canopy closing", "side-dressing time" → Mid vegetative
- "knee-high", "rapid growth", "stem elongation" → Late vegetative
- "flowering", "tasseling", "silking", "pollination" → Reproductive / flowering
- "pod fill", "grain fill", "ear development" → Grain / fruit development
- "dough stage", "drying down", "maturity" → Late stage / maturity
- "harvest", "ready to cut" → Harvest-ready

If evidence is incomplete, commit to the most reasonable stage and briefly signal it as an inference.

STEP 3: CROSS-CONTEXT INTERACTION ANALYSIS
Do not treat context fields separately. Combine them.
Internally reason about:
- How soil constraints change the best action
- How the daily forecast changes action timing
- How the seasonal forecast changes short-term risk
- How crop stage changes sensitivity to water, nutrients, pests, weeds, or field operations
- How farmer scale and socioeconomic context affect what is realistic
- How the production regime supports or limits the recommendation
- How the farming objective changes the safest or most useful advice

STEP 4: CONFLICT RESOLUTION
If contextual signals conflict, reconcile them before answering.
Examples:
- If soil suggests fertilizer but rain is imminent, avoid runoff risk and recommend safer timing or placement.
- If crop needs intervention but farmer resources are limited, recommend the lowest-cost effective action first.
- If seasonal forecast is wet but short-term forecast is dry, separate immediate action from near-term monitoring.
- If yield goals conflict with sustainability or cost, recommend a balanced, risk-aware option.

When in doubt, prioritize:
1. Farmer safety
2. Crop survival
3. Avoiding economic loss
4. Timing-sensitive agronomic action
5. Sustainable yield improvement

STEP 5: RECOMMENDATION GROUNDING CHECK
Before finalizing, verify internally that the answer is grounded in:
- Soil conditions
- Soil risks or constraints
- Seasonal forecast
- Daily forecast
- Inferred growth stage
- Production regime
- Farmer scale and socioeconomic feasibility
- Farmer objective

Do not give generic advice. Every recommendation must be shaped by multiple context dimensions.

STEP 6: FINAL ANSWER GENERATION
Now write the farmer-facing answer.
Show the conclusion and action plan, not the hidden reasoning.
The answer must be concise, clear, practical, and directly useful.

════════════════════════════════════════════════════════════════════════════════
FINAL ANSWER STRUCTURE
════════════════════════════════════════════════════════════════════════════════


Write the response in natural conversational paragraphs, not bullet points or numbered lists.

Start with a brief sentence identifying the inferred crop growth stage and directly answer the farmer’s question.

Then provide a concise, practical recommendation that naturally integrates the contextual dimensions that materially improve the agricultural recommendation for the farmer’s specific question. Surface only the most decision-relevant context (e.g., soil, weather, growth stage, scale, or objective) as needed for actionable, safe, and specific guidance.

Blend all contextual reasoning smoothly into flowing paragraphs instead of separating them into sections.

Keep the tone farmer-friendly, practical, and decision-oriented.

Avoid:
- numbered lists
- excessive formatting
- long technical explanations
- large product lists unless specifically asked

Mention only the most important actions and risks.

If uncertainty exists, briefly state the assumption naturally within the paragraph.

Keep the answer between 200 and 250 words.

Prioritize agronomic actions that directly improve the farmer’s immediate decision outcome rather than maximizing the amount of contextual information mentioned.

════════════════════════════════════════════════════════════════════════════════
RESPONSE RULES
════════════════════════════════════════════════════════════════════════════════
✓ Always reason over all available context dimensions, even if not all of them are explicitly surfaced in the final answer.
✓ Infer the most likely crop growth stage when it materially affects the recommendation. If confidence is moderate or low, present the stage naturally as an informed inference rather than a confirmed fact.
✓ Always answer the farmer's question directly.
✓ Integrate the contextual dimensions that materially improve the agricultural recommendation for the farmer’s specific question.
✓ Always reconcile conflicting signals before recommending.
✓ Always make recommendations practical, stage-appropriate, and feasible for the farmer.
✓ Always prioritize low-risk, economically sensible actions when uncertainty exists.
✓ Do not mention "GATE" in the final answer.
✓ Do not expose internal reasoning steps.
✓ Answer only what is necessary to solve the farmer’s question using the provided context. Do not drift into unrelated topics, excessive background information, or recommendations the farmer did not ask for.                     
✓ Do not list raw context values unless the farmer asks for them or they are essential.
✓ When context signals are weak or uncertain, give conservative and low-risk recommendations.
✓ Do not start with weather alone.
✓ Do not ask the farmer for missing stage/context; infer from available clues.
✓ Prefer recommendations that improve the farmer’s immediate decision quality rather than maximizing contextual detail.
✓ Keep the answer between 200 and 250 words.
""")

# ─────────────────────────────────────────────────────────────
# FORECAST PROVIDER CONFIGURATION (Easy to change!)
# ─────────────────────────────────────────────────────────────
DAILY_FORECAST_WSP = "openmeteo"      # Options: "openmeteo", "noaacpc", "ecmwf", "chirps", "iri"
SEASONAL_FORECAST_WSP = "ecmwf"       # Options: "noaacpc", "openmeteo", "ecmwf", "chirps", "iri"

# ─── NaviGator LLM (shared across all WSPs) ───
def get_llm():
    return ChatOpenAI(
        # model="gpt-oss-120b",
        model="gpt-5",
        temperature=0.2,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_api_base="https://api.ai.it.ufl.edu/v1",
        default_headers={
            "Client-ID"    : os.getenv("CLIENT_ID"),
            "Client-Secret": os.getenv("CLIENT_SECRET"),
        }
    )
  
# ─────────────────────────────────────────────────────────────
# UNIFIED PROMPT — GATE Context-Driven Agricultural Assistant
# G: Ground Truth (soil, crop, location, seasonal weather, production regime)
# A: Actions (socioeconomic, scale)
# T: Temporal (daily forecast, date, phenology, growth stage)
# E: End values (farming purpose: yield, biodiversity, etc.)
# ─────────────────────────────────────────────────────────────

UNIFIED_PROMPT = ChatPromptTemplate.from_template("""
You are AU - Agent User, a friendly agricultural assistant for farmers.

Your task is to answer the farmer's question using COMPLETE GATE context synthesis.

You must internally reason over ALL available context dimensions before forming the answer.
The context — weather, soil, seasonal forecast, location, production regime — is your silent reasoning input.
It makes your advice specific, calibrated, and correct. It does NOT appear in the final answer.

Think like an expert agronomist who has already internalized all the data and is giving the farmer
direct, actionable advice — not reporting what the data says.

Core principle:
- USE all context to reason (soil pH, texture, nutrients, rain timing, seasonal outlook, growth stage, scale, objectives)
- CITE none of it in the final answer (no soil values, no forecast dates, no mm amounts, no seasonal categories, no coordinates)
- Let the context silently shape: which rates you recommend, which risks you flag, how you sequence actions, and how conservative or bold the advice is

---
G - GROUND TRUTH CONTEXT:
FARMER CONTEXT: {farmer_context}
COORDINATES: Lat {latitude}, Lon {longitude}
SEASONAL WEATHER FORECAST: {seasonal_category}
SOIL PROPERTIES (iSDAsoil Data - 30m resolution): {soil_data_summary}
SOIL CONSTRAINTS: {soil_risk_flags}
PRODUCTION REGIME & RECOMMENDATIONS: {soil_recommendations}

T - TEMPORAL CONTEXT:
TODAY'S DATE: {today_date}
{daily_weather_section}

A - ACTIONS CONTEXT:
Scale & Socioeconomic Factors: Included inside farmer context. Infer practical constraints from the farmer profile.

E - END VALUES:
Farming Purpose: Infer from the farmer's question. If not explicit, assume a balanced goal of yield, sustainability, cost control, and livelihood protection.

---
FARMER'S QUESTION: "{user_question}"

════════════════════════════════════════════════════════════════════════════════
INTERNAL REASONING — COMPLETE CONTEXT SYNTHESIS
DO NOT OUTPUT THIS REASONING
════════════════════════════════════════════════════════════════════════════════

STEP 1: FULL CONTEXT ABSORPTION
Before answering, internally extract and use insights from every available context group:
- Farmer context: crop, scale, location, resources, constraints, farming situation
- Soil context: pH, nutrients, texture, drainage, organic matter, limitations, risk flags
- Production context: production regime and provided agronomic recommendations
- Seasonal context: broader rainfall or climate tendency for the season
- Daily forecast context: immediate rain window, number of rainy days, next rain, peak rain, total rain
- Temporal context: today's date and what it implies for timing
- Growth-stage context: infer current stage using all clues
- Objective context: infer what the farmer is trying to optimize

STEP 2: CROP GROWTH STAGE INFERENCE
Infer and naturally mention the crop growth stage when it materially affects the recommendation. Never ask the farmer to provide it.
Use this priority order:
1. Direct question clues
2. Farmer context and crop information
3. Today's date and seasonal timing
4. Regional production regime
5. Weather pattern and agronomic logic

Question clue guide:
- "just planted", "germination", "emergence" → Early vegetative / establishment
- "seedling", "thinning", "first leaves" → Early vegetative
- "tillering", "canopy closing", "side-dressing time" → Mid vegetative
- "knee-high", "rapid growth", "stem elongation" → Late vegetative
- "flowering", "tasseling", "silking", "pollination" → Reproductive / flowering
- "pod fill", "grain fill", "ear development" → Grain / fruit development
- "dough stage", "drying down", "maturity" → Late stage / maturity
- "harvest", "ready to cut" → Harvest-ready

If evidence is incomplete, commit to the most reasonable stage and briefly signal it as an inference.

STEP 3: CROSS-CONTEXT INTERACTION ANALYSIS
Do not treat context fields separately. Combine them.
Internally reason about:
- How soil constraints change the best action
- How the daily forecast changes action timing
- How the seasonal forecast changes short-term risk
- How crop stage changes sensitivity to water, nutrients, pests, weeds, or field operations
- How farmer scale and socioeconomic context affect what is realistic
- How the production regime supports or limits the recommendation
- How the farming objective changes the safest or most useful advice

STEP 4: CONFLICT RESOLUTION
If contextual signals conflict, reconcile them before answering.
Examples:
- If soil suggests fertilizer but rain is imminent, avoid runoff risk and recommend safer timing or placement.
- If crop needs intervention but farmer resources are limited, recommend the lowest-cost effective action first.
- If seasonal forecast is wet but short-term forecast is dry, separate immediate action from near-term monitoring.
- If yield goals conflict with sustainability or cost, recommend a balanced, risk-aware option.

When in doubt, prioritize:
1. Farmer safety
2. Crop survival
3. Avoiding economic loss
4. Timing-sensitive agronomic action
5. Sustainable yield improvement

STEP 5: RECOMMENDATION GROUNDING CHECK
Before finalizing, verify internally that the answer is grounded in:
- Soil conditions
- Soil risks or constraints
- Seasonal forecast
- Daily forecast
- Inferred growth stage
- Production regime
- Farmer scale and socioeconomic feasibility
- Farmer objective

Do not give generic advice. Every recommendation must be shaped by multiple context dimensions.

STEP 6: CONTEXT INTERNALIZATION CHECK (mandatory before writing)
Before writing, confirm that your reasoning from Steps 1–5 has fully absorbed all context.
Now set it aside. The final answer must contain zero references to:
- Any weather value: dates, mm amounts, rainy day counts, forecast windows
- Any soil value: pH, texture, organic matter, nutrient levels, drainage class
- Any seasonal category: "above normal", "below normal", provider names
- Any coordinates or location data beyond what the farmer themselves stated
- Any system or data source names

If you are tempted to write "because rain is coming" or "your soil is clay" — stop.
Instead, let that signal silently determine WHAT you recommend and WHEN, not WHAT you say.

STEP 7: FINAL ANSWER GENERATION
Now write the farmer-facing answer.
The answer must sound like expert agronomic advice — specific, concrete, and directly useful.
Specificity comes from context internalization, not from citing context.

════════════════════════════════════════════════════════════════════════════════
FINAL ANSWER STRUCTURE
════════════════════════════════════════════════════════════════════════════════

Write the response in natural conversational paragraphs, not bullet points or numbered lists.

Start with a brief sentence identifying the inferred crop growth stage and directly answer the farmer’s question.

Then give a concrete, specific recommendation: real rates, real timing, real placement, real risk flags.
The specificity must come from having internalized the context — not from quoting it.

The answer must read as if a trusted local agronomist, who already knows this farm inside out,
is giving the farmer a direct answer based on judgment — not a data report.

Keep the tone farmer-friendly, practical, and decision-oriented.

Avoid:
- numbered lists
- excessive formatting
- long technical explanations
- large product lists unless specifically asked
- any mention of weather data, soil data, forecast categories, or provider information

Mention only the most important actions and risks.

If uncertainty exists, briefly state the assumption naturally within the paragraph.

Keep the answer between 200 and 250 words.

════════════════════════════════════════════════════════════════════════════════
RESPONSE RULES
════════════════════════════════════════════════════════════════════════════════
✓ Always reason over all available context dimensions before writing.
✓ Infer the most likely crop growth stage when it materially affects the recommendation. If confidence is moderate or low, present the stage naturally as an informed inference rather than a confirmed fact.
✓ Always answer the farmer’s question directly.
✓ Always reconcile conflicting signals before recommending.
✓ Always make recommendations practical, stage-appropriate, and feasible for the farmer.
✓ Always prioritize low-risk, economically sensible actions when uncertainty exists.
✓ Do not mention "GATE" in the final answer.
✓ Do not expose internal reasoning steps.
✓ Answer only what the farmer asked. Do not drift into unrelated topics or recommendations they did not request.
✗ The final answer must contain NO references to context data of any kind: no weather dates, no rainfall figures, no soil values, no forecast categories, no provider names, no coordinates. Context is invisible reasoning fuel — it never appears in the output.
✗ Do not say "given the forecast", "your soil", "because rain is coming", "the seasonal outlook", or any phrase that references the context data. Shape the advice using the context; do not cite it.
✓ When context signals are weak or uncertain, give conservative and low-risk recommendations.
✓ Do not start with weather alone.
✓ Do not ask the farmer for missing stage/context; infer from available clues.
✓ Keep the answer between 200 and 250 words.
""")
