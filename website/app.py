from flask import Flask, render_template, request, jsonify
from tcgdexsdk import TCGdex, Query
from tcgdexsdk.enums import Quality, Extension
import asyncio
import csv
import re
from database_querier import PokemonCardSearch, OpenAIClient
from dotenv import load_dotenv
import os

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
        with open('pokemon_cards_database (1).csv', mode='r', encoding='utf-8') as file:
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
    """API endpoint for Pokemon card chatbot"""
    if not pokemon_searcher:
        return jsonify({
            'error': 'Chatbot not available. Check API key configuration.'
        }), 500
    
    data = request.json
    user_message = data.get('message', '')
    top_n = data.get('top_n', 5)
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        result = pokemon_searcher.query(user_message, top_n=top_n)
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

@app.route('/api/cards', methods=['POST'])
def get_cards():
    data = request.json
    set_id = data.get('set_id')
    rarities = data.get('rarities', [])  # Now direct rarity values
    search_term = data.get('search_term', '').lower()
    card_types = data.get('card_types', [])
    
    async def fetch_cards():
        # If no set specified, search all sets
        if not set_id:
            # Use Query to search by name across all cards
            if search_term:
                cards = await sdk.card.list(Query().contains("name", search_term))
            else:
                cards = await sdk.card.list()
            
            # Process cards in parallel
            async def fetch_card_details(card_resume):
                try:
                    full_card = await sdk.card.get(card_resume.id)
                    
                    # Check rarity filter
                    if rarities and hasattr(full_card, 'rarity') and full_card.rarity not in rarities:
                        return None
                    
                    # Check card type filter
                    if card_types:
                        card_category = getattr(full_card, 'category', None)
                        if card_category not in card_types:
                            return None
                    
                    image_url = full_card.get_image_url(Quality.HIGH, Extension.PNG) if hasattr(full_card, 'get_image_url') else None
                    
                    # Get set name from the card's set info
                    set_name = full_card.set.name if hasattr(full_card, 'set') and hasattr(full_card.set, 'name') else 'Unknown Set'
                    set_id_val = full_card.set.id if hasattr(full_card, 'set') and hasattr(full_card.set, 'id') else ''
                    
                    return {
                        'name': full_card.name,
                        'rarity': full_card.rarity if hasattr(full_card, 'rarity') else 'Unknown',
                        'localId': full_card.localId,
                        'image': image_url,
                        'setName': set_name,
                        'setId': set_id_val,
                        'category': card_category if card_category else 'Unknown'
                    }
                except Exception as e:
                    print(f"Error processing card: {e}")
                    return None
            
            # Fetch all cards in parallel
            tasks = [fetch_card_details(card) for card in cards]
            results = await asyncio.gather(*tasks)
            matching_cards = [card for card in results if card is not None]
            
            return matching_cards
        else:
            # Single set logic
            if search_term:
                cards = await sdk.card.list(Query().equal("set.id", set_id).contains("name", search_term))
            else:
                cards = await sdk.card.list(Query().equal("set.id", set_id))
            
            async def fetch_card_details(card_resume):
                try:
                    full_card = await sdk.card.get(card_resume.id)
                    
                    # Check rarity filter
                    if rarities and hasattr(full_card, 'rarity') and full_card.rarity not in rarities:
                        return None
                    
                    # Check card type filter
                    if card_types:
                        card_category = getattr(full_card, 'category', None)
                        if card_category not in card_types:
                            return None
                    
                    image_url = full_card.get_image_url(Quality.HIGH, Extension.PNG) if hasattr(full_card, 'get_image_url') else None
                    
                    # Get set info
                    set_info = await sdk.set.get(set_id)
                    
                    return {
                        'name': full_card.name,
                        'rarity': full_card.rarity if hasattr(full_card, 'rarity') else 'Unknown',
                        'localId': full_card.localId,
                        'image': image_url,
                        'setName': set_info.name,
                        'setId': set_info.id,
                        'category': getattr(full_card, 'category', 'Unknown')
                    }
                except Exception as e:
                    print(f"Error processing card: {e}")
                    return None
            
            tasks = [fetch_card_details(card) for card in cards]
            results = await asyncio.gather(*tasks)
            matching_cards = [card for card in results if card is not None]
            
            return matching_cards
    
    results = asyncio.run(fetch_cards())
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True)
