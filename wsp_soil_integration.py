"""
=============================================================
Soil-Weather Integration Module
Combines iSDAsoil data with seasonal forecasts for LLM prompts
=============================================================

This module formats soil data for use in the unified chatbot prompt,
making it compatible with seasonal forecasts and weather data.

USAGE:
  from wsp_soil_integration import integrate_soil_with_weather
  
  soil_data = get_soil_data(lat, lon)
  weather_data = get_weather_data(lat, lon)
  
  prompt_vars = integrate_soil_with_weather(soil_data, weather_data)
"""

import json
from typing import Dict, List, Optional
from wsp_soil_isda import (
    extract_soil_values,
    interpret_soil_for_recommendations,
    SOIL_PROPERTIES_DICT,
    classify_soil_texture,
)

# ─────────────────────────────────────────────────────────────
# SOIL-WEATHER INTEGRATION
# ─────────────────────────────────────────────────────────────

def format_soil_for_prompt(soil_data: dict) -> dict:
    """
    Formats iSDAsoil data into prompt-ready variables.
    
    Args:
        soil_data: Output from get_soil_data() in wsp_soil_isda.py
    
    Returns:
        Dictionary with formatted soil variables for ChatPromptTemplate
    """
    
    extracted = extract_soil_values(soil_data)
    interpretation = interpret_soil_for_recommendations(extracted)
    
    # ─ Build Soil Summary (with Texture Classification) ─
    soil_summary_lines = []
    
    # Organic Carbon
    carbon_020 = next(
        (c["value"] for c in extracted["soil_chemical"].get("carbon_organic", []) 
         if c["depth"] == "0-20"), 
        None
    )
    if carbon_020 is not None:
        carbon_pct = carbon_020 / 10
        soil_summary_lines.append(f"  • Organic Carbon (0-20cm): {carbon_pct:.2f}%")
    
    # Total Nitrogen
    nitrogen_020 = next(
        (n["value"] for n in extracted["soil_nutrients"].get("nitrogen_total", []) 
         if n["depth"] == "0-20"), 
        None
    )
    if nitrogen_020 is not None:
        nitrogen_pct = nitrogen_020 / 10
        soil_summary_lines.append(f"  • Nitrogen, Total (0-20cm): {nitrogen_pct:.3f}%")
    
    # Soil pH
    ph_020 = next(
        (p["value"] for p in extracted["soil_chemical"].get("ph", []) 
         if p["depth"] == "0-20"), 
        None
    )
    if ph_020 is not None:
        soil_summary_lines.append(f"  • Soil pH (0-20cm): {ph_020:.1f}")
    
    # Extract sand, clay, silt for texture classification
    # Try new API property names first (sand_content, clay_content), then fall back to old names
    clay_020 = next((c["value"] for c in extracted["soil_physical"].get("clay_content", []) if c["depth"]=="0-20"), None)
    if clay_020 is None:
        clay_020 = next((c["value"] for c in extracted["soil_physical"].get("clay", []) if c["depth"]=="0-20"), None)
    
    sand_020 = next((s["value"] for s in extracted["soil_physical"].get("sand_content", []) if s["depth"]=="0-20"), None)
    if sand_020 is None:
        sand_020 = next((s["value"] for s in extracted["soil_physical"].get("sand", []) if s["depth"]=="0-20"), None)
    
    silt_020 = next((s["value"] for s in extracted["soil_physical"].get("silt_content", []) if s["depth"]=="0-20"), None)
    
    # Classify soil texture and add to summary
    texture_info = None
    if sand_020 is not None and clay_020 is not None and silt_020 is not None:
        texture_info = classify_soil_texture(sand_020, clay_020, silt_020)
        
        texture_line = f"  • Soil Texture: {texture_info['texture_class']}"
        texture_line += f" (Sand: {texture_info['percentages']['sand']:.1f}%, "
        texture_line += f"Clay: {texture_info['percentages']['clay']:.1f}%, "
        texture_line += f"Silt: {texture_info['percentages']['silt']:.1f}%)"
        soil_summary_lines.append(texture_line)
        
        # Add texture characteristics summary
        chars = texture_info.get("characteristics", {})
        if chars:
            soil_summary_lines.append(f"    - Water retention: {chars.get('water_retention', 'N/A')}")
            soil_summary_lines.append(f"    - Workability: {chars.get('workability', 'N/A')}")
            soil_summary_lines.append(f"    - Crop suitability: {chars.get('crop_suitability', 'N/A')}")
    else:
        # Fallback if sand/clay/silt not all available
        parts = []
        if clay_020 is not None:
            parts.append(f"Clay: {clay_020:.1f}%")
        if sand_020 is not None:
            parts.append(f"Sand: {sand_020:.1f}%")
        if silt_020 is not None:
            parts.append(f"Silt: {silt_020:.1f}%")
        if parts:
            soil_summary_lines.append("  • Physical properties (0-20cm): " + ", ".join(parts))
    
    soil_data_summary = "\n".join(soil_summary_lines) if soil_summary_lines else "  No soil data available"
    
    # ─ Build Risk Flags ─
    risk_flags = []
    for risk in interpretation.get("risk_flags", []):
        risk_clean = risk.replace("\n", " ")
        risk_flags.append(f"⚠️ {risk_clean}")
    
    soil_risk_flags = "\n  ".join(risk_flags) if risk_flags else "None — soil conditions are acceptable"
    
    # ─ Build Recommendations ─
    recommendations = []
    for rec in interpretation.get("recommendations", []):
        rec_clean = rec.replace("\n", " ")
        recommendations.append(f"• {rec_clean}")
    
    soil_recommendations = "\n  ".join(recommendations) if recommendations else "Standard soil management practices"
    
    return {
        "soil_data_summary": soil_data_summary,
        "soil_risk_flags": soil_risk_flags,
        "soil_recommendations": soil_recommendations,
        "soil_health_status": interpretation.get("soil_health_summary", "Unknown"),
        "texture_info": texture_info,
        "full_interpretation": interpretation,
    }

def integrate_soil_with_weather(
    soil_data: dict,
    weather_variables: dict = None
) -> dict:
    """
    Integrates soil data with weather variables for the unified prompt.
    
    Args:
        soil_data: Output from get_soil_data() (iSDAsoil)
        weather_variables: Dictionary with weather forecast variables
                          (from seasonal_test.py or other weather modules)
    
    Returns:
        Dictionary with combined soil + weather variables ready for ChatPromptTemplate
    """
    
    # Format soil data
    soil_prompt_vars = format_soil_for_prompt(soil_data)

    # Extract soil values for summary and recommendations
    extracted = soil_data if soil_data else {}
    carbon_020 = next(
        (c["value"] for c in extracted.get("soil_chemical", {}).get("carbon_organic", []) if c["depth"] == "0-20"),
        None
    )
    nitrogen_020 = next(
        (n["value"] for n in extracted.get("soil_nutrients", {}).get("nitrogen_total", []) if n["depth"] == "0-20"),
        None
    )
    ph_020 = next(
        (p["value"] for p in extracted.get("soil_chemical", {}).get("ph", []) if p["depth"] == "0-20"),
        None
    )
    clay_020 = next((c["value"] for c in extracted.get("soil_physical", {}).get("clay_content", []) if c["depth"]=="0-20"), None)
    if clay_020 is None:
        clay_020 = next((c["value"] for c in extracted.get("soil_physical", {}).get("clay", []) if c["depth"]=="0-20"), None)
    sand_020 = next((s["value"] for s in extracted.get("soil_physical", {}).get("sand_content", []) if s["depth"]=="0-20"), None)
    if sand_020 is None:
        sand_020 = next((s["value"] for s in extracted.get("soil_physical", {}).get("sand", []) if s["depth"]=="0-20"), None)
    silt_020 = next((s["value"] for s in extracted.get("soil_physical", {}).get("silt_content", []) if s["depth"]=="0-20"), None)

    # Now safe to use these variables for summary and recommendations
    carbon_pct = carbon_020 / 10 if carbon_020 is not None else None
    nitrogen_pct = nitrogen_020 / 10 if nitrogen_020 is not None else None
    ph_val = ph_020 if ph_020 is not None else None
    sand_val = sand_020 if sand_020 is not None else None
    clay_val = clay_020 if clay_020 is not None else None
    silt_val = silt_020 if silt_020 is not None else None
    texture_class = None
    if sand_val is not None and clay_val is not None and silt_val is not None:
        texture_info = classify_soil_texture(sand_val, clay_val, silt_val)
        texture_class = texture_info['texture_class']
    # Format summary in strict order
    soil_data_summary = (
        f"1. • Organic Carbon (0-20cm): {carbon_pct:.2f}%\n" if carbon_pct is not None else "1. • Organic Carbon (0-20cm): N/A\n"
    )
    soil_data_summary += (
        f"2. • Nitrogen, Total (0-20cm): {nitrogen_pct:.3f}%\n" if nitrogen_pct is not None else "2. • Nitrogen, Total (0-20cm): N/A\n"
    )
    soil_data_summary += (
        f"3. • Soil pH (0-20cm): {ph_val:.1f}\n" if ph_val is not None else "3. • Soil pH (0-20cm): N/A\n"
    )
    if texture_class is not None:
        soil_data_summary += (
            f"4. • Soil Texture: {texture_class} (Sand: {sand_val:.1f}%, Clay: {clay_val:.1f}%, Silt: {silt_val:.1f}%)"
        )
    else:
        soil_data_summary += "4. • Soil Texture: N/A"
    # --- Table and recommendations logic fixed or commented out for safety ---
    # If you want to re-enable the table, initialize table_lines = [] at the top of the function
    # and ensure extracted_soil is defined and passed in. For now, this block is removed to prevent errors.
    #
    # Recommendations logic: ensure recommendations is initialized and used safely
    recommendations = {}
    if ph_020 is not None:
        if ph_020 < 5.5:
            recommendations["ph_adjustment"] = "Lime application recommended (pH too low)"
        elif ph_020 > 7.5:
            recommendations["ph_adjustment"] = "Sulfur application may help (pH too high)"
        else:
            recommendations["ph_adjustment"] = "pH acceptable for most crops"
    # Organic matter action
    if carbon_020 is not None:
        carbon_pct = carbon_020 / 10
        if carbon_pct < 1.0:
            recommendations["organic_matter_action"] = "URGENT: Add compost/manure (OM critically low)"
        elif carbon_pct < 2.0:
            recommendations["organic_matter_action"] = "Increase: Apply 5-10 t/ha compost/manure annually"
        else:
            recommendations["organic_matter_action"] = "Maintain: Continue residue retention"
    # Micronutrient risks based on pH
    recommendations["micronutrient_concerns"] = []
    if ph_020 is not None and ph_020 > 7.2:
        recommendations["micronutrient_concerns"].append("Fe, Mn, Zn deficiency likely (alkaline pH) — use chelates")
    if ph_020 is not None and ph_020 < 5.5:
        recommendations["micronutrient_concerns"].append("Al toxicity risk (acidic pH) — apply lime")
    return recommendations

def soil_affects_irrigation_recommendation(extracted_soil: dict) -> dict:
    """
    Analyzes soil and provides irrigation-specific adjustments.
    Useful for water management questions.
    
    Args:
        extracted_soil: Output from extract_soil_values()
    
    Returns:
        Dictionary with irrigation recommendations based on soil texture/density
    """
    
    recommendations = {
        "texture_class": "Unknown",
        "water_holding_capacity": "Unknown",
        "drainage_capacity": "Unknown",
        "irrigation_frequency": "Standard",
        "irrigation_depth": "Standard (50-60mm)",
        "waterlogging_risk": "Low",
        "drought_risk": "Low",
        "compaction_issue": False,
    }
    
    # Use clay and sand percentages (when available) to infer irrigation adjustments
    clay_020 = next((c["value"] for c in extracted_soil["soil_physical"].get("clay", []) if c["depth"]=="0-20"), None)
    sand_020 = next((s["value"] for s in extracted_soil["soil_physical"].get("sand", []) if s["depth"]=="0-20"), None)

    if sand_020 is not None and sand_020 > 50:
        recommendations["texture_class"] = "Sandy"
        recommendations["irrigation_frequency"] = "HIGH - More frequent irrigation needed"
        recommendations["drought_risk"] = "HIGH - Sandy soil dries quickly"
        recommendations["waterlogging_risk"] = "LOW"
    elif clay_020 is not None and clay_020 > 35:
        recommendations["texture_class"] = "Clayey"
        recommendations["irrigation_frequency"] = "LOW - Infrequent but deep irrigation"
        recommendations["waterlogging_risk"] = "HIGH - Poor drainage"
        recommendations["drought_risk"] = "LOW"
        recommendations["irrigation_depth"] = "Deep (75-100mm), less frequent"
    else:
        # Default moderate recommendations
        recommendations["texture_class"] = "Loamy/Unknown"
        recommendations["irrigation_frequency"] = "Standard - Moderate frequency"
        recommendations["waterlogging_risk"] = "Low-Moderate"
        recommendations["drought_risk"] = "Low-Moderate"
    
    # Bulk density (compaction)
    bd_020 = next(
        (b["value"] for b in extracted_soil["soil_physical"].get("bulk_density", []) 
         if b["depth"] == "0-20"), 
        None
    )
    if bd_020 is not None:
        if bd_020 > 1.4:
            recommendations["compaction_issue"] = True
            recommendations["irrigation_frequency"] = "Check drainage — soil may be compacted"
    
    return recommendations
