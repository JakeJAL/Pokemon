from flask import Flask, render_template, request, jsonify
from tcgdexsdk import TCGdex, Query
from tcgdexsdk.enums import Quality, Extension
import asyncio

app = Flask(__name__)
sdk = TCGdex()

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/price')
def price():
    return render_template('price.html')

@app.route('/search')
def search():
    return render_template('search.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

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
