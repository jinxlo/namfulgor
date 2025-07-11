import re
import json
import os

# -------- CONFIG -------- #
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = THIS_DIR
BATTERIES_MASTER_JSON_PATH = os.path.join(DATA_DIR, "batteries_master_data.json")
OUTPUT_FITMENTS_JSON_PATH = os.path.join(DATA_DIR, "vehicle_fitments_data.json")
ERROR_LOG_PATH = os.path.join(DATA_DIR, "fitments_parse_errors.json")

MODEL_CODE_CANONICAL_MAP = {}
VALID_CANONICAL_MODELS = set()

def normalize(code):
    c = code.replace(" ", "").upper()
    return [c, c.replace("-", "").replace("/", "")]

# -------- LOAD CANONICAL MODELS -------- #
if os.path.exists(BATTERIES_MASTER_JSON_PATH):
    with open(BATTERIES_MASTER_JSON_PATH, 'r', encoding='utf-8') as f:
        master_data = json.load(f)
    for bat in master_data:
        brand = bat["brand"].replace(" ", "").upper()
        canonical = bat["model_code"]
        orig = bat.get("original_input_model_code", "")
        for code in set([canonical, orig]):
            if code and isinstance(code, str):
                for variant in normalize(code):
                    MODEL_CODE_CANONICAL_MAP[(brand, variant)] = canonical
        VALID_CANONICAL_MODELS.add((brand, canonical.strip()))
else:
    print(f"❌ batteries_master_data.json not found at {BATTERIES_MASTER_JSON_PATH}")
    exit(1)

# -------- MANUAL MAPPINGS -------- #
# >>> This is where you add as you review your error logs. <<<
# All values must match a model_code in your price list.

MODEL_CODE_CANONICAL_MAP.update({
    # Fulgor
    ("FULGOR", "F22NF700"): "22NF-700",
    ("FULGOR", "F86800"): "86-800",
    ("FULGOR", "F34M900"): "34M-900",
    ("FULGOR", "F22FA800"): "22FA-800",
    ("FULGOR", "F41FXR900"): "41FXR-900",
    ("FULGOR", "F4D1250"): "4D-1250",
    ("FULGOR", "F8D1500"): "8D-1500",
    ("FULGOR", "NS40"): "NS40-670",
    ("FULGOR", "41MR"): "41MR-900",
    ("FULGOR", "30HC1100"): "30H-1100",
    ("FULGOR", "F41MR900"): "41MR-900",
    ("FULGOR", "41M"): "41M-900",  # Only if you have 41M-900 in price list
    ("FULGOR", "F27XR950"): "27XR-900",
    ("FULGOR", "27XR950"): "27XR-900",
    ("FULGOR", "27R950"): "27R-900",
    ("FULGOR", "41MR900AGM"): "41MR-900AGM",  # Only if 41MR-900AGM exists

    # Black Edition
    ("BLACKEDITION", "BN22NF800"): "22NF-800",
    ("BLACKEDITION", "F86800"): "86-800",
    ("BLACKEDITION", "F341000"): "34-1000",
    ("BLACKEDITION", "F22FA800"): "22FA-800",
    ("BLACKEDITION", "F41FXR900"): "41FXR-900",
    ("BLACKEDITION", "BN94R1100"): "94R-1100",
    ("BLACKEDITION", "F94R1100"): "94R-1100",
    ("BLACKEDITION", "94R"): "94R-1100",
    ("BLACKEDITION", "F"): "94R-1100",  # Only if your error log confirms it
    ("BLACKEDITION", "94R1100AGM"): "94R-1100AGM",  # Only if exists

    # Mac/Optima (add more as needed)
    # ("MAC", "SOMEVARIANT"): "CANONICAL",
    # ("OPTIMA", "SOMEVARIANT"): "CANONICAL",
})

def clean_and_get_canonical(brand_name, raw_code_from_text, vehicle_info_for_log, error_logs_list):
    lookup_brand = brand_name.replace(" ", "").upper()
    variants = normalize(raw_code_from_text)
    canonical_model = None
    for v in variants:
        if (lookup_brand, v) in MODEL_CODE_CANONICAL_MAP:
            canonical_model = MODEL_CODE_CANONICAL_MAP[(lookup_brand, v)]
            break
    if canonical_model:
        if VALID_CANONICAL_MODELS and (lookup_brand, canonical_model) not in VALID_CANONICAL_MODELS:
            error_logs_list.append({
                "vehicle_info": vehicle_info_for_log,
                "reason": f"VALIDATION WARNING: Canonical model ('{brand_name}', '{canonical_model}') not found in master data."
            })
        return {"brand": brand_name, "model_code": canonical_model}
    else:
        if raw_code_from_text:
            error_logs_list.append({
                "vehicle_info": vehicle_info_for_log,
                "reason": f"MAPPING WARNING: No canonical mapping for (Brand: '{brand_name}', Raw: '{raw_code_from_text}', Normalized: '{'/'.join(variants)}')"
            })
        return None

def extract_models_from_brand_segment(brand_name, segment_text, vehicle_info_for_log, error_logs_list):
    segment_cleaned_of_prices = re.sub(r"priced at \s*\$[\d\.]+", "", segment_text, flags=re.IGNORECASE)
    potential_raw_codes = re.findall(
        r'\b([A-Z0-9]+(?:[\-\/][A-Z0-9\/]+)*[A-Z0-9]|[A-Z]+[0-9]+[A-Z0-9\-]*|[0-9]+[A-Z]+[A-Z0-9\-]*|NS40)\b',
        segment_cleaned_of_prices, re.IGNORECASE)
    extracted_batteries = []
    seen_in_segment = set()
    ignore_words = {"THE", "IN", "IS", "ARE", "BRAND", "MODELS", "MODEL", "PRICED", "AT", "AND",
                    "OPTION", "OPTIONS", "AVAILABLE", "WHICH", "ONLY", "ONE", "THERE",
                    "ADDITIONAL", "NO", "FOR", "PRICES", "BATTERIES", "BATTERY"}
    for raw_code in potential_raw_codes:
        if raw_code.upper() in ignore_words or raw_code.isdigit():
            continue
        if len(raw_code) < 3 and raw_code.upper() != "NS40":
            continue
        canonical_entry = clean_and_get_canonical(brand_name, raw_code, vehicle_info_for_log, error_logs_list)
        if canonical_entry:
            entry_tuple = (canonical_entry["brand"], canonical_entry["model_code"])
            if entry_tuple not in seen_in_segment:
                extracted_batteries.append(canonical_entry)
                seen_in_segment.add(entry_tuple)
    return extracted_batteries

def parse_vehicle_fitments(data_text):
    results = []
    error_logs = []
    vehicle_entries_text = [entry.strip() for entry in data_text.strip().split("\n\n") if entry.strip()]
    for entry_idx, entry_text in enumerate(vehicle_entries_text):
        first_line = entry_text.split('\n')[0].strip()
        vehicle_info_for_log = f"Entry #{entry_idx+1}: {first_line[:100]}..."
        car_match = re.match(r"^(.*?)\s+([A-Z0-9\s\/\.\-\(\)\']+)[\s\(]+\((\d{4})(?:[\/\-](\d{4}))?\):(.*)", first_line)
        if not car_match:
            error_logs.append({"vehicle_info": vehicle_info_for_log, "reason": "REGEX FAIL: Could not parse vehicle make/model/year from first line."})
            continue
        groups = car_match.groups()
        vehicle_make = groups[0].strip()
        vehicle_model_raw = groups[1].strip()
        year_start = int(groups[2])
        year_end = int(groups[3]) if groups[3] else year_start
        details_text_on_first_line = groups[4].strip()
        full_details_text = details_text_on_first_line
        if '\n' in entry_text:
            full_details_text += " " + " ".join(line.strip() for line in entry_text.split('\n')[1:] if line.strip())
        full_details_text = re.sub(r'\s+', ' ', full_details_text).strip()
        vehicle_model = re.sub(r'\s*\(.*?\)\s*$', '', vehicle_model_raw).strip()
        if not vehicle_model: vehicle_model = vehicle_model_raw
        print(f"\nProcessing: {vehicle_make} | {vehicle_model} | ({year_start}-{year_end})")
        all_compatible_batteries_for_vehicle = []
        brand_search_order = ["Fulgor", "Black Edition", "Mac", "Optima"]
        remaining_text_to_parse = full_details_text
        for brand_name in brand_search_order:
            brand_section_regex = re.compile(
                rf"(?i)(?:In\s+the\s+)?{brand_name}\s+brand\b(.*?)(?=\s+(?:In\s+the\s+)?(?:Fulgor|Black\s+Edition|Mac|Optima)\s+brand|\s*$)",
                re.DOTALL
            )
            match = brand_section_regex.search(remaining_text_to_parse)
            if match:
                segment_for_brand = match.group(1).strip()
                segment_for_brand = re.sub(
                    r"^(?:,|\s)*(?:are\s+the|is\s+(?:the\s+only\s+one\s+option\s+available(?:,\s*which\s+is)?)?\s*(?:the)?)?\s*", "",
                    segment_for_brand, flags=re.IGNORECASE).strip()
                print(f"  Found section for '{brand_name}'. Segment: '{segment_for_brand[:70]}...'")
                codes = extract_models_from_brand_segment(brand_name, segment_for_brand, vehicle_info_for_log, error_logs)
                all_compatible_batteries_for_vehicle.extend(codes)
            elif f"no options available in the {brand_name} brand" in full_details_text.lower() or \
                 (brand_name == "Black Edition" and "no options available in the Black Edition" in full_details_text.lower()):
                 print(f"  Explicitly no options for {brand_name} for {vehicle_make} {vehicle_model}.")
        unique_compatible_batteries = []
        seen_batteries_for_vehicle = set()
        for bat in all_compatible_batteries_for_vehicle:
            entry_tuple = (bat["brand"], bat["model_code"])
            if entry_tuple not in seen_batteries_for_vehicle:
                unique_compatible_batteries.append(bat)
                seen_batteries_for_vehicle.add(entry_tuple)
        if not unique_compatible_batteries and \
           "no options available in either" not in full_details_text.lower() and \
           "There are no additional options available" not in full_details_text:
            any_brand_had_no_options_explicitly = False
            for brand_name_check in brand_search_order:
                if f"no options available in the {brand_name_check} brand" in full_details_text.lower():
                    any_brand_had_no_options_explicitly = True
                    break
            if not any_brand_had_no_options_explicitly:
                error_logs.append({
                    "vehicle_info": vehicle_info_for_log,
                    "reason": f"NO MODELS EXTRACTED (and text did not state 'no options for all/any brands'). Review parsing. Full Details: '{full_details_text[:150]}...'"
                })
        car_json_output = {
            "vehicle_make": vehicle_make,
            "vehicle_model": vehicle_model,
            "year_start": year_start,
            "year_end": year_end,
            "compatible_battery_model_codes": unique_compatible_batteries
        }
        results.append(car_json_output)
    return results, error_logs

# -------- MAIN EXECUTION -------- #
if __name__ == "__main__":
    car_data_input = """
  ALFA ROMEO 145 (1996/2001): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 146 (1996/2001): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 147 (2001/2010): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 155 (1992/1997): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 156 (1997/2006): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 164 (1992/1998): The available battery models in the Fulgor brand are the 24R-900 priced at $118 and the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140.

ALFA ROMEO 166 (1998/2007): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO 33 (1990/2004): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO GT (2003/2010): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO GTV (1995/2005): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ALFA ROMEO SPIDER (1994/2005): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

ACURA INTEGRA (1992/2001): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

ACURA LEGEND (1990/1995): The available battery models in the Fulgor brand are the F86-800 priced at $95 and the F34M-900 priced at $109. In the Black Edition brand, the available batteries are the F86-800 priced at $95 and the F34-1000 priced at $131.


ACURA LEGEND (1990/1995): The available battery models in the Fulgor brand are the F86-800 priced at $95 and the F34M-900 priced at $109. In the Black Edition brand, the available batteries are the F86-800 priced at $95 and the F34-1000 priced at $131.



AUDI A3 (1998/2007): The available battery models in the Fulgor brand are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116.

AUDI A8 (2004/2006): The available battery models in the Fulgor brand are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116.

AUDI A4 (2002/2008): The available battery models in the Fulgor brand are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116.

AUDI Q7 (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F41FXR-900 priced at $116 and the BN94R-1100 priced at $168.

AUDI A6 (2004/2006): The available battery models in the Fulgor brand are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F22FA-800 priced at $95 and the F41FXR-900 priced at $116.



BLUE BIRD AUTOBUSES DIESEL (1973/1993): The available battery models in the Fulgor brand are the F4D-1250 priced at $245 and the F8D-1500 priced at $305. There are no options available in the Black Edition brand.

BLUE BIRD AUTOBUSES A GASOLINA (1971/1993): The available battery models in the Fulgor brand are the F4D-1250 priced at $245 and the F8D-1500 priced at $305. There are no options available in the Black Edition brand.




BAW LA BESTIA (2022/2024): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

BAW MPV M7 VAN/CARGO (2022/2024): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

BAW CALORIE F7 PICKUP (2022/2024): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.


BMW SERIE 3 (1992/2009): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW 131I (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW SERIE 5 (1992/2010): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW 135I (1998/2009): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW X3 (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW 318I (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW X5 (2000/2010): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F41FXR-900 priced at $116 and the BN94R-1100 priced at $168.

BMW 525I (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW X6 (2000/2010): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F41FXR-900 priced at $116 and the BN94R-1100 priced at $168.

BMW 530I (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW X7 (2000/2010): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F41FXR-900 priced at $116 and the BN94R-1100 priced at $168.

BMW Z3 (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW 830I (2000/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, the available batteries are the F41FXR-900 priced at $116 and the BN94R-1100 priced at $168.

BMW Z4 (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

BMW 116I (1998/2008): There is only one option available in the Fulgor brand, which is the F41FXR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.


BUICK CENTURY (1983/1996): The available battery models in the Fulgor brand are the F86-800 priced at $95 and the F34M-900 priced at $109. In the Black Edition brand, the available batteries are the F86-800 priced at $95 and the F34-1000 priced at $131.

BUICK LE SABRE (1992/1999): The available battery models in the Fulgor brand are the F86-800 priced at $95 and the F34M-900 priced at $109. In the Black Edition brand, the available batteries are the F86-800 priced at $95 and the F34-1000 priced at $131.

BYD F3 (2008): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

BYD FLYER (2006/2007): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.




CHANA SUPER VAN (2007/2009): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHANA PICK UP (2008/2009): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.




CHANGHE IDEAL (2007): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHANGAN ALSVIN CS15 (2022/2024): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.

CHANGAN HUNTER 2.0 TURBO GASOLINA (2022/2024): There are no options available in the Fulgor brand. In the Black Edition brand, there is only one option available, which is the F94R-1100. There are no additional options available.

CHANGAN BENNI E-STAR (2023/2024): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHANGAN CS55 (2022/2024): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.

CHANGAN HUNTER 2.5 DIESEL (2022/2024): There is only one option available in the Fulgor brand, which is the F27XR-950. There are no options available in the Black Edition brand.

CHANGAN CS35 PLUS (2022/2024): There is only one option available in the Fulgor brand, which is the F86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F86-800 priced at $95. There are no additional options available.

CHANGAN KAICENE (2022/2024): There is only one option available in the Fulgor brand, which is the F27XR-950. There are no options available in the Black Edition brand.


CHERY ARAUCA (2012/2016): The available battery models in the Fulgor brand are the F36FP-700 priced at $82 and the F22FA-800 priced at $95. In the Black Edition brand, the available batteries are the F36FP-700 priced at $82 and the F22FA-800 priced at $95.

CHERY X1 (2013/2016): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHERY ARAUCA (2019): The available battery models in the Fulgor brand are the NS40 and the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHERY TIGGO 4/4PRO (2022/2024): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.

CHERY COWIN (2008): The available battery models in the Fulgor brand are the F36FP-700 priced at $82 and the F22FA-800 priced at $95. In the Black Edition brand, the available batteries are the F36FP-700 priced at $82 and the F22FA-800 priced at $95.

CHERY TIGGO 7 PRO (2022/2024): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.

CHERY GRAND TIGGO (2014/2015): The available battery models in the Fulgor brand are the F22FA-800 priced at $95 and the F34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the F22FA-800 priced at $95. There are no additional options available.

CHERY TIGGO 8 PRO (2022/2024): There is only one option available in the Fulgor brand, which is the F41MR-900. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

CHERY GRAND TIGGO (2016): There is only one option available in the Fulgor brand, which is the F41MR-900. In the Black Edition brand, there is only one option available, which is the F41FXR-900 priced at $116. There are no additional options available.

CHERY TIUNA X5 (2015/2016): There is only one option available in the Fulgor brand, which is the F34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the F34-1000 priced at $131. There are no additional options available.

CHERY ORINOCO (2012/2018): The available battery models in the Fulgor brand are the F36FP-700 priced at $82 and the F22FA-800 priced at $95. In the Black Edition brand, the available batteries are the F36FP-700 priced at $82 and the F22FA-800 priced at $95.

CHERY VAN H5 (2016): There is only one option available in the Fulgor brand, which is the F22FA-800 priced at $95. There are no options available in the Black Edition brand.

CHERY QQ (2008/2009): The available battery models in the Fulgor brand are the NS40 and the F22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the BN22NF-800 priced at $100. There are no additional options available.

CHERY GRAND TIGER (2012/2013): There is only one option available in the Fulgor brand, which is the F34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the F34-1000 priced at $131. There are no additional options available.

CHERY TIGGO (2006/2009): There is only one option available in the Fulgor brand, which is the F34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the F34-1000 priced at $131. There are no additional options available.

CHERY ZOYTE (2008): There is only one option available in the Fulgor brand, which is the F22NF-700 priced at $93. There are no options available in the Black Edition brand.

CHERY WIND CLOUD (2006/2007): There is only one option available in the Fulgor brand, which is the F86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the F86-800 priced at $95. There are no additional options available.


CHEVROLET ASTRA (2002/2007): The available battery models in the Fulgor brand are the 41MR priced at $116 and the 22FA-800 priced at $95. There are no options available in the Black Edition brand.

CHEVROLET AUTOBUSES (1955/2000): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

CHEVROLET AVALANCHE (2005/2008): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET AVEO (2005/2010): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 41M priced at $116. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 41FXR-900 priced at $116.

CHEVROLET AVEO LT GNV (2011/2014): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. There are no options available in the Black Edition brand.

CHEVROLET BLAZER (1990/2003): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET C10 (1956/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C30 (1980/1991): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C60 (1956/1999): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C70 (2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C3500 (1956/1999): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C3500 (2000/2005): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET C3500 (2011/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET CAMARO SS LT1 V8 (2010/2018): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET CAMARO (1988/2002): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET CAPRICE (1973/1998): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET CAPTIVA (2007/2008): The available battery models in the Fulgor brand are the 24R-900 priced at $118 and the 41MR priced at $116. In the Black Edition brand, the available batteries are the 41FXR-900 priced at $116 and the 24MR-1100 priced at $140.

CHEVROLET CAVALIER (1992/2005): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET CENTURY (1983/1996): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET CELEBRITY (1983/1991): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET CHEVETTE (1981/1996): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET CHEVY C2 (2008/2011): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.


CHEVROLET SILVERADO (1992/1999): There is only one option available in the Fulgor brand, which is the 41MR priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

CHEVROLET CHEYENNE/SILVERADO (2000/2007): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET CHEYENNE/SILVERADO (2008/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET CORSA (1996/2006): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET CORSICA (1990/1996): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET CRUZE (2011/2013): There is only one option available in the Fulgor brand, which is the 41MR priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

CHEVROLET CORVETTE STRINGRAY Z51 2LT 6.2L (2015/2018): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET COLORADO (2007/2008): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. There are no options available in the Black Edition brand.

CHEVROLET EPICA (2007/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET ESTEEM (2007/2011): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET EXZ (2008/2015): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

CHEVROLET EXR (2008/2015): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

CHEVROLET FSR (2014): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

CHEVROLET FSR (2006/2011): The available battery models in the Fulgor brand are the 30HC-1100 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

CHEVROLET FVR (2006/2011): The available battery models in the Fulgor brand are the 30HC-1100 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

CHEVROLET GRAN VITARA XL5 4CIL (2000/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

CHEVROLET GRAN VITARA XL5 6CIL (2000/2008): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET GRAN VITARA XL7 (2003/2007): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET GRAND BLAZER (1992/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET IMPALA SS (2007/2008): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET IMPALA (2000/2005): There is only one option available in the Fulgor brand, which is the 41MR priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

CHEVROLET JIMMY (2000/2003): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. There are no options available in the Black Edition brand.

CHEVROLET KODIAK 157/175 (2002/2010): The available battery models in the Fulgor brand are the 30HC-1100 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

CHEVROLET KODIAK 229 (1992/2010): The available battery models in the Fulgor brand are the 30HC-1100 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

CHEVROLET LUMINA (1996/1999): There is only one option available in the Fulgor brand, which is the 41MR priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

CHEVROLET LUV 4 CIL 2.3L (2001/2006): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

CHEVROLET LUV D/MAX 6 CIL GNV (2009/2015): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET LUV D/MAX 6 CIL (2001/2006): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET MALIBU (1969/1984): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. There are no options available in the Black Edition brand.

CHEVROLET MERIVA (2007/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET MONTANA (2005/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

CHEVROLET MONTECARLO (1978/2005): The available battery models in the Fulgor brand are the 34M-900 priced at $109 and the 34-1000 priced at $131. There are no options available in the Black Edition brand.

CHEVROLET MONZA (1985/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET NHR (1992/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET NOVA (1971/1977): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET NPR 24 (1992/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET NPR TURBO 12V (1992/2015): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

CHEVROLET NPR AUTOBUS (2005/2007): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

CHEVROLET ONIX (2018/2023): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET OPTRA ADVANCE (2004/2007): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

CHEVROLET OPTRA DESING / HATCHBACK (2007/2008): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

CHEVROLET OPTRA LIMITED (2008/2012): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

CHEVROLET OPTRA DESING (2009/2011): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

CHEVROLET ORLANDO (2011/2013): There is only one option available in the Fulgor brand, which is the 41MR priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

CHEVROLET S/10 (1990/1999): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET SPARK (2006/2014): The available battery models in the Fulgor brand are the NS40/22NF-700 and the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

CHEVROLET SPARK GT (2017/2021): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

CHEVROLET SUNFIRE (1995/2003): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET SUPER CARRY (1992/2007): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

CHEVROLET SWIFT (1991/1997): The available battery models in the Fulgor brand are the 22NF-700 priced at $93 and the 36FP-700 priced at $82. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22NF-800 priced at $100.

CHEVROLET TAHOE (2007/2014): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

CHEVROLET TRAIL BLAZER (2002/2008): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET VANS EXPRESS (2007/2008): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHEVROLET VECTRA (1992/1995): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

CHEVROLET VITARA (2004/2007): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHEVROLET VITARA (3 PUERTAS) (1997/2003): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 86-800 priced at $95. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 86-800 priced at $95.

CHEVROLET WAGON R (1999/2004): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.


CHINOS GANDOLAS (2012): There is only one option available in the Fulgor brand, which is the 4D-1250. There are no options available in the Black Edition brand.

CHRYSLER CAMIONES (1956/1999): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

CHRYSLER 300C (2007/2008): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

CHRYSLER 300M (1998/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHRYSLER GRAND CARAVAN (1992/2006): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHRYSLER LE BARON (1978/1995): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHRYSLER JOURNEY (2009/2019): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHRYSLER NEON (1997/2000): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

CHRYSLER PT CRUISER (2002/2008): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHRYSLER SEBRING (2005/2009): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHRYSLER SPIRIT (1989/1995): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CHRYSLER STRATUS (1996/2001): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

CHRYSLER TOWN & COUNTRY (1991/2007): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

CITROËN C3 (2004/2008): The available battery models in the Fulgor brand are the 36FP-700 and the 22FA-800. In the Black Edition brand, the available batteries are the 36FP-700 and the 22FA-800.

CITROËN C4 (2005/2008): The available battery models in the Fulgor brand are the 36FP-700 and the 22FA-800. In the Black Edition brand, the available batteries are the 36FP-700 and the 22FA-800.

DAEWOO CIELO (1995/2002): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

DAEWOO DAMAS (1993/2002): There is only one option available in the Fulgor brand, which is the NS40 priced at $88. There are no options available in the Black Edition brand.

DAEWOO ESPERO (1994/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

DAEWOO LABO (1995/2002): The available battery models in the Fulgor brand are the NS40 priced at $88 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DAEWOO LANOS (1997/2002): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DAEWOO LEGANZA (1998/2002): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DAEWOO LUBLIN II (1997/1998): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DAEWOO MATIZ (1998/2002): The available battery models in the Fulgor brand are the NS40 priced at $88 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DAEWOO MUSSO (1998/2000): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

DAEWOO NUBIRA (1998/2002): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

DAEWOO PRINCE (1997/1998): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DAEWOO RACER (1993/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

DAEWOO SUPER SALOM (1996/1998): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DAEWOO TACUMA (2000/2002): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DAEWOO TICO (2000/2002): There is only one option available in the Fulgor brand, which is the NS40 priced at $88. There are no options available in the Black Edition brand.


DSFK GLORY 500 TURBO DYNAMIC (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

DSFK GLORY 600 (2022/2024): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DSFK C35/C37 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK C31/Y32 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK K01S (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK SHINERGY X30 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

Repetition (for completeness):

DSFK GLORY 500 TURBO DYNAMIC (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

DSFK GLORY 600 (2022/2024): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DSFK C35/C37 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK C31/Y32 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK K01S (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DSFK SHINERGY X30 (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

DODGE ASPEN (1977/1980): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE BRISA (2002/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

DODGE CALIBER (2007/2012): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DODGE CARAVAN (1984/2003): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE CHARGER DAYTONA (2015/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

DODGE CHALLENGER (2008/2018): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 41FXR-900 priced at $116 and the 94R-1100 priced at $168.

DODGE DAKOTA (2006/2009): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

DODGE DART (1963/1982): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE INTREPID (1993/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE NEON (2000/2005): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

DODGE STEALTH (1990/1992): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE RAM 2500 (1997/2000): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DODGE RAM 2500 (2000/2009): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

DODGE VAN RAM (1956/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

ENCANVA EP-1000 DIESEL (2022/2024): The available battery models in the Fulgor brand are the 34M-900 priced at $109 and the 27XR-950 priced at $131. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

ENCANVA ET-5 (2022/2024): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

ENCANVA ET-40 (2022/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

ENCANVA ENT-510 (1980/1995): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

ENCANVA ENT-610 32PTOS (1995/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

ENCANVA ENT-900 26PTOS (2000/2024): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

ENCANVA ENT-3300 (2022/2024): The available battery models in the Fulgor brand are the 4D-1250 priced at $245 and the 8D-1500 priced at $305. There are no options available in the Black Edition brand.

DONGFENG AEOLUS AX7 PRO (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

DONGFENG S30 (2011/2013): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

DONGFENG ZNA RICH (2012): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

DONGFENG DOULIKA 5T, 7T (2012/2015): The available battery models in the Fulgor brand are the 27XR-950 priced at $131 and the 27R-950 priced at $131. There are no options available in the Black Edition brand.

DONGFENG HAIMA 7 (2012/2014): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

DONGFENG JIMBA (2012/2015): There is only one option available in the Fulgor brand, which is the 27R-950 priced at $131. There are no options available in the Black Edition brand.

DONGFENG RICH 6 DIESEL/GASOLINA (2016/2024): The available battery models in the Fulgor brand are the 27XR-950 priced at $131 and the 24MR-1100 priced at $140. There are no options available in the Black Edition brand.

DONGFENG XIAOBA (2012/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

FIAT 147 (1981/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT 500 ELECTRICO (2017): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT 500 GASOLINA (2015/2018): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT ADVENTURE (1990/2014): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT ARGO (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT COUPÉ (1995/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT CRONOS (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT DUCATO (2006/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

FIAT FIORINO (1981/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT IDEA (2007/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT MAREA (1999/2002): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT MOBIL (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT PALIO (1997/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT PREMIO (1985/1999): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT PUNTO (2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT REGATA (1984/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT RITMO (1984/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT SIENA (1987/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT SPAZIO (1981/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT STILO (2006/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT STRADA (2006/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT TEMPRA (1988/1999): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT TUCAN (1981/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT UNO (1981/1992): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT UNO (2000/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FIAT UNO A/A (1993/1999): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FRIEGHTLINER 112 (2000/2010): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FRIEGHTLINER COLUMBIA CL (2000/2010): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FRIEGHTLINER M2-106 (2000/2010): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FOTON AUMARK E60 (2022/2024): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

FOTON AUMARK S E85 (2022/2024): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

FOTON AUMAN EST (2022/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

FOTON AUMAN GTL (2022/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

FOTON VIEW C2 (2023/2024): There is only one option available in the Fulgor brand, which is the 41M-900. In the Black Edition brand, there is only one option available, which is the 41XR-900 priced at $116. There are no additional options available.

FOTON THM5H (2023/2024): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

FORD AUTOBUSES (1956/2000): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

FORD BRONCO 6 CIL/8 CIL (1989/1997): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD BRONCO SPORT (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD CAMIONES (1987/1999): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FORD CARGO 815 / 817 (2003/2011): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FORD CARGO 1721 (2004/2008): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FORD CARGO 1721 (2008/2015): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

FORD CARGO 2632 (2005/2014): The available battery models in the Fulgor brand are the 4D-1250 priced at $245 and the 8D-1500 priced at $305. There are no options available in the Black Edition brand.

FORD CARGO 4432 (2005/2014): The available battery models in the Fulgor brand are the 4D-1250 priced at $245 and the 8D-1500 priced at $305. There are no options available in the Black Edition brand.

FORD CARGO 4532 (2005/2014): The available battery models in the Fulgor brand are the 4D-1250 priced at $245 and the 8D-1500 priced at $305. There are no options available in the Black Edition brand.

FORD CONQUISTADOR (1982/2000): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD CORCEL (1983/1987): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD COUGAR (1980/1987): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

FORD DEL REY (1983/1987): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FORD ECONOLINE (1977/1999): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD ECOSPORT (2004/2008): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD ECOSPORT TITANIUM (2015/2022): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

FORD ESCAPE (2006/2007): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

FORD ESCORT (1988/2000): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD EXPEDITION (2000/2008): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

FORD EXPEDITION LIMITED (2023/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100AGM. There are no options available in the Fulgor brand.

FORD EXPLORER (1995/2004): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD EXPLORER SPORT TRACK (2005/2015): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

FORD EXPLORER ST (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900AGM. There are no options available in the Black Edition brand.

FORD F/30 (TRITON) (2000/2010): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

FORD F/350 (SUPER DUTY) (2011/2014): The available battery models in the Fulgor brand are the 65-1100 priced at $150 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FORD F750 (1965/2000): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

FORD F7000/F8000 (1980/2002): There is only one option available in the Fulgor brand, which is the 30HC-1100 priced at $180. There are no options available in the Black Edition brand.

FORD FESTIVA (1992/2002): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FORD FIESTA (1996/2010): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD FOCUS (2000/2009): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD FORTALEZA (1997/2008): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD FX4 (2008/2009): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

FORD FUSION (2007/2014): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

FORD GRANADA (1980/1985): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

FORD GRAND MARQUIS (1992/1997): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD KA (2004/2007): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

FORD LASER (1992/2004): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

FORD LTD (1973/1984): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD LINCOLN (1992/1996): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD MUSTANG (1964/1973): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD MUSTANG (1974/1978): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD MUSTANG (1979/1993): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD MUSTANG (1994/2004): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD MUSTANG (2005/2014): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD MUSTANG (2015/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD RANGER (1997/2008): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD RAPTOR (2014/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100. There are no options available in the Fulgor brand.

FORD RAPTOR XLS GASOLINA (2019/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100. There are no options available in the Fulgor brand.

FORD RANGER XLT DIESEL (2019/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100. There are no options available in the Fulgor brand.

FORD RANGER XLT GASOLINA (2019/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD SIERRA (1985/1998): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD SPORT TRAC (2005/2011): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

FORD TRANSIT VANS XLT (2016/2023): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD THUNDERBIRD (1979): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD ZEPHYR (1980/1985): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD TAURUS (1995/2001): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

FORD TERRITORY (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

FORD TRACER (1992/1996): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

GREAT WALL DEER (2006/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

GREAT WALL HOVER (2007/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

GREAT WALL PERI (2007/2010): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

GREAT WALL SAFE (2006/2008): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

HAFEI LOBO (2007): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

HAFEI MINYI (2007): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HAFEI ZHONGYI (2007): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HINO BUS (2012/2017): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

HONDA ACCORD 4 CIL (1990/1998): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HONDA ACCORD 4 CIL (2000/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HONDA ACCORD 6 CIL (2000/2008): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HONDA ACCORD SPORT (2018/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HONDA CIVIC (1990/1995): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CIVIC (1996/2000): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CIVIC (2001/2005): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

HONDA CIVIC EMOTION (2006/2011): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CIVIC EVOLUTION (2011/2015): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CIVIC SPORT/TURBO (2016/2021): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CR/V (2000/2008): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA CRX (1992/1995): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA FIT (2002/2008): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HONDA LEGEND (1990/1995): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

HONDA ODYSSEY (1997/2007): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HONDA PILOT (2006/2007): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HONDA PRELUDE (1992/1996): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

HONDA VIGOR (1992/1995): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

HUMMER H2 (2003/2007): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

HUMMER H3 (2003/2007): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

HYUNDAI ACCENT (1997/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

HYUNDAI ACCENT (2012/2017): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

HYUNDAI ATOS PRIME (2006/2008): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HYUNDAI ELANTRA (1992/2001): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HYUNDAI ELANTRA (2002/2018): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HYUNDAI ELANTRA (2022/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HYUNDAI EXCEL (1992/1999): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

HYUNDAI GALLOPER (1997/2001): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HYUNDAI GETZ (2007/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

HYUNDAI GETZ GLS -GNV (2011/2012): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

HYUNDAI Gi10 (2022/2024): There is only one option available in the Fulgor brand, which is the NS40 (BORNE FINO). There are no options available in the Black Edition brand.

HYUNDAI H/100 (1997/1999): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

HYUNDAI H1 (2007/2012): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

HYUNDAI HD36L (2022/2024): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

HYUNDAI MATRIX (1997/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

HYUNDAI PALISADE (2022/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100. There are no options available in the Fulgor brand.

HYUNDAI SANTA FÉ (2001/2019): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HYUNDAI SONATA (1992/2001): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HYUNDAI SONATA (2002/2016): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

HYUNDAI TIBURON (COUPE) (1997/2007): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HYUNDAI TUCSON (2005/2012): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

HYUNDAI TUCSON (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

HYUNDAI VELOSTER (2012/2016): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

IKCO DENA + (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

IKCO TARA (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

INTERNATIONAL 1700 (1971/1990): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

INTERNATIONAL 1800 (1980/1990): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

INTERNATIONAL 2050 (1971/1990): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

INTERNATIONAL 5000 (1980/1991): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

INTERNATIONAL 5070 (1971/1990): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

INTERNATIONAL 7600 (2012): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

ISUZU AMIGO (1992/2000): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

ISUZU CARIBE 442 (1982/1993): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

ISUZU RODEO (1991/2000): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

ISUZU SIDEKICK (1992/1994): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

ISUZU TROOPER (1992/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

IVECO DAILY LIVIANOS (1998/2011): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

IVECO DAILY GNV (2011/2012): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

IVECO POWER DAILY (2012/2016): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

IVECO VERTIS (2012/2016): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

IVECO NEW STRALIS (1983/2011): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

IVECO SERIE EUROTRAKKER (1983/2011): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

IVECO SERIE EURO TECTOR (1998/2011): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

IVECO SERIE EUROCARGO (1989/2003): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

IVECO SERIE STRALIS (1983/2011): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC HFC1030P (X100) (2023/2024): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

JAC 1040/1042 (2015/2024): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

JAC HFC1071L1K-N75S (2023/2024): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

JAC HFC1090L1KT-N90L (2023/2024): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

JAC BUFALO HFC1131KR1 (2023/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC XL HFC1235K3R1L (2023/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC HFC1254KR1 (2023/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC MINERO HFC3255K1R1/HFC3310K3R1 (2023/2024): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

JAC HFC4160 (2023/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC HFC4251KR1K3/HFC4251KR1 (2023/2024): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC LA VENEZOLANA GASOLINA T6 (2018/2024): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JAC LA VENEZOLANA DIESEL T6 (2018/2024): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JAC EXTREME FC1037D3ESV T8 (2023/2024): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JAC AVENTURA GASOLINA T9 (2023/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. There are no options available in the Black Edition brand.

JAC AVENTURA DIESEL T9 (2023/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. There are no options available in the Black Edition brand.

JAC ARENA JS2 (2023/2024): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

JAC TEPUY JS6 (2023/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

JAC SAVANNA JS8 PRO (2023/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

JAC J7/J7 PLUS (2023/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

JAC SUNRAY CARGO DIESEL (2023/2024): The available battery models in the Fulgor brand are the 34M-900 priced at $109 and the 27R-950. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

JAC SUNRAY PASAJEROS (2023/2024): The available battery models in the Fulgor brand are the 34M-900 priced at $109 and the 27R-950. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

JAC VAN M4 (2023/2024): There is only one option available in the Fulgor brand, which is the 41M-900. In the Black Edition brand, there is one option available, which is the 41XR-900 priced at $116. There are no additional options available.

JAC M4 CARGA (2023/2024): There is only one option available in the Fulgor brand, which is the 41M-900. In the Black Edition brand, there is one option available, which is the 41XR-900 priced at $116. There are no additional options available.

JAC EJS1 ELECTRICO (2023/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800. There are no additional options available.

JAC E40X ELECTRICO (2023/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800. There are no additional options available.

JAC K8 AUTOBUS 26 PUESTOS (2023/2024): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

JAC 1061 (2000/2015): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

JAC 1063 (2015/2017): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

JAC 1040 (2000/2015): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

JAC 4253 (2000/2015): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JAC 1134 (2015/2017): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

JEEP CHEROKEE XJ (1989/2002): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. There are no options available in the Black Edition brand.

JEEP CHEROKEE LIBERTY (2002/2007): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

JEEP CHEROKEE KK (2008/2014): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP CHEROKEE T270 RENEGADO SPORT (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 41FXR-900 priced at $116 and the 94R. There are no additional options available.

JEEP CJ / SERIES (1980/1990): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP COMANCHE (1986/1992): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP COMMANDER (2007/2010): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

JEEP COMPASS (2007/2012): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

JEEP COMPASS T270 (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 AGM. There are no options available in the Black Edition brand.

JEEP GRAND CHEROKEE LAREDO (1993/1998): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP GRAND CHEROKEE WJ (1999/2005): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP GRAND CHEROKEE WK (2006/2010): The available battery models in the Fulgor brand are the 34MR-900 priced at $109 and the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

JEEP GRAND CHEROKEE WK-2 (4G) (2011/2013): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

JEEP GRAND CHEROKEE OVERLAND (2023/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

JEEP GRAND WAGONEER (1979/1993): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP RENEGADE/WRANGLER (1995/2005): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

JEEP WRANGLER (1987/2002): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

JEEP RUBICON (2008/2019): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

JETOUR X70/X70 PLUS (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

JMC VIGUS (2023/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. There are no options available in the Black Edition brand.

KARRY PANEL/PASAJERO (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

KARRY YOKI (2022/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

KENWORTH TODOS (1980/2010): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

KIA CARENS (2000/2007): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

KIA CARNIVAL (2000/2004): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

KIA CARNIVAL (2023/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

KIA CERATO (2006/2009): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

KIA CERATO (2015): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

KIA OPTIMA (2005/2009): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

KIA PICANTO (2005/2009): There is only one option available in the Fulgor brand, which is the NS40 (BORNE FINO). There are no options available in the Black Edition brand.

KIA PICANTO (2023/2024): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

KIA PREGIO (2002/2010): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

KIA RIO (2000/2012): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

KIA RIO (2023/2024): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

KIA SEDONA (2000/2009): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

KIA SEPHIA (1999/2001): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

KIA SHUMA (2000/2002): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

KIA SORENTO (2004/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

KIA SORENTO (2023/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

KIA SPECTRA (2002/2003): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

KIA SPORTAGE (1999/2010): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

KIA SPORTAGE (2023/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

KIA SONET (2023/2024): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

KIA SOLUTO (2023/2024): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800. There are no additional options available.

KIA SELTOS (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

LADA MATRIOSKA (1992/1996): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

LADA NIVA (1992/1996): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

LADA SAMARA (1992/1996): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

LAND ROVER DEFENDER (1998/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

LAND ROVER DISCOVERY (1992/2001): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

LAND ROVER RANGE ROVER (1956/2019): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

LEXUS 300 (1991/1997): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS 400 (1991/1997): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

LEXUS LS (1989/2006): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS ES (1989/2006): The available battery models in the Fulgor brand are the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

LEXUS GS (1993/2011): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS GX460 (2020/2023): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS RX (1998/2008): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS LX (1996/2008): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

LEXUS LX 570 (2018/2023): The available battery models in the Fulgor brand are the 27R-950. In the Black Edition brand, there is one option available, which is the 94R-1100 priced at $168. There are no additional options available.

LIFAN 520 TALENT (2008/2009): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

LINCOLN TOWN CAR (1990/2010): The available battery models in the Fulgor brand are the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

LINCOLN NAVIGATOR (2006/2010): There is only one option available in the Fulgor brand, which is the 65-1100 priced at $150. There are no options available in the Black Edition brand.

MACK CHHD Y CHLD (1997/2005): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MACK GRANITE VISION (2004/2006): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MACK MIDLINER (1996/2005): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MACK CH-613 (1996/2002): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MACK SERIE R600 (1966/1996): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MACK RDHD Y RDLD (1989/2005): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MAXUS T60 (2022/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MAXUS D60 (2022/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

Mazda 3 (2005/2009): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

Mazda 5 (2005/2007): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

Mazda 6 (2004/2008): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

Mazda 323 (1992/2003): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

Mazda 626 (1992/2005): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 34-1000 priced at $131.

Mazda 929 (1992/1995): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

Mazda ALLEGRO (1994/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

Mazda B2600 (1992/2007): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

Mazda B400 (1998/2005): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

Mazda BT-50 (2008/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

MERCEDES BENZ AUTOBUSES (1958/1999): The available battery models in the Fulgor brand are the 30HC-1100 priced at $180 and the 31T-1100 priced at $183. There are no options available in the Black Edition brand.

MERCEDES BENZ E 190 (1991/1998): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MERCEDES BENZ E 300 (1991/1999): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MERCEDES BENZ ML 300 (2013/2018): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

MERCEDES BENZ 500SEL (1991/2016): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MERCEDES BENZ 600SEL (1991/2017): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MERCEDES BENZ 711 (2007/2011): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

MERCEDES BENZ LS 1634 (2005/2009): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

MERCEDES BENZ LS 2640 (2005/2010): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

MERCEDES BENZ MB 303 (1990/2012): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

MERCEDES BENZ CLASE A (2001/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MERCEDES BENZ CLASE B 200 (2006/2012): The available battery models in the Fulgor brand are the 86-800 priced at $95 and the 34M-900 priced at $109. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 34-1000 priced at $131.

MERCEDES BENZ CLASE C (1970/2009): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MERCEDES BENZ CLASE E (1986/2008): In the Black Edition brand, there is only one option available, which is the 94R-1100. There are no options available in the Fulgor brand.

MERCEDES BENZ CLASE G (2016): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

MERCEDES BENZ CLASE S (1975/2001): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MERCEDES BENZ SPRINTER (2004/2008): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

MERCEDES BENZ PANEL (1990/1999): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

MITSUBISHI 3000 GT (1991/1999): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MITSUBISHI ATTRAGE/MIRAGE (2022/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI ASX GASOLINA (2022/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI CARTER 24V (2011/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI CANTER 12V (1992/2007): The available battery models in the Fulgor brand are the 27XR-950 and the 27R-950. There are no options available in the Black Edition brand.

MITSUBISHI COLT (1993/2008): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI DIAMANTE (1992/1997): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

MITSUBISHI ECLIPSE (1992/1994): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

MITSUBISHI ECLIPSE G3 (1995/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MITSUBISHI FUSO CARTER (2022/2024): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

MITSUBISHI GALANT (1993/2005): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI GRANDIS (2003/2011): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

MITSUBISHI L200 SPORTERO GASOLINA (2008/2012): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

MITSUBISHI L200 SPORTERO DIESEL (2021/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI L200 SPORTERO GASOLINA (2021/2024): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI TOURING 2.0 (2007/2015): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI LANCER (1992/2015): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI MF/MX/ZX (1993/1995): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

MITSUBISHI MF/MX (1998/2001): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI MIRAGE (1993/2001): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

MITSUBISHI MONTERO DAKAR (1992/2010): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

MITSUBISHI MONTERO LIMITED (2007/2009): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI MONTERO SPORT (2000/2006): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 34-1000 priced at $131. There are no additional options available.

MITSUBISHI MONTERO SPORT (2013/2016): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI OUTLANDER 4CIL (2003/2008): The available battery models in the Fulgor brand are the 24R-900 priced at $118 and the 34MR-900 priced at $109. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI OUTLANDER 6CIL (2009/2010): The available battery models in the Fulgor brand are the 24R-900 priced at $118 and the 34MR-900 priced at $109. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI OUTLANDER (2018/2020): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

MITSUBISHI OUTLANDER (2022/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

MITSUBISHI PAJERO SPORT DIESEL (2022/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

MITSUBISHI PANEL L300/VAN L300 (1993/1995): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800 priced at $100. There are no additional options available.

MITSUBISHI SIGNO (2003/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

MITSUBISHI SPACE WAGON (1992/2005): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

MITSUBISHI XPANDER (2023/2024): There is only one option available in the Fulgor brand, which is the NS40. There are no options available in the Black Edition brand.

MINI COOPER (2005/2010): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

MG MG3 (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MG ZS (2022/2024): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

MG RX8 (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

NISSAN 200SX (1992/1998): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

NISSAN 300ZX (1992/1995): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 86-800 priced at $95. There are no additional options available.

NISSAN 350Z/370 (2004/2018): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

NISSAN AD WAGON (1998/2007): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

NISSAN ALMERA (2007/2008): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

NISSAN ALTIMA (1993/2008): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN ARMADA (2004/2007): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN FRONTIER D22 DIESEL/GASOLINA (2003/2008): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN FRONTIER 4X4 AUTOMATICO (2016/2020): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN FRONTIER NP300 TURBO DIESEL (2009/2015): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

NISSAN FRONTIER NP300 DIESEL (2019/2023): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN NV3500 DIESEL VAN (2019): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

NISSAN MAXIMA (1989/2004): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN MURANO (2003/2018): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

NISSAN PATHFINDER (1990/2004): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

NISSAN PATHFINDER (2006/2010): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN PATROL (1975/1994): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN PATROL 4.5 (1998/2002): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

NISSAN PATROL 4.8 (2005/2011): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

NISSAN PICK UP D21 (1996/2007): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, there is one option available, which is the 86-800 priced at $95. There are no additional options available.

NISSAN PRIMERA (1998/2001): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

NISSAN SENTRA B13/B15 (1991/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

NISSAN SENTRA B14 (1999/2008): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800 priced at $100. There are no additional options available.

NISSAN SENTRA B16 (2007/2010): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is one option available, which is the 22FA-800 priced at $95. There are no additional options available.

NISSAN TERRANO (2002/2005): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

NISSAN TIIDA (2007/2009): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800 priced at $100. There are no additional options available.

NISSAN TITAN (2008/2017): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

NISSAN VERSA (2012/2018): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

NISSAN XTRAIL T30 (2002/2018): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

PEGASO AUTOBUSES Y CAMIONES (TODOS): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

PEUGEOT 206 (2001/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 207 (2010/2012): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 307 (2007/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 405 (1992/1996): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 406 (2006/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 407 (2006/2014): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT 408 (2012): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

PEUGEOT 607 (2006/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

PEUGEOT PARTNER (2012): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

PEUGEOT EXPERT (2009/2012): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

PEUGEOT PARTNER (2011/2012): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RAM BIGHORN (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RAM RAPID (2023/2025): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RAM RAM 2500 SLT (2010/2018): The available battery models in the Fulgor brand are the 27R-950 and the 65-1100 priced at $150. There are no options available in the Black Edition brand.

RELLY RELY (2022/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

RENAULT CLIO (1992/2009): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT DUSTER (2013/2015): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

RENAULT DUSTER 1.3/1.6 TURBO (2023/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

RENAULT FUEGO (1984/1995): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT GALA (1984/1995): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT KANGOO (2001/2009): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT LAGUNA (2000/2001): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

RENAULT LOGAN (2005/2014): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT LOGAN (2019/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT MEGANE (1999/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT MEGANE II SEDAN/HATCHBACK (2005/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

RENAULT R/11 (1987/1993): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT R/18 (1980/1990): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT R/19 (1991/2001): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT R/21 (1989/1994): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT R/5 (1982/1986): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT SANDERO (2009): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

RENAULT SCENIC (2000/2009): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT SADERO (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT STEEPWAY (2023/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT SYMBOL (2001/2009): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

RENAULT TRAFFIC (1992/2003): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

RENAULT TWINGO (1992/2009): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

ROVER MINICORD (1991/1995): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SAIC WULING CARGO (2006/2008): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

SAIC WULING SUPER VAN (2006/2008): The available battery models in the Fulgor brand are the NS40 and the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

SAIPA SAINA (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SAIPA QUICK ST (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SEAT CORDOBA (2000/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SEAT IBIZA (2001/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SEAT LEON (2005/2008): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

SEAT TOLEDO (2001/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SKODA FABIA (2007/2009): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SKODA FORMAN (1992/1994): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. There are no options available in the Black Edition brand.

SKODA OCTAVIA (2002/2008): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. There are no options available in the Black Edition brand.

SKODA ROOMSTER (2008/2010): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. There are no options available in the Black Edition brand.

SUBARU FORESTER (1998/2007): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 34MR-900 priced at $109. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

SUBARU IMPREZA (1993/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SUBARU IMPREZA (2000/2014): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SUBARU LEGACY (1998/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

SUZUKI BALENO (2022/2024): There is only one option available in the Fulgor brand, which is the NS40 (BORNE FINO). There are no options available in the Black Edition brand.

SUZUKI GRAND VITARA (2007/2008): There is only one option available in the Fulgor brand, which is the 86-800 priced at $95. In the Black Edition brand, the available batteries are the 86-800 priced at $95 and the 22FA-800 priced at $95.

SUZUKI SWIFT (2022/2024): There is only one option available in the Fulgor brand, which is the NS40 (BORNE FINO). There are no options available in the Black Edition brand.

TOYOTA AUTANA/BURBUJA (1992/2007): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA C/HR (2018/2019): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

TOYOTA CAMRY (1992/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA CAMRY (2017/2022): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

TOYOTA CELICA (1992/1999): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA CELICA (2000/2005): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

TOYOTA COASTER (2001/2014): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

TOYOTA COROLLA/SKY (1986/2002): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA COROLLA (2003/2014): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA COROLLA LE 1.8/LE 2.0 (2016/2019): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA COROLLA S (2015/2019): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA COROLLA SE/SE-G/LE (2020/2024): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

TOYOTA COROLLA IMPORTADO (SEGÚN MUESTRA) (2016/2024): There are no options available in either the Fulgor brand or the Black Edition brand.

TOYOTA COROLLA CROSS (2022/2024): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

TOYOTA CROWN (1993/1998): There is only one option available in the Fulgor brand, which is the 34MR-900 priced at $109. There are no options available in the Black Edition brand.

TOYOTA DYNA (1992/2007): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA ETIOS (2016/2023): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

TOYOTA FJ CRUISER (2005/2016): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA FORTUNER VXR (2018/2019): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA FORTUNER VXR LEYENDER (2023/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA FORTUNER (2006/2019): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA FORTUNER DUBAI (2018/2020): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA FORTUNER SW4 (2021/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA FORTUNER DIESEL 2.8 (2017/2023): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is only one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA 4RUNNER/SR5/LIMITED (1991/2024): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA HIACE (2007/2009): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

TOYOTA HIACE 2.5 TURBO DIESEL (2022/2024): The available battery models in the Fulgor brand are the 41MR-900 priced at $116 and the 34MR-900 priced at $109. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA HILUX (1992/2005): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA HILUX 2.7 (2006/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA HILUX KAVAK 4.0 (2006/2015): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA HILUX DUBAI (2018/2019): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA HILUX DIESEL 2.8L (2022/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA HILUX 4.0 GASOLINA (2022/2024): There is only one option available in the Fulgor brand, which is the 41MR-900 priced at $116. In the Black Edition brand, there is one option available, which is the 41FXR-900 priced at $116. There are no additional options available.

TOYOTA LAND CRUISER SERIE J40 (MACHO) (1960/1984): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA LAND CRUISER SERIE J60 (SAMURAI) (1984/1992): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

TOYOTA LAND CRUISER SERIE J70 (MACHITO) (1985/2009): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA LAND CRUISER SERIE J70 (MACHITO 4.0 V6) (2010/2024): There is only one option available in the Fulgor brand, which is the 34M-900 priced at $109. In the Black Edition brand, there is one option available, which is the 34-1000 priced at $131. There are no additional options available.

TOYOTA LAND CRUISER SERIE J70 DIESEL V8 (2022/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. There are no options available in the Black Edition brand.

TOYOTA LAND CRUISER SERIE J80 (AUTANA/BURBUJA) (1990/2007): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA LAND CRUISER SERIE 200 (RORAIMA) (2008/2021): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA LAND CRUISER SERIE 300 VX (2021/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

TOYOTA MERU (2005/2009): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA PASEO (1993/1997): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

TOYOTA PRADO (1999/2006): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA LAND CRUISER PRADO TX DIESEL (2022/2024): There is only one option available in the Fulgor brand, which is the 27XR-950. There are no options available in the Black Edition brand.

TOYOTA LAND CRUISER PRADO WX GASOLINA (2022/2024): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

TOYOTA PREVIA (1991/2010): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is only one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA PRIUS (2012/2015): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

TOYOTA RAV/4 (1996/2007): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

TOYOTA RAV/4 (2016): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

TOYOTA SEQUOIA (2003/2009): There is only one option available in the Fulgor brand, which is the 27XR-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA SIENNA (1998/2006): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA STARLET (1992/2000): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. In the Black Edition brand, there is only one option available, which is the 36FP-700 priced at $82. There are no additional options available.

TOYOTA SUPRA (1982/1998): The available battery models in the Fulgor brand are the 22FA-800 priced at $95 and the 41MR-900 priced at $116. In the Black Edition brand, the available batteries are the 22FA-800 priced at $95 and the 41FXR-900 priced at $116.

TOYOTA TACOMA (2007/2019): There is only one option available in the Fulgor brand, which is the 24R-900 priced at $118. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA TERCEL (1991/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

TOYOTA TERIOS (2002/2010): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA TUNDRA (2004/2010): There is only one option available in the Fulgor brand, which is the 27R-950. In the Black Edition brand, there is one option available, which is the 24MR-1100 priced at $140. There are no additional options available.

TOYOTA YARIS (2000/2009): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is one option available, which is the 22NF-800 priced at $100. There are no additional options available.

TOYOTA YARIS E CVT (2022/2024): The available battery models in the Fulgor brand are the 36FP-700 priced at $82. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

TOYOTA YARIS CROSS/SD (2022/2024): There is only one option available in the Fulgor brand, which is the NS40 (BORNE FINO). There are no options available in the Black Edition brand.

VOLKSWAGEN BORA (2000/2009): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLKSWAGEN CADDY (1998/2006): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN CROSSFOX (2006/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN ESCARABAJO (1963/1998): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN FOX (2005/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN GOL (1992/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN GOLF (1993/2007): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN JETTA (1992/2008): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLKSWAGEN PARATI (2001/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN PASSAT (1992/2007): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLKSWAGEN POLO (1998/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN SANTANA (2002/2004): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN SAVEIRO (1998/2008): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN SPACEFOX (2007/2010): The available battery models in the Fulgor brand are the 36FP-700 priced at $82 and the 22FA-800 priced at $95. In the Black Edition brand, the available batteries are the 36FP-700 priced at $82 and the 22FA-800 priced at $95.

VOLKSWAGEN TOUAREG (2004/2008): In the Black Edition brand, there is only one option available, which is the 94R-1100 priced at $168. There are no options available in the Fulgor brand.

VOLKSWAGEN VENTO (1993/1999): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VENUCIA V-ONLINE 260T (2023/2024): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLVO 740 (1990/1992): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLVO 940 (1991/1997): There is only one option available in the Fulgor brand, which is the 22FA-800 priced at $95. In the Black Edition brand, there is only one option available, which is the 22FA-800 priced at $95. There are no additional options available.

VOLVO FH 440 (2005/2010): There is only one option available in the Fulgor brand, which is the 4D-1250 priced at $245. There are no options available in the Black Edition brand.

VOLVO VM (2005/2010): There is only one option available in the Fulgor brand, which is the 30HC-1100 priced at $180. There are no options available in the Black Edition brand.

ZOTYE NOMADA (2007/2009): There is only one option available in the Fulgor brand, which is the 22NF-700 priced at $93. In the Black Edition brand, there is only one option available, which is the 22NF-800 priced at $100. There are no additional options available.

ZOTYE MANZA (2012/2014): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. There are no options available in the Black Edition brand.

ZOTYE VISTA (2012/2014): There is only one option available in the Fulgor brand, which is the 36FP-700 priced at $82. There are no options available in the Black Edition brand.
    """
    # Or load from file if you want

    structured_fitment_data, error_logs = parse_vehicle_fitments(car_data_input)

    with open(OUTPUT_FITMENTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(structured_fitment_data, f, indent=4, ensure_ascii=False)
    if error_logs:
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as ef:
            json.dump(error_logs, ef, indent=4, ensure_ascii=False)
        print(f"⚠️  Saved {len(error_logs)} error logs to {ERROR_LOG_PATH}")
        print("--- First 10 error log entries ---")
        for e in error_logs[:10]:
            print(json.dumps(e, indent=2))
    else:
        print("🎉 No mapping or parsing errors detected in the processed entries!")
    print(f"\n✅ Saved {len(structured_fitment_data)} fitment entries to {OUTPUT_FITMENTS_JSON_PATH}")
    print("--- Script Finished ---")
