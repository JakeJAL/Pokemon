import os
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
import pandas as pd
import json
import re
from typing import List, Dict, Any, Tuple, Optional

# Load environment variables from the parent directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

api_key=os.getenv("API_KEY")
endpoint=os.getenv("ENDPOINT")

chat_client = OpenAI(api_key=api_key, 
                    base_url=endpoint)

# Connect to ChromaDB - look in parent directory
chroma_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db")
client = chromadb.PersistentClient(path=chroma_path)
collection = client.get_collection(name="tcg_cards")

def parse_price_constraints(query: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse price constraints from user query.
    Returns (min_price, max_price) tuple where None means no constraint.
    """
    query_lower = query.lower()
    min_price = None
    max_price = None
    
    # Patterns for price constraints
    price_patterns = [
        # "over £5", "above £10", "more than £15"
        (r'(?:over|above|more than|greater than)\s*£?(\d+(?:\.\d+)?)', 'min'),
        # "under £10", "below £20", "less than £15"
        (r'(?:under|below|less than|cheaper than)\s*£?(\d+(?:\.\d+)?)', 'max'),
        # "between £5 and £15"
        (r'between\s*£?(\d+(?:\.\d+)?)\s*and\s*£?(\d+(?:\.\d+)?)', 'range'),
        # "£5 to £15", "£10-£20"
        (r'£?(\d+(?:\.\d+)?)\s*(?:to|-)\s*£?(\d+(?:\.\d+)?)', 'range'),
        # "around £10", "about £15"
        (r'(?:around|about|approximately)\s*£?(\d+(?:\.\d+)?)', 'around'),
    ]
    
    for pattern, constraint_type in price_patterns:
        matches = re.findall(pattern, query_lower)
        if matches:
            if constraint_type == 'min':
                min_price = float(matches[0])
            elif constraint_type == 'max':
                max_price = float(matches[0])
            elif constraint_type == 'range':
                if isinstance(matches[0], tuple):
                    min_price = float(matches[0][0])
                    max_price = float(matches[0][1])
                else:
                    # Single match case
                    prices = [float(x) for x in matches[0].split()]
                    if len(prices) >= 2:
                        min_price = min(prices)
                        max_price = max(prices)
            elif constraint_type == 'around':
                target_price = float(matches[0])
                # Allow ±20% range around target price
                min_price = target_price * 0.8
                max_price = target_price * 1.2
            break
    
    return min_price, max_price

# Load all cards data for direct searching
ALL_CARDS_DATA = None

def load_all_cards_data():
    """Load all cards data from JSON file"""
    global ALL_CARDS_DATA
    if ALL_CARDS_DATA is None:
        try:
            cards_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "all_cards.json")
            with open(cards_file_path, 'r', encoding='utf-8') as f:
                ALL_CARDS_DATA = json.load(f)
            print(f"Loaded {len(ALL_CARDS_DATA)} cards from all_cards.json")
        except Exception as e:
            ALL_CARDS_DATA = []
    return ALL_CARDS_DATA

def search_cards_by_pokemon_name(pokemon_name: str, rarity_filter: str = None) -> List[Dict]:
    """Search for all cards of a specific Pokemon directly from the JSON data"""
    all_cards = load_all_cards_data()
    
    if not all_cards:
        return []
    
    matching_cards = []
    search_term = pokemon_name.lower().strip()
    
    for card in all_cards:
        card_name = card.get('name', '').lower().strip()
        
        # More flexible matching - exact name match or starts with the Pokemon name
        if (search_term == card_name or 
            card_name.startswith(search_term + ' ') or 
            card_name.startswith(search_term + "'") or
            search_term in card_name):
            
            # Convert to the same format as ChromaDB results
            card_info = {
                'name': card.get('name', 'Unknown'),
                'card_id': card.get('id', 'Unknown'),
                'hp': card.get('hp', 'Unknown'),
                'types': card.get('types', 'Unknown'),
                'rarity': card.get('rarity', 'Unknown'),
                'set_name': card.get('set', {}).get('name', 'Unknown'),
                'set_id': card.get('set', {}).get('id', 'Unknown'),
                'series_name': card.get('set', {}).get('series', {}).get('name', 'Unknown') if isinstance(card.get('set', {}), dict) else 'Unknown',
                'artist': card.get('illustrator', 'Unknown')
            }
            
            # Apply rarity filter if specified
            if rarity_filter:
                card_rarity = card_info['rarity'].lower()
                rarity_filter_lower = rarity_filter.lower()
                
                # Handle special cases for common terms
                rarity_mappings = {
                    'full art': ['full art', 'illustration rare', 'special illustration'],
                    'illustration rare': ['illustration rare', 'special illustration'],
                    'alternate art': ['alternate art', 'alt art'],
                    'rainbow rare': ['rainbow rare', 'hyper rare'],
                    'secret rare': ['secret rare'],
                    'ultra rare': ['ultra rare'],
                    'holo rare': ['holo rare', 'rare holo'],
                    'reverse holo': ['reverse holo'],
                    'promo': ['promo', 'promotional']
                }
                
                # Check if the rarity filter matches
                rarity_match = False
                
                # First check direct mappings
                if rarity_filter_lower in rarity_mappings:
                    for mapped_rarity in rarity_mappings[rarity_filter_lower]:
                        if mapped_rarity in card_rarity:
                            rarity_match = True
                            break
                else:
                    # Check for exact match or partial match
                    if (rarity_filter_lower in card_rarity or 
                        any(keyword in card_rarity for keyword in rarity_filter_lower.split())):
                        rarity_match = True
                
                if not rarity_match:
                    continue
            
            matching_cards.append(card_info)
    
    # Sort by rarity (rarest first) and return more results
    rarity_order = {
        'Secret Rare': 1, 'Ultra Rare': 2, 'Hyper rare': 3, 'Special illustration rare': 4,
        'Illustration rare': 5, 'Double rare': 6, 'Shiny rare': 7, 'Holo Rare': 8,
        'Rare Holo': 9, 'Rare': 10, 'Uncommon': 11, 'Common': 12
    }
    
    def get_rarity_priority(card):
        rarity = card.get('rarity', 'Common')
        return rarity_order.get(rarity, 99)
    
    matching_cards.sort(key=get_rarity_priority)
    
    # Return up to 50 cards instead of 20 to show more variety
    return matching_cards[:50]


class PokemonCardSearch:
    """Pokemon card search system for finding store availability"""
    
    def __init__(self, csv_path: str):
        """Initialize the Pokemon card search system."""
        try:
            self.df = pd.read_csv(csv_path)
            # Convert price column to numeric, handling any non-numeric values
            self.df['price'] = pd.to_numeric(self.df['price'], errors='coerce')
            self.available = True
        except FileNotFoundError:
            self.available = False
    
    def search_for_card(self, card_name: str, top_n: int = 3) -> pd.DataFrame:
        """Search for a specific card in the store database."""
        if not self.available:
            return pd.DataFrame()
        
        df = self.df.copy()
        
        # Search for the card name in the title field (use regex=False for literal string matching)
        mask = df['title'].str.lower().str.contains(card_name.lower(), case=False, na=False, regex=False)
        results = df[mask].sort_values('price', ascending=True)
        
        return results.head(top_n)
    
    def get_available_cards_from_chromadb(self, retrieved_cards: List[Dict]) -> List[Dict]:
        """Filter ChromaDB results to only include cards available in stores."""
        if not self.available:
            return []
        
        available_cards = []
        for card in retrieved_cards:
            # Search for this card in the store database
            store_results = self.search_for_card(card['name'])
            if not store_results.empty:
                # Add store information to the card data
                card_with_stores = card.copy()
                card_with_stores['store_options'] = []
                for _, row in store_results.iterrows():
                    card_with_stores['store_options'].append({
                        'title': row['title'],
                        'price': row['price'],
                        'source': row['source'],
                        'url': row['url']
                    })
                available_cards.append(card_with_stores)
        
        return available_cards
    
    def search_for_set_products(self, set_names: List[str], top_n: int = 5, query: str = "") -> pd.DataFrame:
        """Search for booster packs, boxes, and other products from specific sets."""
        if not self.available:
            return pd.DataFrame()
        
        df = self.df.copy()
        
        # Detect if user wants a specific language
        query_lower = query.lower()
        language_keywords = {
            'japanese': ['japanese', 'japan'],
            'french': ['french', 'france'],
            'german': ['german', 'germany'],
            'spanish': ['spanish', 'spain'],
            'italian': ['italian', 'italy'],
            'korean': ['korean', 'korea'],
            'chinese': ['chinese', 'china']
        }
        
        requested_language = None
        for lang, keywords in language_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                requested_language = lang
                break
        
        # Keywords that indicate set products (not individual cards) - all lowercase
        # Note: Order matters - more specific terms first to avoid over-matching
        product_keywords = [
            'booster pack', 'booster box', 'elite trainer box', 'trainer box',
            'collection box', 'premium collection', 'booster', 'pack', 'box',
            'bundle', 'tin', 'case', 'display'
        ]
        
        # Create mask for products (not individual cards)
        product_mask = pd.Series([False] * len(df))
        for keyword in product_keywords:
            # Convert both to lowercase for comparison
            keyword_mask = df['title'].str.lower().str.contains(keyword.lower(), case=False, na=False, regex=False)
            product_mask |= keyword_mask
        
        # Language filtering - default to English unless specific language requested
        if not requested_language:
            # Exclude non-English products
            non_english_terms = ['japanese', 'japan', 'jp', 'french', 'france', 'german', 'germany',
                               'spanish', 'spain', 'italian', 'italy', 'korean', 'korea', 'chinese', 'china']
            
            language_mask = pd.Series([False] * len(df))
            for term in non_english_terms:
                language_mask |= df['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
            
            product_mask = product_mask & ~language_mask
        
        # Create mask for set names with improved matching
        set_mask = pd.Series([False] * len(df))
        for set_name in set_names:
            if not set_name or set_name.lower() == 'unknown':
                continue
            
            # Try exact set name match first
            exact_match = df['title'].str.lower().str.contains(set_name.lower(), case=False, na=False, regex=False)
            set_mask |= exact_match
            
            # Also try matching key words from the set name
            set_words = set_name.lower().split()
            if len(set_words) > 1:  # Only for multi-word set names
                set_word_mask = pd.Series([True] * len(df))
                
                for word in set_words:
                    if len(word) > 2 and word not in ['and', 'the', 'of', 'in']:  # Skip common words
                        word_mask = df['title'].str.lower().str.contains(word.lower(), case=False, na=False, regex=False)
                        set_word_mask &= word_mask
                
                set_mask |= set_word_mask
        
        # Must NOT contain any of these (individual cards and accessories)
        exclusion_terms = [
            ' - 0', ' - 1', ' - 2', ' - 3', ' - 4', ' - 5', ' - 6', ' - 7', ' - 8', ' - 9',
            '/132', '/182', '/195', '/193', '/264', '/198', '/159', '/251', '/230',
            'energy card', 'basic energy', 'fighting energy', 'fire energy', 'water energy', 
            'grass energy', 'psychic energy', 'lightning energy', 'darkness energy', 'metal energy',
            ' ex ', ' v ', ' vmax ', ' vstar ', ' gx ', 'holo', 'reverse holo', 'full art', 
            'online code card', 'code card', 'card divider', 'divider', 'sleeves', 'deck box', 
            'playmat', 'outer sleeve', 'sticker', 'art card', 'empty tin', 'empty box', 'empty',
            'dice', 'coin', 'jumbo', 'promo', 'used empty', 'random used', 'used',
            'single card', 'individual card', 'rare card', 'common card', 'uncommon card'
        ]
        
        # Apply exclusions
        exclusion_mask = pd.Series([False] * len(df))
        for term in exclusion_terms:
            exclusion_mask |= df['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
        
        # Combine masks: must be a product AND from one of the sets AND not excluded
        final_mask = product_mask & set_mask & ~exclusion_mask
        results = df[final_mask].sort_values('price', ascending=True)
        
        return results.head(top_n)
    
    def detect_set_query(self, query: str, retrieved_cards: List[Dict]) -> bool:
        """Detect if the user is asking about sets/packs rather than individual cards."""
        # Convert query to lowercase for comparison
        query_lower = query.lower()
        
        # Set-related keywords (all lowercase) - prioritize pack-related terms
        set_keywords = [
            'pack', 'packs', 'booster', 'booster pack', 'booster packs',
            'booster box', 'box', 'boxes', 'elite trainer box', 'trainer box',
            'set', 'sets', 'collection', 'series', 'expansion', 'bundle', 'tin'
        ]
        
        # Keywords that indicate asking about which sets contain cards
        set_inquiry_keywords = [
            'what set', 'which set', 'what sets', 'which sets',
            'sets contain', 'set contains', 'sets have', 'set has',
            'found in', 'available in', 'comes from', 'from which set',
            'in what set', 'in which set', 'what expansion', 'which expansion',
            'give me sets', 'show me sets', 'find sets', 'sets with',
            'sets that have', 'sets that contain', 'list sets'
        ]
        
        # Check if query contains set inquiry keywords
        has_set_inquiry = any(keyword in query_lower for keyword in set_inquiry_keywords)
        
        # Check if query contains set-related keywords
        has_set_keywords = any(keyword in query_lower for keyword in set_keywords)
        
        # If asking about sets containing cards, it's definitely a set query
        if has_set_inquiry:
            return True
        
        # Special case: if query mentions "cheapest" or "cheap" with pack keywords, it's definitely a set query
        if ('cheap' in query_lower or 'cheapest' in query_lower or 'affordable' in query_lower or 'budget' in query_lower):
            pack_keywords = ['pack', 'packs', 'booster', 'box', 'boxes', 'set', 'bundle']
            if any(pk in query_lower for pk in pack_keywords):
                return True
        
        # Check if multiple cards from the same set are returned
        if len(retrieved_cards) > 1:
            set_names = [card.get('set_name', '').lower() for card in retrieved_cards if card.get('set_name')]
            unique_sets = set(set_names)
            # If most cards are from the same few sets, likely a set query
            if len(unique_sets) <= 3 and len(retrieved_cards) >= 5:
                has_set_keywords = True
        
        return has_set_keywords
    
    def find_sets_containing_cards(self, retrieved_cards: List[Dict], query: str = "") -> Dict[str, List[Dict]]:
        """Find which sets contain the queried cards and check for available products."""
        if not self.available:
            return {}
        
        # Group cards by their sets
        sets_with_cards = {}
        for card in retrieved_cards:
            set_name = card.get('set_name', '')
            if set_name and set_name != 'Unknown':
                if set_name not in sets_with_cards:
                    sets_with_cards[set_name] = []
                sets_with_cards[set_name].append(card)
        
        # For each set, check if products are available
        sets_with_products = {}
        for set_name, cards in sets_with_cards.items():
            products = self.search_for_set_products([set_name], top_n=5, query=query)
            if not products.empty:
                sets_with_products[set_name] = {
                    'cards': cards,
                    'products': []
                }
                for _, product in products.iterrows():
                    sets_with_products[set_name]['products'].append({
                        'title': product['title'],
                        'price': product['price'],
                        'source': product['source'],
                        'url': product['url']
                    })
        
        return sets_with_products
    
    def format_store_results(self, results: pd.DataFrame, card_name: str) -> str:
        """Format store search results for Professor Oak's response."""
        if results.empty:
            return f"I'm afraid I don't see {card_name} available in any stores right now, young trainer."
        
        store_info = f"\nNow, if you're looking to add {card_name} to your collection, here's where you might find it:\n\n"
        for _, row in results.iterrows():
            store_info += f"• {row['title']} - £{row['price']:.2f} at {row['source']}\n"
        
        return store_info


# Initialize store search - look for CSV in the website directory
csv_path = os.path.join(os.path.dirname(__file__), "pokemon_cards_database.csv")
store_searcher = PokemonCardSearch(csv_path)

def professor_oak_query(query: str) -> Dict[str, Any]:
    """
    Main function to process user query and return Professor Oak's response.
    
    Args:
        query: Natural language query from user
        
    Returns:
        Dictionary with response, results, and metadata
    """
    # Check if this is a pure product query (skip ChromaDB card search)
    query_lower = query.lower()
    
    # Check for general TCG information queries
    general_info_keywords = [
        'newest set', 'latest set', 'most recent set', 'when was', 'release date',
        'how many sets', 'what sets are', 'list all sets', 'all sets',
        'when did', 'what year', 'release schedule', 'upcoming sets'
    ]
    
    is_general_info_query = any(keyword in query_lower for keyword in general_info_keywords)
    
    if is_general_info_query:
        return _handle_general_info_query(query)
    
    # Check for price constraints
    min_price, max_price = parse_price_constraints(query)
    has_price_constraints = min_price is not None or max_price is not None
    
    pure_product_keywords = ['cheapest', 'cheap', 'affordable', 'budget', 'best value', 'best price', 'lowest price']
    pack_keywords = ['pack', 'packs', 'booster', 'box', 'boxes', 'bundle', 'tin', 'set', 'product', 'products']
    rarity_keywords = [
        'rare', 'rarest', 'valuable', 'expensive', 'ultra rare', 'secret rare',
        'full art', 'illustration rare', 'special illustration', 'alternate art',
        'rainbow rare', 'gold card', 'shiny', 'holo rare', 'reverse holo',
        'promo', 'first edition', '1st edition', 'shadowless', 'base set',
        'vmax', 'vstar', 'v card', 'ex card', 'gx card', 'prime', 'legend'
    ]
    
    # Don't treat as pure product query if asking about rare cards
    is_rarity_query = any(rarity_word in query_lower for rarity_word in rarity_keywords)
    
    # Enhanced detection for product queries
    is_pure_product_query = (
        (any(price_word in query_lower for price_word in pure_product_keywords) or has_price_constraints) and
        any(pack_word in query_lower for pack_word in pack_keywords) and
        not any(card_word in query_lower for card_word in ['card', 'cards']) and  # Exclude if asking about cards
        not is_rarity_query and  # Exclude if asking about rare items
        not any(set_inquiry in query_lower for set_inquiry in ['sets with', 'give me sets', 'show me sets', 'sets contain', 'sets have'])  # Exclude set inquiry queries
    )
    
    if is_pure_product_query:
        return _handle_product_query(query, min_price, max_price)
    else:
        return _handle_card_query(query)


def _handle_general_info_query(query: str) -> Dict[str, Any]:
    """Handle general Pokemon TCG information queries"""
    try:
        # Load all cards to analyze set information
        all_cards = load_all_cards_data()
        
        if not all_cards:
            return {
                'response': "I'm having trouble accessing my Pokemon TCG database right now, young trainer.",
                'results': [],
                'num_results': 0,
                'query_type': 'general_info'
            }
        
        # Extract set information from all cards
        sets_info = {}
        for card in all_cards:
            set_data = card.get('set', {})
            if isinstance(set_data, dict):
                set_name = set_data.get('name', 'Unknown')
                set_id = set_data.get('id', 'Unknown')
                series_name = set_data.get('series', {}).get('name', 'Unknown') if isinstance(set_data.get('series'), dict) else 'Unknown'
                release_date = set_data.get('releaseDate', 'Unknown')
                
                if set_name != 'Unknown' and set_name not in sets_info:
                    sets_info[set_name] = {
                        'id': set_id,
                        'series': series_name,
                        'release_date': release_date,
                        'card_count': 0
                    }
                
                if set_name in sets_info:
                    sets_info[set_name]['card_count'] += 1
        
        # Build context for the AI
        sets_context = "Here is information about Pokemon TCG sets:\n\n"
        
        # Sort sets by release date (newest first) if available
        sorted_sets = []
        for set_name, info in sets_info.items():
            release_date = info['release_date']
            # Try to parse the date for sorting
            try:
                if release_date != 'Unknown' and release_date:
                    # Assuming date format is YYYY-MM-DD or similar
                    sorted_sets.append((set_name, info, release_date))
            except:
                sorted_sets.append((set_name, info, '0000-00-00'))
        
        # Sort by release date (newest first)
        sorted_sets.sort(key=lambda x: x[2], reverse=True)
        
        # Add top 20 most recent sets to context
        for i, (set_name, info, release_date) in enumerate(sorted_sets[:20]):
            sets_context += f"SET: {set_name}\n"
            sets_context += f"  ID: {info['id']}\n"
            sets_context += f"  Series: {info['series']}\n"
            sets_context += f"  Release Date: {release_date}\n"
            sets_context += f"  Cards in Database: {info['card_count']}\n"
            sets_context += f"  ---\n\n"
        
        # Create AI prompt for general info
        prompt = f"""You are Professor Oak answering a general question about Pokemon TCG sets and releases.

CRITICAL FORMATTING RULES:
1. NEVER use ** or any markdown formatting (bold, italic, etc.)
2. Use simple, clean text formatting only
3. Be conversational and friendly
4. Provide specific information when available

CONTENT RULES:
1. Answer the user's question directly using the set information provided
2. For "newest set" questions, identify the most recent set by release date
3. For release date questions, provide the specific date if available
4. For general set questions, provide relevant information
5. Be helpful and informative

SET INFORMATION (sorted by release date, newest first):
{sets_context}

User Question: {query}

Answer the question directly and helpfully. If asking about the newest set, identify it clearly with its release date."""

        try:
            response = chat_client.chat.completions.create(
                model="google/gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": "You are Professor Oak, a Pokemon expert. Answer questions about Pokemon TCG sets and releases using only the provided information. Never use markdown formatting. Be friendly and conversational."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            response_text = response.choices[0].message.content
            
            return {
                'response': response_text,
                'results': [],
                'num_results': len(sets_info),
                'query_type': 'general_info'
            }
            
        except Exception as e:
            return {
                'response': f"I'm having trouble organizing my thoughts about Pokemon sets right now, young trainer. Error: {str(e)}",
                'results': [],
                'num_results': 0,
                'query_type': 'general_info'
            }
        
    except Exception as e:
        return {
            'response': f"I'm having trouble accessing my Pokemon TCG knowledge right now, young trainer. Error: {str(e)}",
            'results': [],
            'num_results': 0,
            'query_type': 'general_info'
        }


def _handle_product_query(query: str, min_price: Optional[float] = None, max_price: Optional[float] = None) -> Dict[str, Any]:
    """Handle pure product queries (cheapest packs, etc.)"""
    # Search for all products (empty string matches all sets)
    df = store_searcher.df.copy() if store_searcher.available else pd.DataFrame()
    
    if df.empty:
        return {
            'response': "I'm afraid I don't see any products available right now, young trainer!",
            'results': [],
            'num_results': 0,
            'query_type': 'product'
        }
    
    # Detect if user wants a specific language
    query_lower = query.lower()
    language_keywords = {
        'japanese': ['japanese', 'japan'],
        'french': ['french', 'france'],
        'german': ['german', 'germany'],
        'spanish': ['spanish', 'spain'],
        'italian': ['italian', 'italy'],
        'korean': ['korean', 'korea'],
        'chinese': ['chinese', 'china']
    }
    
    requested_language = None
    for lang, keywords in language_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            requested_language = lang
            break
    
    # Look specifically for actual booster products (not accessories)
    required_product_terms = [
        'booster pack', 'booster box', 'elite trainer box', 'collection box',
        'premium collection', 'bundle'
    ]
    
    # Must NOT contain any of these (accessories/individual items)
    exclusion_terms = [
        ' - 0', ' - 1', ' - 2', ' - 3', ' - 4', ' - 5', ' - 6', ' - 7', ' - 8', ' - 9',
        '/132', '/182', '/195', '/193', '/264', '/198', '/159', '/251', '/230',
        'energy card', 'basic energy', ' ex ', ' v ', ' vmax ', ' vstar ',
        'holo', 'reverse holo', 'full art', 'online code card', 'code card',
        'card divider', 'divider', 'sleeves', 'deck box', 'playmat',
        'outer sleeve', 'sticker', 'art card', 'empty tin', 'empty box', 'empty',
        'dice', 'coin', 'jumbo', 'promo', 'used empty', 'random used', 'used',
        'fighting energy', 'fire energy', 'water energy', 'grass energy',
        'psychic energy', 'lightning energy', 'darkness energy', 'metal energy'
    ]
    
    # If no specific language requested, exclude non-English products
    if not requested_language:
        exclusion_terms.extend([
            'japanese', 'japan', 'jp', 'french', 'france', 'german', 'germany',
            'spanish', 'spain', 'italian', 'italy', 'korean', 'korea', 'chinese', 'china'
        ])
    
    # Filter products
    product_mask = pd.Series([False] * len(df))
    for term in required_product_terms:
        product_mask |= df['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
    
    exclusion_mask = pd.Series([False] * len(df))
    for term in exclusion_terms:
        exclusion_mask |= df['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
    
    final_mask = product_mask & ~exclusion_mask
    all_products = df[final_mask].copy()
    all_products['price'] = pd.to_numeric(all_products['price'], errors='coerce')
    all_products = all_products[all_products['price'] >= 1.0]
    
    # Apply price constraints if specified
    if min_price is not None:
        all_products = all_products[all_products['price'] > min_price]
    
    if max_price is not None:
        all_products = all_products[all_products['price'] < max_price]
    
    # Sort by price (ascending for cheapest first, unless asking for expensive items)
    if 'expensive' in query.lower() or 'costly' in query.lower() or 'pricey' in query.lower():
        all_products = all_products.sort_values('price', ascending=False).head(20)
    else:
        all_products = all_products.sort_values('price', ascending=True).head(20)
    
    if all_products.empty:
        return {
            'response': "I'm afraid I don't see any products matching your criteria right now, young trainer!",
            'results': [],
            'num_results': 0,
            'query_type': 'product'
        }
    
    # Build context for products
    price_desc = ""
    if min_price is not None and max_price is not None:
        price_desc = f" (£{min_price:.2f} - £{max_price:.2f})"
    elif min_price is not None:
        price_desc = f" (over £{min_price:.2f})"
    elif max_price is not None:
        price_desc = f" (under £{max_price:.2f})"
    
    products_context = f"Here are booster packs and products{price_desc}:\n\n"
    for i, (_, product) in enumerate(all_products.iterrows(), 1):
        products_context += f"Product #{i}:\n"
        products_context += f"  Title: {product['title']}\n"
        products_context += f"  Price: £{product['price']:.2f}\n"
        products_context += f"  Store: {product['source']}\n"
        products_context += f"  URL: {product['url']}\n"
        products_context += f"  ---\n\n"

    # Create prompt for products
    product_prompt = f"""You are Professor Oak helping a trainer find affordable packs. Keep it SHORT - recommend TOP 5 cheapest products only.

CRITICAL RULES:
1. Recommend ONLY the TOP 5 cheapest products from the list below
2. NEVER change product information, prices, or URLs
3. Keep each recommendation to 1-2 sentences maximum
4. Focus on best value for money

AVAILABLE PRODUCTS:
{products_context}

User Question: {query}

Briefly recommend the TOP 5 cheapest products. For each:
- Product name and price
- Why it's good value
- Include the store URL

Keep it short and helpful!"""

    # Convert products to results format
    results = []
    for _, product in all_products.head(5).iterrows():
        results.append({
            'title': product['title'],
            'price': product['price'],
            'source': product['source'],
            'url': product['url']
        })
    
    # Use short response since we have results to show
    if len(results) > 0:
        price_desc = ""
        if min_price is not None and max_price is not None:
            price_desc = f" between £{min_price:.2f} and £{max_price:.2f}"
        elif min_price is not None:
            price_desc = f" over £{min_price:.2f}"
        elif max_price is not None:
            price_desc = f" under £{max_price:.2f}"
        
        response_text = f"I found {len(results)} great booster pack options{price_desc} for you, young trainer!"
    else:
        price_desc = ""
        if min_price is not None and max_price is not None:
            price_desc = f" between £{min_price:.2f} and £{max_price:.2f}"
        elif min_price is not None:
            price_desc = f" over £{min_price:.2f}"
        elif max_price is not None:
            price_desc = f" under £{max_price:.2f}"
        
        response_text = f"I'm afraid I don't see any products{price_desc} matching your criteria right now, young trainer!"
    
    return {
        'response': response_text,
        'results': results,
        'num_results': len(all_products),
        'query_type': 'product'
    }


def _handle_card_query(query: str) -> Dict[str, Any]:
    """Handle card-based queries"""
    try:
        # Check if this is a rarity-based query
        rarity_keywords = [
            'rare', 'rarest', 'valuable', 'expensive', 'ultra rare', 'secret rare',
            'full art', 'illustration rare', 'special illustration', 'alternate art',
            'rainbow rare', 'gold card', 'shiny', 'holo rare', 'reverse holo',
            'promo', 'first edition', '1st edition', 'shadowless', 'base set',
            'vmax', 'vstar', 'v card', 'ex card', 'gx card', 'prime', 'legend'
        ]
        is_rarity_query = any(keyword in query.lower() for keyword in rarity_keywords)
        
        # Check for specific Pokemon queries using improved detection
        query_words = query.lower().split()
        common_words = {'show', 'me', 'tell', 'about', 'find', 'get', 'cards', 'card', 'pokemon', 'pokémon', 
                       'the', 'a', 'an', 'and', 'or', 'but', 'for', 'with', 'from', 'what', 'are', 'is',
                       'rare', 'best', 'good', 'powerful', 'strong', 'cool', 'awesome', 'legendary', 'all',
                       'some', 'any', 'have', 'has', 'do', 'does', 'can', 'could', 'would', 'should'}
        
        # More sophisticated Pokemon name detection
        potential_pokemon_names = []
        
        # First, remove rarity keywords from the query to better isolate Pokemon names
        query_without_rarity = query.lower()
        for rarity_keyword in rarity_keywords:
            query_without_rarity = query_without_rarity.replace(rarity_keyword, ' ')
        
        # Clean up extra spaces
        query_without_rarity = ' '.join(query_without_rarity.split())
        query_words_clean = query_without_rarity.split()
        
        for word in query_words_clean:
            if (word not in common_words and 
                len(word) > 2 and 
                word.isalpha() and  # Only alphabetic characters
                not word.endswith('s')):  # Avoid plurals like "cards"
                potential_pokemon_names.append(word)
        
        # Also check for common Pokemon name patterns (expanded list)
        pokemon_patterns = [
            r'\b(pikachu|charizard|blastoise|venusaur|mewtwo|mew|lugia|ho-oh|rayquaza|kyogre|groudon|dialga|palkia|giratina|arceus|reshiram|zekrom|kyurem|xerneas|yveltal|zygarde|solgaleo|lunala|necrozma|zacian|zamazenta|eternatus|calyrex|umbreon|espeon|vaporeon|jolteon|flareon|leafeon|glaceon|sylveon|dewgong|alakazam|machamp|gengar|dragonite|tyranitar|salamence|metagross|garchomp|lucario|zoroark|greninja|talonflame|decidueye|incineroar|primarina)\b',
            r'\b([a-z]{4,})\b(?=\s+(?:card|cards|pokemon|pokémon))'
        ]
        
        for pattern in pokemon_patterns:
            matches = re.findall(pattern, query.lower())
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1]
                if match and match not in potential_pokemon_names:
                    potential_pokemon_names.append(match)
        
        # Try to get cards using direct JSON search for specific Pokemon
        retrieved_cards = []
        specific_pokemon_found = None
        
        # Handle combined Pokemon + rarity queries (e.g., "rare umbreon cards")
        if potential_pokemon_names and is_rarity_query:
            # Extract the rarity term from the query
            detected_rarity = None
            for rarity_keyword in rarity_keywords:
                if rarity_keyword in query.lower():
                    detected_rarity = rarity_keyword
                    break
            
            # For Pokemon + rarity queries, search for the Pokemon with rarity filter
            for pokemon_name in potential_pokemon_names:
                direct_cards = search_cards_by_pokemon_name(pokemon_name, detected_rarity)
                if direct_cards:
                    retrieved_cards.extend(direct_cards)
                    specific_pokemon_found = pokemon_name.title()
        elif potential_pokemon_names and not is_rarity_query:
            # For specific Pokemon queries without rarity, search directly in JSON
            for pokemon_name in potential_pokemon_names:
                direct_cards = search_cards_by_pokemon_name(pokemon_name)
                if direct_cards:
                    retrieved_cards.extend(direct_cards)
                    specific_pokemon_found = pokemon_name.title()
        
        # Remove duplicates while preserving order
        if retrieved_cards:
            seen = set()
            unique_cards = []
            for card in retrieved_cards:
                card_key = (card['name'], card['card_id'])
                if card_key not in seen:
                    seen.add(card_key)
                    unique_cards.append(card)
            retrieved_cards = unique_cards[:50]  # Increased limit to show more variety
        
        # If no direct search results, use ChromaDB as fallback
        if not retrieved_cards:
            if is_rarity_query and not potential_pokemon_names:
                # Pure rarity query without specific Pokemon
                retrieved_cards = _get_rare_cards(query)
            else:
                # General search or fallback
                retrieved_cards = _get_regular_cards(query)
        
        if not retrieved_cards:
            return {
                'response': "I couldn't find any cards matching your query, young trainer. Try being more specific!",
                'results': [],
                'num_results': 0,
                'query_type': 'card'
            }
        
        # Build context and get AI response
        context = _build_card_context(retrieved_cards)
        is_set_query = store_searcher.detect_set_query(query, retrieved_cards)
        
        # Temporary debug - remove this later
        if 'sets with' in query.lower() or 'give me sets' in query.lower():
            is_set_query = True  # Force set query detection for this pattern
        
        # Set query type based on detection
        query_type = 'set' if is_set_query else 'card'
        
        # Get store availability first to determine response style
        store_results = _get_store_availability(query, retrieved_cards, is_set_query, potential_pokemon_names)
        
        # Always provide full response for rarity queries and specific Pokemon queries
        if is_rarity_query or specific_pokemon_found:
            response_text = _get_card_response(query, retrieved_cards, context, specific_pokemon_found)
        elif is_set_query:
            # For set queries, always provide the full set response explaining which sets contain the cards
            has_store_results = len(store_results['results']) > 0
            response_text = _get_set_response(query, retrieved_cards, context, has_store_results)
        elif store_results['results']:
            # Short response when we have store results (non-specific queries)
            response_text = f"I found these cards available for purchase, young trainer!"
        else:
            # Full response when no store results
            response_text = _get_card_response(query, retrieved_cards, context, specific_pokemon_found)
        
        # No need to combine responses since store_results['response'] is now empty
        full_response = response_text
        
        return {
            'response': full_response,
            'results': store_results['results'],
            'num_results': len(retrieved_cards),
            'query_type': query_type
        }
        
    except Exception as e:
        return {
            'response': f"I'm having trouble accessing my knowledge right now, young trainer. Error: {str(e)}",
            'results': [],
            'num_results': 0,
            'query_type': 'error'
        }


def _get_rare_cards(query: str) -> List[Dict]:
    """Get rare cards using rarity filtering"""
    top_rare_categories = [
        'Crown', 'LEGEND', 'Mega Hyper Rare', 'Amazing Rare',
        'Shiny Ultra Rare', 'Radiant Rare', 'ACE SPEC Rare',
        'Hyper rare', 'Special illustration rare', 'Shiny rare VMAX',
        'Shiny rare V', 'Full Art Trainer', 'Black White Rare',
        'Holo Rare VSTAR', 'Holo Rare VMAX', 'Holo Rare V',
        'Shiny rare', 'Illustration rare', 'Double rare',
        'Secret Rare', 'Ultra Rare', 'Rare PRIME', 'Rare Holo LV.X',
        'Holo Rare', 'Rare Holo', 'Four Diamond', 'Three Diamond',
        'Three Star', 'Two Diamond', 'Two Star', 'Two Shiny',
        'One Diamond', 'One Star', 'One Shiny', 'Classic Collection'
    ]
    
    retrieved_cards = []
    for rarity_category in top_rare_categories:
        if len(retrieved_cards) >= 20:
            break
            
        try:
            results = collection.query(
                query_texts=[query],
                n_results=50,
                where={"rarity": rarity_category}
            )
            
            if results['metadatas'] and len(results['metadatas'][0]) > 0:
                for metadata in results['metadatas'][0]:
                    if len(retrieved_cards) >= 20:
                        break
                    card_info = {
                        'name': metadata.get('name', 'Unknown'),
                        'card_id': metadata.get('card_id', 'Unknown'),
                        'hp': metadata.get('hp', 'Unknown'),
                        'types': metadata.get('types', 'Unknown'),
                        'rarity': metadata.get('rarity', 'Unknown'),
                        'set_name': metadata.get('set_name', 'Unknown'),
                        'set_id': metadata.get('set_id', 'Unknown'),
                        'series_name': metadata.get('series_name', 'Unknown'),
                        'artist': metadata.get('artist', 'Unknown')
                    }
                    retrieved_cards.append(card_info)
        except Exception:
            continue
    
    # Remove duplicates by name
    seen_names = set()
    unique_cards = []
    for card in retrieved_cards:
        if card['name'] not in seen_names:
            unique_cards.append(card)
            seen_names.add(card['name'])
            if len(unique_cards) >= 15:
                break
    
    return unique_cards


def _get_regular_cards(query: str) -> List[Dict]:
    """Get regular cards using standard search"""
    results = collection.query(
        query_texts=[query],
        n_results=20
    )
    
    retrieved_cards = []
    if results['metadatas'] and len(results['metadatas'][0]) > 0:
        for metadata in results['metadatas'][0]:
            card_info = {
                'name': metadata.get('name', 'Unknown'),
                'card_id': metadata.get('card_id', 'Unknown'),
                'hp': metadata.get('hp', 'Unknown'),
                'types': metadata.get('types', 'Unknown'),
                'rarity': metadata.get('rarity', 'Unknown'),
                'set_name': metadata.get('set_name', 'Unknown'),
                'set_id': metadata.get('set_id', 'Unknown'),
                'series_name': metadata.get('series_name', 'Unknown'),
                'artist': metadata.get('artist', 'Unknown')
            }
            retrieved_cards.append(card_info)
    
    return retrieved_cards


def _build_card_context(retrieved_cards: List[Dict]) -> str:
    """Build context string from retrieved cards"""
    context = f"Here are {len(retrieved_cards)} Pokémon cards that match your query:\n\n"
    
    for i, card in enumerate(retrieved_cards, 1):
        context += f"Card #{i}:\n"
        context += f"  Name: {card['name']}\n"
        context += f"  Card ID: {card['card_id']}\n"
        context += f"  HP: {card['hp']}\n"
        context += f"  Types: {card['types']}\n"
        context += f"  Rarity: {card['rarity']}\n"
        context += f"  Set: {card['set_name']} ({card['set_id']})\n"
        context += f"  Series: {card['series_name']}\n"
        context += f"  Artist: {card['artist']}\n"
        context += f"  ---\n\n"
    
    return context


def _get_set_response(query: str, retrieved_cards: List[Dict], context: str, has_store_results: bool = False) -> str:
    """Get AI response for set queries"""
    # Build sets context
    sets_info = {}
    for card in retrieved_cards:
        set_name = card.get('set_name', 'Unknown')
        if set_name not in sets_info:
            sets_info[set_name] = {
                'series': card.get('series_name', 'Unknown'),
                'card_count': 0,
                'notable_cards': []
            }
        sets_info[set_name]['card_count'] += 1
        if len(sets_info[set_name]['notable_cards']) < 3:
            sets_info[set_name]['notable_cards'].append(card['name'])
    
    sets_context = f"Here are the sets that match your query:\n\n"
    for set_name, info in sets_info.items():
        sets_context += f"SET: {set_name}\n"
        sets_context += f"  Series: {info['series']}\n"
        sets_context += f"  Cards found: {info['card_count']}\n"
        sets_context += f"  Notable cards: {', '.join(info['notable_cards'])}\n"
        sets_context += f"  ---\n\n"
    
    prompt = f"""You are Professor Oak helping a trainer find booster packs to get specific cards.

CRITICAL FORMATTING RULES:
1. NEVER use ** or any markdown formatting (bold, italic, etc.)
2. ALWAYS use bullet points (•) when listing multiple sets
3. Put each bullet point on its own separate line with a blank line between them
4. Keep each set description to 2-3 short sentences maximum
5. Use simple, clean text formatting only

CONTENT RULES:
1. Focus on which BOOSTER PACKS and PRODUCTS the trainer can buy to get these cards
2. Recommend the TOP 3 most relevant sets from the list below
3. Explain what cards they can find in each set's booster packs
4. Mention that booster packs from these sets will give them a chance to get the cards they want
{f"5. IMPORTANT: Add at the end that no booster packs from these sets are currently available for purchase online." if not has_store_results else "5. Note that booster packs from these sets may be available for purchase (check the products shown below)."}

SET INFORMATION:
{sets_context}

User Question: {query}

Format your response like this example:
Here are the sets where you can find these cards in booster packs:

• Set Name (Series) - You can find [notable cards] in booster packs from this set. Great for collectors looking for [type of cards].

• Set Name (Series) - Booster packs from this set contain [notable cards]. This set is known for [special feature].

• Set Name (Series) - Look for booster packs from this expansion to get [notable cards]. Perfect for [collecting goal].

IMPORTANT: Put each bullet point on a separate line with an empty line between each one. Use actual line breaks (newlines) in your response."""

    try:
        response = chat_client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are Professor Oak, a Pokémon expert helping trainers find booster packs. Focus on which booster packs and products contain the cards they want. Never use markdown formatting. Always use bullet points for multiple items with blank lines between each bullet point. Be friendly and educational. Limit to exactly 3 sets maximum."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"I'm having trouble organizing my thoughts about these sets right now, young trainer. Error: {str(e)}"


def _get_card_response(query: str, retrieved_cards: List[Dict], context: str, specific_pokemon_found: str = None) -> str:
    """Get AI response for individual card queries"""
    
    prompt = f"""You are Professor Oak, the renowned Pokémon researcher. You're speaking to a new trainer.

CRITICAL FORMATTING RULES:
1. NEVER use ** or any markdown formatting (bold, italic, etc.)
2. ALWAYS use bullet points (•) when listing multiple cards
3. Put each bullet point on its own separate line with a blank line between them
4. Keep each card description to 1-2 short sentences maximum
5. Use simple, clean text formatting only

CONTENT RULES:
1. There are {len(retrieved_cards)} cards in the list below - recommend the TOP 5 most relevant ones only
2. ONLY discuss cards from the list below - never mention cards not in the list
3. NEVER change card details (name, HP, types, rarity, set, etc.)
4. Focus on the most interesting/powerful/rare cards only
5. Do NOT mention store availability in this response

{f"IMPORTANT: The user asked specifically about {specific_pokemon_found} cards. Focus on {specific_pokemon_found} cards from the list." if specific_pokemon_found else ""}

CARD INFORMATION:
{context}

User Question: {query}

Format your response like this example:
Here are the most notable cards I found for you:

• Card Name (Rarity) - Brief description of why it's noteworthy. From Set Name.

• Card Name (Rarity) - Brief description of why it's noteworthy. From Set Name.

• Card Name (Rarity) - Brief description of why it's noteworthy. From Set Name.

• Card Name (Rarity) - Brief description of why it's noteworthy. From Set Name.

• Card Name (Rarity) - Brief description of why it's noteworthy. From Set Name.

IMPORTANT: Put each bullet point on a separate line with an empty line between each one. Use actual line breaks (newlines) in your response."""

    try:
        response = chat_client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "You are Professor Oak, a Pokémon expert. Only discuss cards from the provided list. Never use markdown formatting. Always use bullet points for multiple items with blank lines between each bullet point. Be friendly and educational. Limit to exactly 5 cards maximum."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"I'm having trouble organizing my thoughts about these cards right now, young trainer. Error: {str(e)}"


def _get_store_availability(query: str, retrieved_cards: List[Dict], is_set_query: bool, potential_pokemon_names: List[str] = None) -> Dict[str, Any]:
    """Get store availability information"""
    if not store_searcher.available:
        return {'response': '', 'results': []}
    
    # Ensure potential_pokemon_names is not None
    if potential_pokemon_names is None:
        potential_pokemon_names = []
    
    # For set queries, ONLY look for booster packs from the specific sets
    if is_set_query:
        set_names = list(set(card.get('set_name', '') for card in retrieved_cards if card.get('set_name')))
        set_products = store_searcher.search_for_set_products(set_names, top_n=10, query=query)
        
        if not set_products.empty:
            results = []
            for _, product in set_products.head(5).iterrows():
                results.append({
                    'title': product['title'],
                    'price': product['price'],
                    'source': product['source'],
                    'url': product['url']
                })
            return {'response': '', 'results': results}
        
        # For set queries, return empty if no booster packs found - NO FALLBACK
        return {'response': '', 'results': []}
    # For non-set queries, do the original logic
    # Check if this is a rarity query
    rarity_keywords = [
        'rare', 'rarest', 'valuable', 'expensive', 'ultra rare', 'secret rare',
        'full art', 'illustration rare', 'special illustration', 'alternate art',
        'rainbow rare', 'gold card', 'shiny', 'holo rare', 'reverse holo',
        'promo', 'first edition', '1st edition', 'shadowless', 'base set',
        'vmax', 'vstar', 'v card', 'ex card', 'gx card', 'prime', 'legend'
    ]
    is_rarity_query = any(keyword in query.lower() for keyword in rarity_keywords)
    
    # Look for individual cards and sets containing them
    available_cards = store_searcher.get_available_cards_from_chromadb(retrieved_cards)
    sets_with_products = store_searcher.find_sets_containing_cards(retrieved_cards, query)
    
    all_results = []
    
    if available_cards:
        for card in available_cards[:3]:  # Show top 3
            best_option = min(card['store_options'], key=lambda x: x['price'])
            all_results.append(best_option)
    
    if sets_with_products:
        for set_name, set_data in list(sets_with_products.items())[:2]:  # Show top 2 sets
            best_product = min(set_data['products'], key=lambda x: x['price'])
            all_results.append(best_product)
    
    # If this is a rarity query or specific Pokemon query, search for relevant cards in store
    if is_rarity_query:
        if potential_pokemon_names:
            # Combined Pokemon + rarity query (e.g., "rare umbreon cards")
            for pokemon_name in potential_pokemon_names:
                pokemon_store_cards = _search_rare_cards_in_store(pokemon_name)
                if pokemon_store_cards:
                    all_results.extend(pokemon_store_cards[:3])  # Add top 3 Pokemon cards from store
                    break  # Only search for the first Pokemon found
        else:
            # Pure rarity query
            rare_store_cards = _search_rare_cards_in_store()
            all_results.extend(rare_store_cards[:3])  # Add top 3 rare cards from store
    else:
        # Check if this is a specific Pokemon query
        query_words = query.lower().split()
        common_words = {'show', 'me', 'tell', 'about', 'find', 'get', 'cards', 'card', 'pokemon', 'pokémon', 
                       'the', 'a', 'an', 'and', 'or', 'but', 'for', 'with', 'from', 'what', 'are', 'is',
                       'rare', 'best', 'good', 'powerful', 'strong', 'cool', 'awesome', 'legendary'}
        
        potential_pokemon_names_local = [word for word in query_words if word not in common_words and len(word) > 2]
        
        # If we found a potential Pokemon name, search for it in the store
        if potential_pokemon_names_local:
            for pokemon_name in potential_pokemon_names_local:
                pokemon_store_cards = _search_rare_cards_in_store(pokemon_name)
                if pokemon_store_cards:
                    all_results.extend(pokemon_store_cards[:3])  # Add top 3 Pokemon cards from store
                    break  # Only search for the first Pokemon found
    
    if all_results:
        return {'response': '', 'results': all_results}
    
    return {'response': '', 'results': []}


def _search_rare_cards_in_store(pokemon_name: str = None) -> List[Dict]:
    """Search for rare cards in the store database, optionally filtered by Pokemon name"""
    if not store_searcher.available:
        return []
    
    df = store_searcher.df.copy()
    
    # If searching for a specific Pokemon, add it to the search terms
    if pokemon_name:
        # Search for the specific Pokemon first
        pokemon_mask = df['title'].str.lower().str.contains(pokemon_name.lower(), case=False, na=False, regex=False)
        pokemon_cards = df[pokemon_mask].copy()
        
        # Exclude packs and accessories for Pokemon-specific searches
        exclusion_terms = [
            'booster pack', 'booster box', 'elite trainer box', 'collection box',
            'bundle', 'tin', 'deck', 'sleeves', 'playmat', 'dice', 'coin',
            'empty', 'code card', 'online', 'divider'
        ]
        
        exclusion_mask = pd.Series([False] * len(pokemon_cards), index=pokemon_cards.index)
        for term in exclusion_terms:
            exclusion_mask |= pokemon_cards['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
        
        pokemon_cards = pokemon_cards[~exclusion_mask]
        
        # Convert price and sort by price (highest first for rare cards)
        pokemon_cards['price'] = pd.to_numeric(pokemon_cards['price'], errors='coerce')
        pokemon_cards = pokemon_cards.dropna(subset=['price'])
        pokemon_cards = pokemon_cards.sort_values('price', ascending=False).head(10)
        
        results = []
        for _, card in pokemon_cards.iterrows():
            results.append({
                'title': card['title'],
                'price': card['price'],
                'source': card['source'],
                'url': card['url']
            })
        
        return results
    
    # Original rare card search logic for non-Pokemon specific queries
    rare_keywords = [
        'secret rare', 'ultra rare', 'full art', 'rainbow rare', 'gold card',
        'shiny', 'holo rare', 'special illustration', 'alternate art', 'promo',
        'first edition', '1st edition', 'shadowless', 'base set'
    ]
    
    # Exclusion terms (packs, boxes, accessories)
    exclusion_terms = [
        'booster pack', 'booster box', 'elite trainer box', 'collection box',
        'bundle', 'tin', 'deck', 'sleeves', 'playmat', 'dice', 'coin',
        'empty', 'code card', 'online', 'divider'
    ]
    
    # Search for rare cards
    rare_mask = pd.Series([False] * len(df))
    for keyword in rare_keywords:
        rare_mask |= df['title'].str.lower().str.contains(keyword.lower(), case=False, na=False, regex=False)
    
    # Exclude non-card items
    exclusion_mask = pd.Series([False] * len(df))
    for term in exclusion_terms:
        exclusion_mask |= df['title'].str.lower().str.contains(term.lower(), case=False, na=False, regex=False)
    
    final_mask = rare_mask & ~exclusion_mask
    rare_cards = df[final_mask].copy()
    
    # Convert price to numeric and filter
    rare_cards['price'] = pd.to_numeric(rare_cards['price'], errors='coerce')
    rare_cards = rare_cards.dropna(subset=['price'])
    
    # Sort by price (most expensive first for rare cards)
    rare_cards = rare_cards.sort_values('price', ascending=False).head(10)
    
    results = []
    for _, card in rare_cards.iterrows():
        results.append({
            'title': card['title'],
            'price': card['price'],
            'source': card['source'],
            'url': card['url']
        })
    
    return results


# Keep the old main section for backwards compatibility but make it optional
if __name__ == "__main__":
    # Test query - only runs when script is executed directly
    test_query = "What are the cheapest packs?"
    result = professor_oak_query(test_query)
    
    print("=" * 80)
    print("PROFESSOR OAK'S RESPONSE:")
    print("=" * 80)
    print(result['response'])
    print("\n" + "=" * 80)
    print(f"Query Type: {result['query_type']}")
    print(f"Results Found: {result['num_results']}")
    if result['results']:
        print(f"Store Results: {len(result['results'])}")
    print("=" * 80)
