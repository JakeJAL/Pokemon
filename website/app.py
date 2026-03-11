from flask import Flask, render_template, request, jsonify
from tcgdexsdk import TCGdex, Query
from tcgdexsdk.enums import Quality, Extension
import asyncio
import csv
import re
import json
from prof_oak_ai import professor_oak_query
from dotenv import load_dotenv
import os
import easyocr
import cv2
import numpy as np
import base64
from difflib import get_close_matches
from PIL import Image, ImageOps, ImageEnhance

# Load environment variables
load_dotenv()

app = Flask(__name__)
sdk = TCGdex()

# Initialize the Pokemon card search system - now using prof_oak_ai
try:
    # Test the prof_oak_ai system
    test_result = professor_oak_query("test")
    pokemon_searcher_available = True
except Exception as e:
    print(f"Error initializing Professor Oak AI system: {e}")
    pokemon_searcher_available = False

def prepare_image_for_ocr(cv2_img):
    """
    Takes an OpenCV image, applies multiple preprocessing techniques
    to improve OCR accuracy for Pokemon cards at various angles.
    """
    try:
        # Convert OpenCV (BGR) to RGB
        color_converted = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(color_converted)

        # 1. Convert to grayscale
        pil_img = ImageOps.grayscale(pil_img)
        
        # 2. Boost Contrast significantly (helps with angled/shadowed cards)
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(3.0)  # Increased from 2.5
        
        # 3. Boost Sharpness (helps with slightly blurry images)
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(2.0)
        
        # 4. Adjust Brightness (helps with shadows from fingers)
        enhancer = ImageEnhance.Brightness(pil_img)
        pil_img = enhancer.enhance(1.2)

        # Convert back to OpenCV format for EasyOCR
        img_array = np.array(pil_img)
        
        # 5. Apply adaptive thresholding to handle uneven lighting
        # This helps separate text from background even with shadows
        img_array = cv2.adaptiveThreshold(
            img_array, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 
            11, 2
        )
        
        return img_array
    except Exception as e:
        print(f"Image processing failed: {e}")
        return cv2_img  # Fallback to original

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/price')
def price():
    search_query = request.args.get('query', '').lower()
    category = request.args.get('category', 'all')
    items = []
    
    # Smart detection keywords
    pack_keywords = ['pack', 'booster pack', 'sleeved', 'blister']
    box_keywords = ['box', 'display', 'etb', 'trainer box', 'collection', 'tin', 'deck', 'bundle']

    try:
        # Get the directory where this script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(script_dir, 'pokemon_cards_database.csv')
        
        with open(csv_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                title = row['title'].lower()
                
                if search_query not in title:
                    continue
                
                # CATEGORY LOGIC
                is_pack = any(word in title for word in pack_keywords)
                is_box = any(word in title for word in box_keywords)
                # Regex looks for patterns like 123/456 or 01/10
                is_single = bool(re.search(r'\d+/\d+', title)) or (not is_pack and not is_box and any(x in title for x in [' v ', ' vmax', ' ex ', ' star', ' rare']))

                # Filtering based on selection
                if category == 'booster' and not is_pack:
                    continue
                elif category == 'box' and not is_box:
                    continue
                elif category == 'single' and not is_single:
                    continue
                elif category == 'other':
                    # If it's not a pack, box, or single, it goes to 'Other'
                    if is_pack or is_box or is_single:
                        continue
                        
                items.append(row)
    except FileNotFoundError:
        print("CSV file missing!")

    return render_template('price.html', items=items, query=search_query, current_cat=category)

@app.route('/search')
def search():
    return render_template('search.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/collection')
def collection():
    return render_template('collection.html')

@app.route('/api/chat', methods=['POST'])
def chat_api():
    """API endpoint for Pokemon card chatbot using Professor Oak AI"""
    if not pokemon_searcher_available:
        return jsonify({
            'error': 'Professor Oak is not available right now. Check API key configuration.'
        }), 500
    
    data = request.json
    user_message = data.get('message', '')
    
    # NEW: Grab the collection data sent from the browser's localStorage
    user_collection = data.get('collection', {})
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        result = professor_oak_query(user_message, user_collection)
        
        return jsonify({
            'response': result['response'],
            'results': result['results'],
            'num_results': result['num_results']
        })
    except Exception as e:
        return jsonify({
            'error': f'Sorry, Professor Oak encountered an error: {str(e)}'
        }), 500

@app.route('/api/sets', methods=['GET'])
def get_sets():
    sets = asyncio.run(sdk.set.list())
    return jsonify([{'id': s.id, 'name': s.name} for s in sets])

@app.route('/api/cards', methods=['POST'])
def get_cards():
    data = request.json
    set_id = data.get('set_id')
    rarities = data.get('rarities', [])
    search_term = data.get('search_term', '').lower()
    card_types = data.get('card_types', [])
    
    # NEW: Sorting & Pagination variables
    sort_by = data.get('sort_by', 'number') # Default sorting
    page = int(data.get('page', 1))
    per_page = data.get('per_page', 20)  # Allow custom per_page, default 20
    # If per_page is 0 or 'all', disable pagination
    disable_pagination = per_page == 0 or per_page == 'all'
    
    async def fetch_cards():
        # Fetch the initial list
        if not set_id:
            if search_term:
                cards = await sdk.card.list(Query().contains("name", search_term))
            else:
                cards = await sdk.card.list()
        else:
            if search_term:
                cards = await sdk.card.list(Query().equal("set.id", set_id).contains("name", search_term))
            else:
                cards = await sdk.card.list(Query().equal("set.id", set_id))
        
        # --- NEW: SORTING LOGIC ---
        # We sort the 'resume' objects before doing the heavy lifting
        if sort_by == 'name':
            cards.sort(key=lambda x: x.name)
        elif sort_by == 'set':
            cards.sort(key=lambda x: x.set.name if hasattr(x, 'set') else '')
        elif sort_by == 'number':
            # Extract number from localId (handles '12/102')
            def get_num(c):
                match = re.search(r'\d+', str(c.localId))
                return int(match.group()) if match else 999
            cards.sort(key=get_num)

        # --- NEW: SLICE THE LIST HERE ---
        if disable_pagination:
            # Return all cards
            paginated_cards = cards
        else:
            # Apply pagination
            start = (page - 1) * per_page
            end = start + per_page
            paginated_cards = cards[start:end]
        
        async def fetch_card_details(card_resume):
            try:
                full_card = await sdk.card.get(card_resume.id)
                
                # Define this early for safety!
                card_category = getattr(full_card, 'category', 'Unknown')
                
                # Filters
                if rarities and hasattr(full_card, 'rarity') and full_card.rarity not in rarities:
                    return None
                if card_types and card_category not in card_types:
                    return None
                
                image_url = full_card.get_image_url(Quality.LOW, Extension.JPG)
                
                return {
                    'name': full_card.name,
                    'rarity': getattr(full_card, 'rarity', 'Unknown'),
                    'localId': full_card.localId,
                    'image': image_url,
                    'setName': full_card.set.name if hasattr(full_card, 'set') else 'Unknown',
                    'setId': full_card.set.id if hasattr(full_card, 'set') else '',
                    'category': card_category
                }
            except Exception as e:
                print(f"Error: {e}")
                return None
        
        tasks = [fetch_card_details(card) for card in paginated_cards]
        results = await asyncio.gather(*tasks)
        
        # If the user chose Rarity sorting, we sort the detailed results
        # because rarity isn't available on the 'resume' objects
        final_results = [card for card in results if card is not None]
        
        if sort_by == 'rarity_asc' or sort_by == 'rarity_desc':
            rarity_map = {'Common': 1, 'Uncommon': 2, 'Rare': 3, 'Holo Rare': 4, 'Ultra Rare': 5, 'Secret Rare': 6}
            final_results.sort(key=lambda x: rarity_map.get(x['rarity'], 0), reverse=(sort_by == 'rarity_desc'))
            
        return final_results
    
    results = asyncio.run(fetch_cards())
    return jsonify(results)

@app.route('/scan')
def scan_page():
    # This looks inside the 'templates' folder for scan.html
    return render_template('scan.html')

# Initialize the reader once (this downloads the model on first run)
reader = easyocr.Reader(['en'])

# Load all Pokemon names for card matching
POKEMON_NAMES = None

def load_pokemon_names():
    """Load all unique Pokemon names from the card database"""
    global POKEMON_NAMES
    if POKEMON_NAMES is None:
        try:
            cards_file_path = os.path.join(os.path.dirname(__file__), '..', 'all_cards.json')
            with open(cards_file_path, 'r', encoding='utf-8') as f:
                all_cards = json.load(f)
            
            # Extract unique Pokemon names (base names without suffixes)
            names = set()
            for card in all_cards:
                card_name = card.get('name', '')
                if card_name:
                    # Get the base Pokemon name (before any space, dash, or special character)
                    # Examples: "Pikachu V" -> "Pikachu", "Charizard-GX" -> "Charizard"
                    base_name = card_name.split()[0].split('-')[0]
                    names.add(base_name)
                    # Also add the full name for exact matches
                    names.add(card_name)
            
            POKEMON_NAMES = sorted(list(names))
            print(f"Loaded {len(POKEMON_NAMES)} Pokemon names for card matching")
        except Exception as e:
            print(f"Error loading Pokemon names: {e}")
            POKEMON_NAMES = []
    return POKEMON_NAMES

def extract_card_number(ocr_text: str) -> str:
    """
    Extract card number from OCR text (e.g., "097/094", "12/102")
    """
    # Pattern for card numbers: digits/digits
    pattern = r'\b(\d{1,4})[/\\](\d{1,4})\b'
    matches = re.findall(pattern, ocr_text)
    
    if matches:
        # Return the first match in format "XXX/YYY"
        return f"{matches[0][0]}/{matches[0][1]}"
    
    return None

def extract_set_info(ocr_text: str) -> str:
    """
    Extract set information from OCR text.
    Set codes are usually 2-5 letter/number combinations at the bottom of cards.
    Common formats: PFLN, SVI, PAL, sv3pt5, etc.
    """
    # Known Pokemon TCG set codes (partial list of recent sets)
    known_set_codes = {
        'PFLN', 'PAL', 'SVI', 'MEW', 'OBF', 'PAF', 'TEF', 'TWM', 'SFA', 'SCR',
        'PAR', 'CRZ', 'SIT', 'LOR', 'PGO', 'ASR', 'BRS', 'FST', 'EVS', 'CRE',
        'BST', 'SHF', 'VIV', 'CPA', 'DAA', 'RCL', 'SSH', 'CEC', 'HIF', 'UNM',
        'UNB', 'DET', 'TEU', 'LOT', 'DRM', 'CES', 'FLI', 'UPR', 'CIN', 'SLG',
        'BUS', 'GRI', 'SUM', 'EVO', 'STS', 'FCO', 'GEN', 'BKP', 'BKT', 'AOR',
        'sv1', 'sv2', 'sv3', 'sv4', 'sv5', 'sv6', 'sv3pt5', 'sv4pt5'
    }
    
    # Look for patterns that match set codes
    # Pattern 1: 2-5 uppercase letters possibly followed by numbers
    pattern1 = r'\b([A-Z]{2,5}\d?)\b'
    matches1 = re.findall(pattern1, ocr_text.upper())
    
    # Pattern 2: sv followed by numbers (Scarlet & Violet era)
    pattern2 = r'\b(sv\d+(?:pt\d+)?)\b'
    matches2 = re.findall(pattern2, ocr_text.lower())
    
    all_matches = matches1 + [m.upper() for m in matches2]
    
    # Filter out common false positives
    exclude_words = {
        'HP', 'EX', 'GX', 'VMAX', 'VSTAR', 'STAGE', 'BASIC', 'ABILITY', 'ATTACK', 
        'RETREAT', 'WEAKNESS', 'RESISTANCE', 'POKEMON', 'POKÉMON', 'TRAINER', 
        'ENERGY', 'RARE', 'HOLO', 'REVERSE', 'PROMO', 'ILLUS', 'LV', 'FLIP', 
        'DAMAGE', 'COIN', 'COINS', 'TURN', 'CARD', 'CARDS', 'DECK', 'DRAW',
        'HAND', 'BENCH', 'ACTIVE', 'PRIZE', 'DISCARD', 'SHUFFLE', 'SEARCH',
        'PUT', 'TAKE', 'PLACE', 'PLAY', 'ATTACH', 'EVOLVE', 'KNOCK', 'OUT',
        'GAME', 'FREAK', 'NINTENDO', 'CREATURES', 'INC', 'USA', 'UK', 'MADE',
        'PRINTED', 'JAPAN', 'THICK', 'FAT', 'SLAM', 'WATER', 'FIRE', 'GRASS',
        'ELECTRIC', 'PSYCHIC', 'FIGHTING', 'DARKNESS', 'METAL', 'FAIRY', 'DRAGON',
        'COLORLESS', 'NORMAL', 'SPECIAL', 'ITEM', 'SUPPORTER', 'STADIUM', 'TOOL'
    }
    
    valid_codes = []
    for match in all_matches:
        match_upper = match.upper()
        # Check if it's a known set code
        if match_upper in known_set_codes:
            valid_codes.append(match_upper)
        # Or if it's not in the exclude list and has the right length
        elif match_upper not in exclude_words and 2 <= len(match_upper) <= 6:
            valid_codes.append(match_upper)
    
    # Return the last valid code (set codes are usually at the bottom)
    if valid_codes:
        print(f"Found potential set codes: {valid_codes}")
        return valid_codes[-1]
    
    return None

def extract_hp_value(ocr_text: str) -> str:
    """
    Extract HP value from OCR text (e.g., "HP 130", "130")
    """
    # Pattern for HP: "HP" followed by digits, or just "HP" near digits
    patterns = [
        r'HP\s*(\d{2,3})',  # "HP 130" or "HP130"
        r'(\d{2,3})\s*HP',  # "130 HP"
        r'HP.*?(\d{2,3})',  # "HP" with digits nearby
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, ocr_text, re.IGNORECASE)
        if matches:
            return matches[0]
    
    return None

def find_exact_card(pokemon_name: str, card_number: str = None, hp_value: str = None, set_code: str = None) -> dict:
    """
    Find the exact card from the database using Pokemon name, card number, HP, and set code
    Priority: card_number + set_code > card_number + HP > HP only > name only
    """
    try:
        cards_file_path = os.path.join(os.path.dirname(__file__), '..', 'all_cards.json')
        with open(cards_file_path, 'r', encoding='utf-8') as f:
            all_cards = json.load(f)
        
        # Filter cards by Pokemon name
        matching_cards = []
        for card in all_cards:
            card_name = card.get('name', '').lower()
            if pokemon_name.lower() in card_name or card_name.startswith(pokemon_name.lower()):
                matching_cards.append(card)
        
        if not matching_cards:
            return None
        
        print(f"Found {len(matching_cards)} cards matching '{pokemon_name}'")
        
        # Priority 1: Match by card number AND set code (most specific)
        if card_number and set_code:
            for card in matching_cards:
                card_local_id = card.get('localId', '')
                card_set_id = card.get('set', {}).get('id', '').upper()
                card_set_name = card.get('set', {}).get('name', '').upper()
                
                # Check if set code matches the set ID or is contained in set name
                # Be flexible: PFLN might match "sv4pt5" or "Paldean Fates"
                set_code_upper = set_code.upper()
                if card_local_id == card_number:
                    # Direct match
                    if (set_code_upper in card_set_id.upper() or 
                        card_set_id.upper() in set_code_upper or
                        set_code_upper in card_set_name):
                        print(f"✓ Matched by card number + set code: {card.get('name')} from {card.get('set', {}).get('name')} (ID: {card_set_id})")
                        return format_card_result(card)
        
        # Priority 2: Match by card number AND HP (very specific)
        if card_number and hp_value:
            try:
                hp_int = int(hp_value)
                for card in matching_cards:
                    card_local_id = card.get('localId', '')
                    card_hp = card.get('hp')
                    if card_local_id == card_number and card_hp:
                        try:
                            if int(card_hp) == hp_int:
                                print(f"✓ Matched by card number + HP: {card.get('name')} from {card.get('set', {}).get('name')}")
                                return format_card_result(card)
                        except (ValueError, TypeError):
                            continue
            except (ValueError, TypeError):
                pass
        
        # Priority 3: Match by card number only (less specific, might match wrong set)
        # But prefer more recent cards (they appear first in the list)
        if card_number:
            for card in matching_cards:
                card_local_id = card.get('localId', '')
                if card_local_id == card_number:
                    print(f"⚠ Matched by card number only: {card.get('name')} from {card.get('set', {}).get('name')}")
                    return format_card_result(card)
        
        # Priority 4: Match by HP only
        if hp_value:
            try:
                hp_int = int(hp_value)
                for card in matching_cards:
                    card_hp = card.get('hp')
                    if card_hp:
                        try:
                            if int(card_hp) == hp_int:
                                print(f"⚠ Matched by HP: {card.get('name')} from {card.get('set', {}).get('name')}")
                                return format_card_result(card)
                        except (ValueError, TypeError):
                            continue
            except (ValueError, TypeError):
                pass
        
        # Priority 5: Return the most recent card (first in list)
        if matching_cards:
            card = matching_cards[0]
            print(f"⚠ Matched by name only (most recent): {card.get('name')} from {card.get('set', {}).get('name')}")
            return format_card_result(card)
        
        return None
        
    except Exception as e:
        print(f"Error finding exact card: {e}")
        import traceback
        traceback.print_exc()
        return None

def format_card_result(card: dict) -> dict:
    """Format card data for API response"""
    return {
        'name': card.get('name'),
        'id': card.get('id'),
        'localId': card.get('localId'),
        'hp': card.get('hp'),
        'set_name': card.get('set', {}).get('name', 'Unknown'),
        'set_id': card.get('set', {}).get('id', 'Unknown'),
        'rarity': card.get('rarity', 'Unknown'),
        'image': card.get('image', {}).get('small') if isinstance(card.get('image'), dict) else None
    }

def extract_pokemon_name_from_ocr(ocr_text: str) -> str:
    """
    Extract the most likely Pokemon name from OCR text.
    Pokemon card names are typically at the top and are capitalized.
    """
    if not ocr_text:
        return ""
    
    # Split into lines and words
    lines = ocr_text.split('\n')
    words = ocr_text.split()
    
    # Load Pokemon names database
    pokemon_names = load_pokemon_names()
    if not pokemon_names:
        return ocr_text
    
    # Strategy 1: Check first few words (Pokemon name is usually first)
    for i in range(min(5, len(words))):
        word = words[i].strip()
        # Clean up common OCR errors
        word = word.replace('0', 'O').replace('1', 'I').replace('5', 'S')
        
        # Try to match this word against Pokemon names
        matches = get_close_matches(word, pokemon_names, n=1, cutoff=0.75)
        if matches:
            return matches[0]
    
    # Strategy 2: Look for capitalized words (Pokemon names are capitalized)
    capitalized_words = [w for w in words if w and w[0].isupper() and len(w) > 2]
    for word in capitalized_words[:5]:  # Check first 5 capitalized words
        word = word.strip()
        word = word.replace('0', 'O').replace('1', 'I').replace('5', 'S')
        matches = get_close_matches(word, pokemon_names, n=1, cutoff=0.75)
        if matches:
            return matches[0]
    
    # Strategy 3: Try the entire first line
    if lines:
        first_line = lines[0].strip()
        first_line = first_line.replace('0', 'O').replace('1', 'I').replace('5', 'S')
        matches = get_close_matches(first_line, pokemon_names, n=1, cutoff=0.7)
        if matches:
            return matches[0]
    
    # Strategy 4: Try all text as fallback
    cleaned_text = ocr_text.replace('0', 'O').replace('1', 'I').replace('5', 'S')
    matches = get_close_matches(cleaned_text, pokemon_names, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    
    # If nothing matches, return the first capitalized word or first word
    if capitalized_words:
        return capitalized_words[0]
    elif words:
        return words[0]
    
    return ocr_text

@app.route('/api/scan', methods=['POST'])
def api_scan():
    try:
        data = request.json['image']
        # Decode the base64 image from the camera
        header, encoded = data.split(",", 1)
        nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Apply pre-processing for better OCR
        processed_img = prepare_image_for_ocr(img)

        # Pass the cleaned image to the reader
        results = reader.readtext(processed_img)

        # results is a list: [ ([[coords]], "text", confidence), ... ]
        # Sort by Y-coordinate to get text from top to bottom
        results_sorted = sorted(results, key=lambda x: x[0][0][1])  # Sort by top-left Y coordinate
        
        # Join text from top of card (first few detections)
        top_text = " ".join([res[1] for res in results_sorted[:3]])  # First 3 text blocks
        # Get bottom text (last few detections for set code)
        bottom_text = " ".join([res[1] for res in results_sorted[-5:]])  # Last 5 text blocks
        all_text = " ".join([res[1] for res in results])
        
        # Log for debugging
        print(f"Scanner detected (top): {top_text}")
        print(f"Scanner detected (bottom): {bottom_text}")
        print(f"Scanner detected (all): {all_text}")
        
        # Extract Pokemon name from OCR text
        pokemon_name = extract_pokemon_name_from_ocr(top_text)
        
        # If we didn't find anything good from top text, try all text
        if not pokemon_name or len(pokemon_name) < 3:
            pokemon_name = extract_pokemon_name_from_ocr(all_text)
        
        # Extract card number, HP, and set code
        card_number = extract_card_number(all_text)
        hp_value = extract_hp_value(all_text)
        set_code = extract_set_info(bottom_text)  # Look in bottom text for set code
        
        print(f"Extracted Pokemon name: {pokemon_name}")
        print(f"Extracted card number: {card_number}")
        print(f"Extracted HP: {hp_value}")
        print(f"Extracted set code: {set_code}")
        
        # Find the exact card
        exact_card = find_exact_card(pokemon_name, card_number, hp_value, set_code)
        
        if exact_card:
            return jsonify({
                'name': exact_card['name'],
                'card_number': exact_card['localId'],
                'hp': exact_card['hp'],
                'set_name': exact_card['set_name'],
                'set_id': exact_card['set_id'],
                'rarity': exact_card['rarity'],
                'image': exact_card['image'],
                'card_id': exact_card['id'],
                'raw_text': all_text,
                'detected_set_code': set_code,  # Include for debugging
                'success': True
            })
        else:
            # Fallback to just the Pokemon name
            return jsonify({
                'name': pokemon_name if pokemon_name else "No Pokemon detected",
                'raw_text': all_text,
                'success': True
            })
            
    except Exception as e:
        print(f"Scan Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500

def find_best_card_match(detected_text, card_list):
    # This looks for the closest name in your CSV
    matches = get_close_matches(detected_text, card_list, n=1, cutoff=0.6)
    return matches[0] if matches else detected_text

if __name__ == '__main__':
    app.run(debug=True)
