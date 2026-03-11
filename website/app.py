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
from openai import OpenAI
from typing import List

# Load environment variables
load_dotenv()

# Get API credentials for vision
api_key = os.getenv("API_KEY")
endpoint = os.getenv("ENDPOINT")

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
    Advanced preprocessing for Pokemon cards held at angles with fingers/glare.
    Returns multiple processed versions for better OCR accuracy.
    """
    try:
        # Convert to RGB
        rgb_img = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
        
        # Strategy 1: Perspective correction (detect card edges and unwarp)
        gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        
        # Find contours to detect card boundary
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Try to find the card rectangle
        card_contour = None
        if contours:
            # Sort by area and get the largest
            contours = sorted(contours, key=cv2.contourArea, reverse=True)
            for cnt in contours[:5]:  # Check top 5 largest contours
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
                if len(approx) == 4:  # Found a quadrilateral
                    card_contour = approx
                    break
        
        # If we found the card, apply perspective transform
        if card_contour is not None:
            pts = card_contour.reshape(4, 2)
            rect = order_points(pts)
            warped = four_point_transform(rgb_img, rect)
            processed_img = warped
        else:
            processed_img = rgb_img
        
        # Convert to PIL for enhancement
        pil_img = Image.fromarray(processed_img)
        
        # Strategy 2: Aggressive preprocessing for text regions
        # Focus on top portion (where Pokemon name is)
        height, width = processed_img.shape[:2] if len(processed_img.shape) == 2 else processed_img.shape[:2]
        
        # Convert to grayscale
        pil_img = ImageOps.grayscale(pil_img)
        
        # Enhance contrast dramatically
        enhancer = ImageEnhance.Contrast(pil_img)
        pil_img = enhancer.enhance(3.5)
        
        # Enhance sharpness
        enhancer = ImageEnhance.Sharpness(pil_img)
        pil_img = enhancer.enhance(2.5)
        
        # Adjust brightness
        enhancer = ImageEnhance.Brightness(pil_img)
        pil_img = enhancer.enhance(1.3)
        
        # Convert to numpy for OpenCV operations
        img_array = np.array(pil_img)
        
        # Apply bilateral filter to reduce noise while keeping edges
        img_array = cv2.bilateralFilter(img_array, 9, 75, 75)
        
        # Apply adaptive thresholding
        img_array = cv2.adaptiveThreshold(
            img_array, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            15, 3
        )
        
        # Morphological operations to clean up
        kernel = np.ones((2, 2), np.uint8)
        img_array = cv2.morphologyEx(img_array, cv2.MORPH_CLOSE, kernel)
        
        return img_array
    except Exception as e:
        print(f"Image processing failed: {e}")
        # Fallback to basic processing
        gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
        return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

def order_points(pts):
    """Order points in top-left, top-right, bottom-right, bottom-left order"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def four_point_transform(image, pts):
    """Apply perspective transform to get bird's eye view of card"""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    
    # Compute width
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    
    # Compute height
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    
    # Construct destination points
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")
    
    # Compute perspective transform matrix and apply it
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    
    return warped

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/price')
def price():
    search_query = request.args.get('query', '').lower()
    category = request.args.get('category', 'all')
    sort_order = request.args.get('sort', 'asc')  # 'asc' or 'desc'
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
                
                # Convert price to float for sorting
                try:
                    row['price_float'] = float(row['price'])
                except (ValueError, KeyError):
                    row['price_float'] = 0.0
                        
                items.append(row)
    except FileNotFoundError:
        print("CSV file missing!")
    
    # Sort items by price
    reverse_sort = (sort_order == 'desc')
    items.sort(key=lambda x: x.get('price_float', 0.0), reverse=reverse_sort)

    return render_template('price.html', items=items, query=search_query, current_cat=category, current_sort=sort_order)

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

# Initialize vision client for image comparison
vision_client = OpenAI(api_key=api_key, base_url=endpoint)

# Load all Pokemon names for card matching
POKEMON_NAMES = None

def detect_full_art_card(cv2_img):
    """
    Detect if a card is full-art/illustration rare by analyzing the image.
    Full-art cards have artwork covering most of the card, while regular cards
    have a distinct border/frame around the artwork.
    
    Returns True if full-art, False if regular card.
    """
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
        
        # Get image dimensions
        height, width = gray.shape
        
        # Define regions to analyze
        # Regular cards have a yellow/colored border, full-art cards don't
        # Check the edges of the card for border presence
        
        # Sample edge regions (top, bottom, left, right)
        edge_thickness = int(min(height, width) * 0.05)  # 5% of smallest dimension
        
        top_edge = gray[0:edge_thickness, :]
        bottom_edge = gray[height-edge_thickness:height, :]
        left_edge = gray[:, 0:edge_thickness]
        right_edge = gray[:, width-edge_thickness:width]
        
        # Calculate variance in edge regions
        # Regular cards have consistent colored borders (low variance)
        # Full-art cards have artwork extending to edges (high variance)
        top_var = np.var(top_edge)
        bottom_var = np.var(bottom_edge)
        left_var = np.var(left_edge)
        right_var = np.var(right_edge)
        
        avg_edge_variance = (top_var + bottom_var + left_var + right_var) / 4
        
        # Also check the center region variance (artwork area)
        center_y_start = int(height * 0.2)
        center_y_end = int(height * 0.6)
        center_x_start = int(width * 0.15)
        center_x_end = int(width * 0.85)
        center_region = gray[center_y_start:center_y_end, center_x_start:center_x_end]
        center_var = np.var(center_region)
        
        # Calculate ratio of edge variance to center variance
        # Full-art: edges have similar variance to center (ratio close to 1)
        # Regular: edges have much lower variance than center (ratio < 0.5)
        if center_var > 0:
            variance_ratio = avg_edge_variance / center_var
        else:
            variance_ratio = 0
        
        print(f"Card analysis - Edge variance: {avg_edge_variance:.2f}, Center variance: {center_var:.2f}, Ratio: {variance_ratio:.3f}")
        
        # Threshold: if variance ratio > 0.4, likely full-art
        # Full-art cards have detailed artwork extending to edges
        is_full_art = variance_ratio > 0.4
        
        # Additional check: analyze color distribution
        # Regular cards often have yellow/gold borders
        # Convert to HSV to detect yellow borders
        hsv = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2HSV)
        
        # Yellow hue range in HSV
        lower_yellow = np.array([20, 100, 100])
        upper_yellow = np.array([30, 255, 255])
        
        # Check edges for yellow color
        edge_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        edge_mask[0:edge_thickness, :] = 255
        edge_mask[height-edge_thickness:height, :] = 255
        edge_mask[:, 0:edge_thickness] = 255
        edge_mask[:, width-edge_thickness:width] = 255
        
        yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        yellow_in_edges = cv2.bitwise_and(yellow_mask, edge_mask)
        yellow_percentage = np.sum(yellow_in_edges > 0) / np.sum(edge_mask > 0)
        
        print(f"Yellow border detection: {yellow_percentage:.3f} (>0.15 = regular card)")
        
        # If significant yellow in edges, it's a regular card
        if yellow_percentage > 0.15:
            is_full_art = False
        
        return is_full_art
        
    except Exception as e:
        print(f"Error detecting full-art card: {e}")
        return False  # Default to regular card

def compare_cards_with_vision(scanned_image_base64: str, pokemon_name: str, candidate_cards: List[dict]) -> dict:
    """
    Use AI vision to compare the scanned card image with candidate cards from database.
    Returns the best matching card.
    """
    try:
        if not candidate_cards:
            return None
        
        # Limit to top 10 candidates to avoid token limits
        candidates = candidate_cards[:10]
        
        # Build the comparison prompt
        card_descriptions = []
        for i, card in enumerate(candidates, 1):
            desc = f"{i}. {card.get('name')} - HP: {card.get('hp', 'N/A')}, Set: {card.get('set', {}).get('name', 'Unknown')}, Card #: {card.get('localId', 'N/A')}"
            if card.get('rarity'):
                desc += f", Rarity: {card.get('rarity')}"
            card_descriptions.append(desc)
        
        cards_list = "\n".join(card_descriptions)
        
        prompt = f"""You are analyzing a scanned Pokemon card image to identify which exact card it is.

The OCR detected this Pokemon name: {pokemon_name}

Here are the candidate cards from the database:
{cards_list}

TASK: Look at the scanned card image and determine which candidate card it matches.

IMPORTANT MATCHING CRITERIA (in order of importance):
1. Visual appearance - does the artwork match?
2. HP value (shown in top-right corner)
3. Card layout and style (regular, holo, full art, etc.)
4. Set symbol or design elements
5. Card number (bottom of card)

RESPONSE FORMAT:
Return ONLY a JSON object with this exact structure:
{{
    "match_number": <number 1-{len(candidates)} of the matching card>,
    "confidence": <"high", "medium", or "low">,
    "reasoning": "<brief explanation of why this card matches>"
}}

Example:
{{"match_number": 3, "confidence": "high", "reasoning": "HP 130 matches, artwork is identical, card layout matches"}}

Be precise and only return the JSON object, nothing else."""

        # Make vision API call
        response = vision_client.chat.completions.create(
            model="google/gemini-2.5-flash",  # Free vision model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": scanned_image_base64
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=200
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        result = json.loads(response_text)
        
        match_number = result.get('match_number')
        confidence = result.get('confidence', 'low')
        reasoning = result.get('reasoning', '')
        
        if match_number and 1 <= match_number <= len(candidates):
            matched_card = candidates[match_number - 1]
            print(f"✓✓✓ VISION MATCH: {matched_card.get('name')} - Confidence: {confidence}")
            print(f"    Reasoning: {reasoning}")
            
            return {
                'card': matched_card,
                'confidence': confidence,
                'reasoning': reasoning,
                'method': 'vision'
            }
        
        return None
        
    except Exception as e:
        print(f"Vision comparison error: {e}")
        import traceback
        traceback.print_exc()
        return None

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
    HP is critical for card identification and appears in top-right of card.
    """
    # Pattern for HP: "HP" followed by digits, or just "HP" near digits
    patterns = [
        r'HP\s*[:\-]?\s*(\d{2,3})',  # "HP 130", "HP: 130", "HP-130", "HP130"
        r'(\d{2,3})\s*HP',  # "130 HP"
        r'HP.*?(\d{2,3})',  # "HP" with digits nearby
        r'H\s*P\s*(\d{2,3})',  # "H P 130" (OCR spacing issues)
        r'(\d{2,3})\s*H\s*P',  # "130 H P"
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, ocr_text, re.IGNORECASE)
        if matches:
            hp_val = matches[0]
            # Validate HP is in reasonable range (10-340)
            try:
                hp_int = int(hp_val)
                if 10 <= hp_int <= 340:
                    return hp_val
            except ValueError:
                continue
    
    # Fallback: Look for standalone 2-3 digit numbers in reasonable HP range
    # This catches cases where "HP" text is missed but the number is there
    standalone_numbers = re.findall(r'\b(\d{2,3})\b', ocr_text)
    for num in standalone_numbers:
        try:
            hp_int = int(num)
            # Common HP values: 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, etc.
            # Usually multiples of 10, but not always
            if 30 <= hp_int <= 340:
                return num
        except ValueError:
            continue
    
    return None

def find_exact_card(pokemon_name: str, card_number: str = None, hp_value: str = None, set_code: str = None) -> dict:
    """
    Find the exact card from the database using Pokemon name, card number, HP, and set code
    Priority: name + HP + card_number > name + HP > card_number + set_code > card_number only > name only
    HP is now a PRIMARY matching criterion since it's reliable and unique per Pokemon variant
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
        
        # Priority 1: Match by NAME + HP + CARD NUMBER (most specific)
        if hp_value and card_number:
            try:
                hp_int = int(hp_value)
                for card in matching_cards:
                    card_hp = card.get('hp')
                    card_local_id = card.get('localId', '')
                    if card_hp and card_local_id == card_number:
                        try:
                            if int(card_hp) == hp_int:
                                print(f"✓✓✓ EXACT MATCH by name + HP + card#: {card.get('name')} HP{card_hp} #{card_local_id} from {card.get('set', {}).get('name')}")
                                return format_card_result(card)
                        except (ValueError, TypeError):
                            continue
            except (ValueError, TypeError):
                pass
        
        # Priority 2: Match by NAME + HP (very reliable)
        if hp_value:
            try:
                hp_int = int(hp_value)
                hp_matches = []
                for card in matching_cards:
                    card_hp = card.get('hp')
                    if card_hp:
                        try:
                            if int(card_hp) == hp_int:
                                hp_matches.append(card)
                        except (ValueError, TypeError):
                            continue
                
                if hp_matches:
                    # If we have multiple cards with same name and HP, prefer most recent
                    card = hp_matches[0]
                    print(f"✓✓ STRONG MATCH by name + HP: {card.get('name')} HP{card_hp} from {card.get('set', {}).get('name')} ({len(hp_matches)} variants found)")
                    return format_card_result(card)
            except (ValueError, TypeError):
                pass
        
        # Priority 3: Match by card number AND set code
        if card_number and set_code:
            for card in matching_cards:
                card_local_id = card.get('localId', '')
                card_set_id = card.get('set', {}).get('id', '').upper()
                card_set_name = card.get('set', {}).get('name', '').upper()
                
                set_code_upper = set_code.upper()
                if card_local_id == card_number:
                    if (set_code_upper in card_set_id.upper() or 
                        card_set_id.upper() in set_code_upper or
                        set_code_upper in card_set_name):
                        print(f"✓ Matched by card# + set: {card.get('name')} #{card_local_id} from {card.get('set', {}).get('name')}")
                        return format_card_result(card)
        
        # Priority 4: Match by card number only
        if card_number:
            for card in matching_cards:
                card_local_id = card.get('localId', '')
                if card_local_id == card_number:
                    print(f"⚠ Matched by card# only: {card.get('name')} #{card_local_id} from {card.get('set', {}).get('name')}")
                    return format_card_result(card)
        
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
    Uses fuzzy matching with common OCR error corrections.
    """
    if not ocr_text:
        return ""
    
    # Load Pokemon names database
    pokemon_names = load_pokemon_names()
    if not pokemon_names:
        return ocr_text
    
    # Common OCR character substitutions
    def clean_ocr_text(text):
        """Apply common OCR error corrections"""
        corrections = {
            '0': 'O', '1': 'I', '5': 'S', '8': 'B',
            '!': 'I', '|': 'I', '@': 'a', '$': 'S',
            '6': 'G', '9': 'g', '2': 'Z'
        }
        for wrong, right in corrections.items():
            text = text.replace(wrong, right)
        return text
    
    # Split into words and lines
    words = ocr_text.split()
    lines = ocr_text.split('\n')
    
    # Filter out common non-Pokemon words
    exclude_words = {
        'HP', 'STAGE', 'BASIC', 'ABILITY', 'ATTACK', 'WEAKNESS', 'RESISTANCE',
        'RETREAT', 'POKEMON', 'POKÉMON', 'ILLUSTRATOR', 'ILLUS', 'THICK', 'FAT',
        'SLAM', 'DAMAGE', 'FLIP', 'COIN', 'TURN', 'CARD', 'ENERGY', 'WATER',
        'FIRE', 'GRASS', 'ELECTRIC', 'PSYCHIC', 'FIGHTING', 'COLORLESS'
    }
    
    # Strategy 1: Direct match on first few words (highest priority)
    for i in range(min(5, len(words))):
        word = words[i].strip().upper()
        if word in exclude_words or len(word) < 3:
            continue
        
        # Try exact match first
        if word.title() in pokemon_names or word.capitalize() in pokemon_names:
            return word.title()
        
        # Try with OCR corrections
        cleaned = clean_ocr_text(word)
        if cleaned.title() in pokemon_names or cleaned.capitalize() in pokemon_names:
            return cleaned.title()
        
        # Fuzzy match with high threshold
        matches = get_close_matches(cleaned.title(), pokemon_names, n=1, cutoff=0.85)
        if matches:
            return matches[0]
    
    # Strategy 2: Check capitalized words (Pokemon names are capitalized)
    capitalized_words = [w.strip() for w in words if w and len(w) > 2 and w[0].isupper()]
    for word in capitalized_words[:7]:
        word_upper = word.upper()
        if word_upper in exclude_words:
            continue
        
        cleaned = clean_ocr_text(word)
        matches = get_close_matches(cleaned, pokemon_names, n=1, cutoff=0.80)
        if matches:
            return matches[0]
    
    # Strategy 3: Try first line (Pokemon name is usually on first line)
    if lines:
        first_line = lines[0].strip()
        # Remove HP value if present
        first_line = re.sub(r'HP\s*\d+', '', first_line, flags=re.IGNORECASE).strip()
        first_line = re.sub(r'\d+', '', first_line).strip()  # Remove all numbers
        
        if first_line and len(first_line) > 2:
            cleaned = clean_ocr_text(first_line)
            matches = get_close_matches(cleaned, pokemon_names, n=1, cutoff=0.75)
            if matches:
                return matches[0]
    
    # Strategy 4: Try each word individually with lower threshold
    for word in words[:10]:
        word = word.strip()
        if len(word) < 4 or word.upper() in exclude_words:
            continue
        
        cleaned = clean_ocr_text(word)
        matches = get_close_matches(cleaned, pokemon_names, n=1, cutoff=0.70)
        if matches:
            return matches[0]
    
    # Strategy 5: Try partial matches (for multi-word Pokemon names)
    for pokemon in pokemon_names:
        pokemon_lower = pokemon.lower()
        ocr_lower = ocr_text.lower()
        if pokemon_lower in ocr_lower or any(word.lower() == pokemon_lower for word in words):
            return pokemon
    
    # Last resort: return first meaningful word
    for word in words:
        if len(word) > 3 and word.upper() not in exclude_words:
            return clean_ocr_text(word).title()
    
    return ocr_text.split()[0] if words else ocr_text

@app.route('/api/scan', methods=['POST'])
def api_scan():
    try:
        data = request.json['image']
        # Decode the base64 image from the camera
        header, encoded = data.split(",", 1)
        nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Apply advanced pre-processing
        processed_img = prepare_image_for_ocr(img)

        # Multi-pass OCR strategy for better accuracy
        # Pass 1: Full image with EasyOCR
        results = reader.readtext(processed_img, detail=1, paragraph=False)
        
        # Pass 2: Try with original image too (sometimes works better)
        results_original = reader.readtext(img, detail=1, paragraph=False)
        
        # Combine results and remove duplicates
        all_results = results + results_original
        
        # Sort by Y-coordinate to get text from top to bottom
        results_sorted = sorted(all_results, key=lambda x: x[0][0][1])
        
        # Extract text with confidence filtering
        high_conf_text = [res[1] for res in results_sorted if res[2] > 0.3]  # Confidence > 30%
        all_text_list = [res[1] for res in results_sorted]
        
        # Separate regions by Y-coordinate for targeted extraction
        if len(results_sorted) > 0:
            # Top 30% of detections for Pokemon name and HP
            top_count = max(3, len(results_sorted) // 3)
            top_text = " ".join([res[1] for res in results_sorted[:top_count]])
            
            # Top-right region specifically for HP (rightmost text in top portion)
            top_results = results_sorted[:top_count]
            # Sort by X-coordinate to get rightmost text
            top_right_results = sorted(top_results, key=lambda x: x[0][0][0], reverse=True)
            top_right_text = " ".join([res[1] for res in top_right_results[:3]])
            
            # Bottom 30% for set code and card number
            bottom_count = max(3, len(results_sorted) // 3)
            bottom_text = " ".join([res[1] for res in results_sorted[-bottom_count:]])
        else:
            top_text = ""
            top_right_text = ""
            bottom_text = ""
        
        all_text = " ".join(all_text_list)
        high_conf_only = " ".join(high_conf_text)
        
        # Log for debugging
        print(f"=== OCR Results ===")
        print(f"Top region: {top_text}")
        print(f"Top-right region (HP area): {top_right_text}")
        print(f"Bottom region: {bottom_text}")
        print(f"High confidence: {high_conf_only}")
        print(f"All text: {all_text}")
        
        # Extract HP FIRST (most reliable identifier after name)
        # Priority: top-right region > top region > all text
        hp_value = extract_hp_value(top_right_text)
        if not hp_value:
            hp_value = extract_hp_value(top_text)
        if not hp_value:
            hp_value = extract_hp_value(all_text)
        
        # Extract Pokemon name
        # Strategy 1: Try high confidence text first
        pokemon_name = extract_pokemon_name_from_ocr(high_conf_only)
        if not pokemon_name or len(pokemon_name) < 3:
            # Strategy 2: Try top region
            pokemon_name = extract_pokemon_name_from_ocr(top_text)
        if not pokemon_name or len(pokemon_name) < 3:
            # Strategy 3: Try all text
            pokemon_name = extract_pokemon_name_from_ocr(all_text)
        
        # If still no name, try to extract ANY capitalized word as a guess
        if not pokemon_name or len(pokemon_name) < 3:
            words = all_text.split()
            for word in words:
                if word and len(word) >= 3 and word[0].isupper():
                    pokemon_name = word
                    print(f"Using fallback Pokemon name: {pokemon_name}")
                    break
        
        # Last resort: use a generic search term
        if not pokemon_name or len(pokemon_name) < 3:
            pokemon_name = "Pokemon"
            print("Could not extract Pokemon name, using generic search")
        
        # Extract other identifiers
        card_number = extract_card_number(all_text) or extract_card_number(bottom_text)
        set_code = extract_set_info(bottom_text) or extract_set_info(all_text)
        
        print(f"=== Extracted Info ===")
        print(f"Pokemon: {pokemon_name}")
        print(f"Card #: {card_number}")
        print(f"HP: {hp_value}")
        print(f"Set: {set_code}")
        
        # NEW: Analyze the scanned card to detect if it's full-art/illustration rare
        is_full_art = detect_full_art_card(img)
        print(f"Full-art detection: {is_full_art}")
        
        # Get candidate cards for vision comparison
        candidate_cards = []
        if pokemon_name and len(pokemon_name) >= 3:
            try:
                cards_file_path = os.path.join(os.path.dirname(__file__), '..', 'all_cards.json')
                with open(cards_file_path, 'r', encoding='utf-8') as f:
                    all_cards_data = json.load(f)
                
                # Find all cards matching the Pokemon name
                for card in all_cards_data:
                    card_name = card.get('name', '').lower()
                    # More lenient matching
                    if (pokemon_name.lower() in card_name or 
                        card_name.startswith(pokemon_name.lower()) or
                        any(word.lower() in card_name for word in pokemon_name.split() if len(word) > 3)):
                        candidate_cards.append(card)
                
                # Filter candidates based on full-art detection
                if is_full_art and len(candidate_cards) > 5:
                    # Prioritize illustration rare, special illustration, full art cards
                    full_art_rarities = ['illustration rare', 'special illustration rare', 'ultra rare', 'full art']
                    full_art_candidates = [c for c in candidate_cards if any(r in c.get('rarity', '').lower() for r in full_art_rarities)]
                    
                    if full_art_candidates:
                        print(f"Detected full-art card, prioritizing {len(full_art_candidates)} full-art candidates")
                        # Show full-art first, then add some regular ones
                        candidate_cards = full_art_candidates[:3] + [c for c in candidate_cards if c not in full_art_candidates][:7]
                    else:
                        print("Full-art detected but no full-art candidates found, showing all")
                elif not is_full_art and len(candidate_cards) > 5:
                    # Prioritize regular cards (not full-art)
                    regular_rarities = ['common', 'uncommon', 'rare', 'holo rare', 'rare holo', 'reverse holo']
                    regular_candidates = [c for c in candidate_cards if any(r in c.get('rarity', '').lower() for r in regular_rarities)]
                    
                    if regular_candidates:
                        print(f"Detected regular card, prioritizing {len(regular_candidates)} regular candidates")
                        # Show regular first, then add some full-art ones
                        candidate_cards = regular_candidates[:3] + [c for c in candidate_cards if c not in regular_candidates][:7]
                
                print(f"Found {len(candidate_cards)} candidate cards for vision comparison")
            except Exception as e:
                print(f"Error loading candidate cards: {e}")
        
        # Try vision-based matching first if we have candidates
        vision_match = None
        if candidate_cards and len(candidate_cards) > 1:
            print("Attempting vision-based card matching...")
            try:
                vision_match = compare_cards_with_vision(data, pokemon_name, candidate_cards)
            except Exception as e:
                print(f"Vision matching failed: {e}")
                vision_match = None
        
        # Prepare top 5 candidates with images for user selection
        top_candidates = []
        if candidate_cards:
            # Fetch full card details for all candidates at once (for proper image URLs)
            async def fetch_all_candidate_images():
                candidates_with_images = []
                for card in candidate_cards[:5]:
                    try:
                        card_id = card.get('id')
                        if card_id:
                            full_card = await sdk.card.get(card_id)
                            image_url = full_card.get_image_url(Quality.LOW, Extension.JPG)
                            
                            candidates_with_images.append({
                                'name': full_card.name,
                                'id': full_card.id,
                                'localId': full_card.localId,
                                'hp': getattr(full_card, 'hp', 'N/A'),
                                'set_name': full_card.set.name if hasattr(full_card, 'set') else 'Unknown',
                                'set_id': full_card.set.id if hasattr(full_card, 'set') else 'Unknown',
                                'rarity': getattr(full_card, 'rarity', 'Unknown'),
                                'image': image_url
                            })
                    except Exception as e:
                        print(f"Error fetching candidate card {card.get('name')}: {e}")
                        # Fallback to basic card data
                        image_url = None
                        if card.get('image'):
                            if isinstance(card['image'], dict):
                                image_url = card['image'].get('small') or card['image'].get('large')
                        
                        candidates_with_images.append({
                            'name': card.get('name'),
                            'id': card.get('id'),
                            'localId': card.get('localId'),
                            'hp': card.get('hp', 'N/A'),
                            'set_name': card.get('set', {}).get('name', 'Unknown'),
                            'set_id': card.get('set', {}).get('id', 'Unknown'),
                            'rarity': card.get('rarity', 'Unknown'),
                            'image': image_url
                        })
                
                return candidates_with_images
            
            try:
                top_candidates = asyncio.run(fetch_all_candidate_images())
            except Exception as e:
                print(f"Error fetching candidate images: {e}")
                # Fallback to basic data without images
                for card in candidate_cards[:5]:
                    top_candidates.append({
                        'name': card.get('name'),
                        'id': card.get('id'),
                        'localId': card.get('localId'),
                        'hp': card.get('hp', 'N/A'),
                        'set_name': card.get('set', {}).get('name', 'Unknown'),
                        'set_id': card.get('set', {}).get('id', 'Unknown'),
                        'rarity': card.get('rarity', 'Unknown'),
                        'image': None
                    })
        
        # If vision found a match, use it as the primary suggestion
        if vision_match and vision_match.get('confidence') in ['high', 'medium']:
            matched_card = vision_match['card']
            exact_card = format_card_result(matched_card)
            
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
                'detected_set_code': set_code,
                'confidence': vision_match['confidence'],
                'match_method': 'AI Vision',
                'reasoning': vision_match.get('reasoning', ''),
                'candidates': top_candidates,  # Include candidates for user selection
                'success': True
            })
        
        # Fallback to traditional OCR-based matching
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
                'detected_set_code': set_code,
                'confidence': 'high' if card_number and set_code else 'medium' if card_number or hp_value else 'low',
                'match_method': 'OCR',
                'candidates': top_candidates,  # Include candidates for user selection
                'success': True
            })
        else:
            # Always show candidates even if no exact match
            return jsonify({
                'name': pokemon_name if pokemon_name else "Card detected",
                'raw_text': all_text,
                'detected_info': {
                    'card_number': card_number,
                    'hp': hp_value,
                    'set_code': set_code
                },
                'confidence': 'low',
                'candidates': top_candidates,  # Always show candidates
                'success': True,
                'message': 'Please select your card from the options below' if top_candidates else 'Could not identify card'
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
