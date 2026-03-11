from flask import Flask, render_template, request, jsonify
from tcgdexsdk import TCGdex, Query
from tcgdexsdk.enums import Quality, Extension
import asyncio
import csv
import re
from database_querier import PokemonCardSearch, OpenAIClient
from dotenv import load_dotenv
import os
import easyocr
import cv2
import numpy as np
import base64
from difflib import get_close_matches

# Load environment variables
load_dotenv()

app = Flask(__name__)
sdk = TCGdex()

# Initialize the Pokemon card search system
try:
    llm = OpenAIClient(model="gpt-3.5-turbo")
    pokemon_searcher = PokemonCardSearch("pokemon_cards_database.csv", llm)
except Exception as e:
    print(f"Error initializing Pokemon search system: {e}")
    pokemon_searcher = None

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
        with open('pokemon_cards_database.csv', mode='r', encoding='utf-8') as file:
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

@app.route('/api/chat', methods=['POST'])
def chat_api():
    """API endpoint for Pokemon card chatbot with Collection awareness"""
    if not pokemon_searcher:
        return jsonify({
            'error': 'Chatbot not available. Check API key configuration.'
        }), 500
    
    data = request.json
    user_message = data.get('message', '')
    top_n = data.get('top_n', 5)
    
    # NEW: Grab the collection data sent from the browser's localStorage
    user_collection = data.get('collection', {})
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        # Pass the user_collection into the query method so the LLM knows what's owned
        result = pokemon_searcher.query(
            user_message, 
            top_n=top_n, 
            collection=user_collection
        )
        
        return jsonify({
            'response': result['response'],
            'results': result['results'],
            'num_results': result['num_results']
        })
    except Exception as e:
        return jsonify({
            'error': f'Sorry, I encountered an error: {str(e)}'
        }), 500

@app.route('/api/sets', methods=['GET'])
def get_sets():
    sets = asyncio.run(sdk.set.list())
    return jsonify([{'id': s.id, 'name': s.name} for s in sets])

@app.route('/collection')
def collection():
    return render_template('collection.html')

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
    per_page = 20
    
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

@app.route('/api/scan', methods=['POST'])
def api_scan():
    try:
        data = request.json['image']
        # Decode the base64 image from the camera
        header, encoded = data.split(",", 1)
        nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # EasyOCR is smart! It doesn't need as much pre-processing as Tesseract.
        # We just pass the image directly.
        results = reader.readtext(img)

        # results is a list: [ ([[coords]], "text", confidence), ... ]
        # We'll join all detected text together to look for the Pokemon name
        detected_text = " ".join([res[1] for res in results])
        
        # Tinka Tip: In a real app, you'd search your CSV for 'detected_text'
        # For now, let's just return what we found!
        return jsonify({
            'name': detected_text if detected_text else "No text detected",
            'success': True
        })
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

def find_best_card_match(detected_text, card_list):
    # This looks for the closest name in your CSV
    matches = get_close_matches(detected_text, card_list, n=1, cutoff=0.6)
    return matches[0] if matches else detected_text

if __name__ == '__main__':
    app.run(debug=True)
