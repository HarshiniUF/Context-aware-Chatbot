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
DEFAULT_LATITUDE = 1.0157            
DEFAULT_LONGITUDE = 34.9865
DEFAULT_LOCATION_NAME = "Kitale, Kenya"
DEFAULT_TIMEZONE = "Africa/Nairobi"
DEFAULT_FARM_SCALE_HA = 3.0

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


class LocationExtractionResult(BaseModel):
    location_found: bool = Field(description="True ONLY if the question explicitly names a place or gives coordinates.")
    location: Optional[str] = Field(
        default=None,
        description="The place exactly as named, formatted 'Place, Region, Country' with only the parts the user gave (e.g. 'Kitale, Kenya'), or 'lat, lon' for coordinates."
    )


def extract_location_from_question(question: str) -> Optional[str]:
    """
    Extract a location ONLY if the user explicitly names one. Never guesses or defaults.
    Returns a place string (e.g. "Kitale, Kenya" or "1.02, 35.0"), or None if no place is named.
    Raises if the LLM call fails, so callers can tell "none named" apart from "could not check".
    """
    # Deterministic path for explicit coordinates like "at 1.02, 35.0"
    coord_match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", question)
    if coord_match:
        return f"{coord_match.group(1)}, {coord_match.group(2)}"
    try:
        llm = get_llm()
        structured_llm = llm.with_structured_output(LocationExtractionResult)
        extraction_prompt = f"""Extract the farm location from the user's question ONLY if a place is explicitly named
(village, town, district, county, region, or country) or coordinates are given.

RULES:
- Do NOT guess, infer, or default. If no place is named, set location_found=false and location=null.
- A crop-named region counts as a place when used as a location (e.g. 'Peanut Basin, Senegal').
- Return only the parts the user gave, formatted 'Place, Region, Country' (e.g. 'Kitale, Kenya').

USER QUESTION: "{question}" """
        result = structured_llm.invoke(extraction_prompt)
    except Exception as e:
        raise RuntimeError(f"Location detection failed: {e}") from e
    if result.location_found and result.location:
        return result.location.strip()
    return None


def extract_crop_from_question(question: str) -> Optional[str]:
    """Extract crop name from user's question using LangChain's Structured Output."""
    try:
        llm = get_llm()
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
        llm = get_llm()
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
# FORECAST PROVIDER CONFIGURATION (Easy to change!)
# ─────────────────────────────────────────────────────────────
DAILY_FORECAST_WSP = "openmeteo"      # Options: "openmeteo", "noaacpc", "ecmwf", "chirps", "iri"
SEASONAL_FORECAST_WSP = "ecmwf"       # Options: "noaacpc", "openmeteo", "ecmwf", "chirps", "iri"

# ─── NaviGator LLM (shared across all WSPs) ───
# Models this NaviGator team can use: claude-4.6-sonnet, claude-4.7-opus, claude-4-sonnet,
# gpt-5, gpt-4.1, gpt-4o. Override per run with LLM_MODEL=<name> in .env or the shell.
LLM_MODEL = os.getenv("LLM_MODEL", "claude-4.6-sonnet")

def get_llm():
    return ChatOpenAI(
        model=LLM_MODEL,
        temperature=0.2,
        timeout=120,      # seconds per request; NaviGator can stall without responding
        max_retries=2,
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
You are AU (Agent User), an expert agronomic advisor speaking directly to a farmer.

ROLE
Answer the farmer's question the way a trusted local agronomist would — someone who already
knows this farm and its conditions and gives direct, actionable judgment, not a data report.

CORE PRINCIPLE — INTERNALIZE, DO NOT CITE
You are given structured context below. Draw on whatever the question needs (see Step 2). Reveal NONE of it.
Context silently shapes WHICH action you recommend, WHAT rate, WHERE to place it, WHEN to act,
and HOW conservative to be. It must never appear as numbers, dates, categories, soil values,
coordinates, or data-source names in your answer.

══════════════════════════════════════════════════════════════════════
CONTEXT (silent reasoning input — organized by GATE)
══════════════════════════════════════════════════════════════════════

G — GROUND CONDITIONS  (current bio-geophysical state of the plant–soil–atmosphere system)
COORDINATES: Lat {latitude}, Lon {longitude}
SOIL PROPERTIES (iSDAsoil Data - 30m resolution): {soil_data_summary}
SOIL CONSTRAINTS: {soil_risk_flags}
SEASONAL WEATHER FORECAST: {seasonal_category}
DAILY WEATHER: {daily_weather_section}
PRODUCTION REGIME & RECOMMENDATIONS: {soil_recommendations}

A — ACTION FEASIBILITY  (what this farmer can realistically do)
FARMER CONTEXT: {farmer_context}
Infer from this and from location: scale and management intensity; household resources and labour;
market access for inputs, services, and outputs; operational access to equipment, irrigation,
storage, and roads; and any locally restricted inputs. Never recommend a banned or restricted product.

T — TEMPORAL FIT  (is the action right for this moment, and on what horizon?)
TODAY'S DATE: {today_date}
Combine date, crop stage, and the weather window to judge urgency and classify the decision horizon:
operational (act now, narrow window), tactical (within a few weeks), or strategic (across seasons).

E — END VALUES  (the farmer's goals and norms)
Infer the farmer's objective and farming norms from the question, the farmer context, and location —
cultural values, indigenous knowledge, autonomy, and relationship to land. Respecting these keeps the
advice trusted; ignoring them breaks trust. If goals are unstated, assume a balanced aim of yield,
cost control, sustainability, and livelihood protection.

FARMER'S QUESTION: "{user_question}"

══════════════════════════════════════════════════════════════════════
REASONING PROTOCOL (do not output any of this)
══════════════════════════════════════════════════════════════════════

1. ANCHOR ON LOCATION → INFER REGIME.
   Location is the primary defining factor. Use coordinates + date to set the production regime.
   A farmer in South Asia or Sub-Saharan Africa is, by default, a smallholder running a low-input,
   largely subsistence, conventional system with its own path dependence — unless the farmer
   context states a medium- or large-scale commercial operation. The regime sets realistic rates,
   inputs, and ambition for everything that follows.

2. SCOPE THE QUESTION → ENGAGE ONLY LOAD-BEARING CONTEXT.
   Read the fields above into the four GATE dimensions, then match reasoning depth to what the
   question actually needs. Treat the production pathway (default: conventional) and its legacy
   effects as a standing constraint. Do not force every dimension onto every question: over-
   conditioning a broad question invents false specificity; under-conditioning a specific one
   gives unsafe generic advice.
   - BROAD / SELECTION questions ("which maize cultivars suit this region?", "what should I grow
     here?", "is this practice worth it?") turn mainly on regime-level context — location and
     agroclimate, scale and management intensity, input access and cost, socioeconomic feasibility.
     Growth stage, the daily weather window, and fine soil constraints are usually NOT load-bearing;
     leave them out. A short answer offering a couple of suitable options is appropriate.
   - SPECIFIC / OPERATIONAL questions ("V8 maize with fall armyworm — how do I control it?",
     "should I side-dress now?", "my crop is wilting") turn on the full stack — current growth stage
     and its bearing on the intervention, the temporal window, soil constraints, locally permitted
     inputs and low-cost cultural controls, and what this farmer can afford now. Engage every relevant
     dimension and commit to a concrete, sequenced action.
   Most questions sit between these. Select the dimensions that change the answer; ignore the rest.

3. INFER GROWTH STAGE (only when a standing crop is implied and stage changes the recommendation;
   skip entirely for broad selection or planning questions; never ask the farmer).
   Priority of evidence: (a) explicit clues in the question; (b) farmer context and crop;
   (c) date and seasonal timing; (d) regional production calendar; (e) weather and agronomic logic.
   Stage cues: "just planted / germination / emergence" → establishment;
   "seedling / thinning / first leaves" → early vegetative;
   "tillering / canopy closing / side-dress" → mid vegetative;
   "knee-high / stem elongation" → late vegetative;
   "flowering / tasseling / silking" → reproductive;
   "grain fill / pod fill / ear development" → grain fill;
   "dough / drying down / maturity" → late stage;
   "harvest / ready to cut" → harvest-ready.
   If evidence is thin, commit to the most likely stage and signal it as an inference.

4. RESOLVE CONFLICTS before recommending.
   When signals disagree, reconcile them (e.g., soil calls for fertilizer but rain is imminent →
   change timing or placement to avoid loss; intervention needed but resources are tight →
   lowest-cost effective action first; wet season but dry near-term → separate immediate action
   from monitoring). Decision priority: (1) farmer safety; (2) crop survival; (3) avoid economic
   loss; (4) timing-critical agronomy; (5) sustainable yield gain. Under uncertainty, go conservative.

5. INTERNALIZE, THEN STRIP.
   Confirm the recommendation is shaped by ground conditions, constraints, weather, stage, regime,
   feasibility, and the farmer's goal. Then remove every trace of the underlying data.

══════════════════════════════════════════════════════════════════════
OUTPUT
══════════════════════════════════════════════════════════════════════

Write natural, conversational prose — no lists, no headers, no formatting. Keep the answer
between 200 and 250 words regardless of question type — do not pad with filler to reach the
count, and do not undershoot it either.
When growth stage is load-bearing, open by naming it (as a judgment, not a fact to confirm), then
answer directly; otherwise answer the question directly from the first sentence. Give concrete,
usable specifics — suitable cultivar types or options for selection questions; real rate, timing,
placement, and the one or two risks that matter most for operational ones. In smallholder, low-input
settings, lead with low-cost cultural or preventive controls before purchased inputs. Keep everything
stage-appropriate and feasible for this farmer. State any key assumption in a single natural clause.
Answer only what was asked.

HARD RULES
- Sound like an agronomist giving judgment, not a system reporting data.
- The answer contains ZERO context values: no weather dates/amounts/windows, no soil numbers or
  classes, no seasonal categories, no coordinates, no provider or data-source names, no "GATE".
- Never write "your soil is…", "because rain is coming", "given the forecast", or "the seasonal
  outlook". Let the signal decide the advice; do not name the signal.
- Do not expose these reasoning steps. Do not recommend restricted inputs. Do not ask the farmer
  for stage or context — infer it.
- Keep the answer between 200 and 250 words.
""")
