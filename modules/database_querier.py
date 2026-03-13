"""
Pokemon Card Database Querier with OpenAI LLM
"""
import pandas as pd
import json
from typing import List, Dict, Any
import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class OpenAIClient:
    """OpenAI LLM client wrapper"""
    
    def __init__(self, api_key: str = None, model: str = "gpt-3.5-turbo"):
        """
        Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key (uses OPENAI_API_KEY or OPENROUTER_API_KEY env variable if not provided)
            model: Model to use (default: gpt-3.5-turbo)
        """
        # Try OPENAI_API_KEY first, then OPENROUTER_API_KEY
        api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        
        if not api_key:
            raise ValueError("No API key found. Set OPENAI_API_KEY or OPENROUTER_API_KEY in .env file")
        
        # If using OpenRouter, set the base URL
        if os.getenv("OPENROUTER_API_KEY"):
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1"
            )
        else:
            self.client = OpenAI(api_key=api_key)
        
        self.model = model
    
    def generate(self, prompt: str) -> str:
        """Generate response from OpenAI"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content


class PokemonCardSearch:
    """Pokemon card search system with LLM-powered query parsing"""
    
    def __init__(self, csv_path: str, llm_client: OpenAIClient):
        """
        Initialize the Pokemon card search system.
        
        Args:
            csv_path: Path to the Pokemon cards CSV database
            llm_client: OpenAI client instance
        """
        self.df = pd.read_csv(csv_path)
        # Convert price column to numeric, handling any non-numeric values
        self.df['price'] = pd.to_numeric(self.df['price'], errors='coerce')
        self.llm_client = llm_client
    
    def extract_keywords(self, user_query: str) -> Dict[str, Any]:
        """
        Use LLM to extract search keywords from user query.
        
        Args:
            user_query: Natural language query from user
            
        Returns:
            Dictionary with extracted keywords and search criteria
        """
        prompt = f"""Extract search keywords from this Pokemon card query. Return a JSON object with:
- "keywords": list of the MOST IMPORTANT search terms only (prioritize Pokemon names, specific card types). Avoid generic words like "card", "cheapest", "find".
- "price_range": object with "min" and "max" if price mentioned, else null
- "sort_by_price": true if user wants cheapest/lowest price items, false otherwise
- "intent": brief description of what user is looking for

Examples:
- "cheapest Pikachu card" → keywords: ["pikachu"]
- "Elite Trainer Box under £50" → keywords: ["elite trainer box"]
- "Scarlet Violet booster packs" → keywords: ["scarlet", "violet", "booster"]

User query: "{user_query}"

Return only valid JSON, no other text."""

        response = self.llm_client.generate(prompt)
        
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback to simple keyword extraction
            return {
                "keywords": user_query.lower().split(),
                "price_range": None,
                "sort_by_price": False,
                "intent": user_query
            }
    
    def search_database(self, keywords: Dict[str, Any], top_n: int = 5) -> pd.DataFrame:
        """
        Search the database using extracted keywords.
        
        Args:
            keywords: Dictionary with search criteria from extract_keywords
            top_n: Number of top results to return
            
        Returns:
            DataFrame with matching cards
        """
        df = self.df.copy()
        
        # Search in title field - require ALL keywords to match (AND logic)
        search_terms = keywords.get("keywords", [])
        if search_terms:
            # Create a mask that requires ALL keywords to be present
            mask = pd.Series([True] * len(df))
            for term in search_terms:
                term_mask = df['title'].str.lower().str.contains(term.lower(), case=False, na=False)
                mask = mask & term_mask
            df = df[mask]
        
        # Filter by price range if specified
        price_range = keywords.get("price_range")
        if price_range:
            if price_range.get("min") is not None:
                df = df[df['price'] >= price_range["min"]]
            if price_range.get("max") is not None:
                df = df[df['price'] <= price_range["max"]]
        
        # Sort by price if requested (cheapest first)
        if keywords.get("sort_by_price", False):
            df = df.sort_values('price', ascending=True)
        
        return df.head(top_n)
    
    def generate_response(self, user_query: str, results: pd.DataFrame) -> str:
        """
        Use LLM to generate a natural language response with the search results.
        
        Args:
            user_query: Original user query
            results: DataFrame with search results
            
        Returns:
            Natural language response string
        """
        if results.empty:
            prompt = f"""The user asked: "{user_query}"

No Pokemon cards matching this search were found in our database. 

Provide a helpful response that:
1. Clearly states no results were found
2. Suggests they try different or more general search terms
3. Gives examples of what they could search for instead (like "Pikachu", "booster packs", "Elite Trainer Box", etc.)

Be friendly and encouraging."""
        else:
            results_text = "\n".join([
                f"- {row['title']}: £{row['price']} ({row['source']}) - {row['url']}"
                for _, row in results.iterrows()
            ])
            
            prompt = f"""The user asked: "{user_query}"

Here are the matching Pokemon cards from our database:

{results_text}

Provide a helpful, friendly response presenting these options to the user. Include prices and mention they can click the links for more details."""
        
        return self.llm_client.generate(prompt)
    
    def query(self, user_query: str, top_n: int = 5, collection: dict = None) -> Dict[str, Any]:
            """
            Updated query function to handle user collection data.
            """
            # Step 1: Extract keywords using LLM
            keywords = self.extract_keywords(user_query)
            
            # Step 2: Search database
            results = self.search_database(keywords, top_n)
            
            # Step 3: Generate a personalized response
            # We'll calculate how many cards they own to give the LLM some context
            owned_count = sum(1 for v in collection.values() if v) if collection else 0
            
            # We customize the prompt for the response generator
            if results.empty:
                response = self.generate_response(user_query, results)
            else:
                # Tell the LLM about the user's vault!
                prompt = f"""
                The user asked: "{user_query}"
                The user currently has {owned_count} cards in their collection vault.
                We found {len(results)} matching items in the shop.

                Write a SHORT, bubbly, and helpful response (1-2 sentences). 
                If they have a lot of cards, congratulate them! 
                If they are looking for something new, encourage them to add to their vault.
                Do not list the results, just a friendly intro.
                """
                response = self.llm_client.generate(prompt)
            
            return {
                "response": response,
                "results": results.to_dict('records') if not results.empty else [],
                "keywords_extracted": keywords,
                "num_results": len(results)
            }


def main():
    """Example usage"""
    # Initialize OpenAI client
    llm = OpenAIClient()
    
    # Initialize search system
    searcher = PokemonCardSearch("data/pokemon_cards_database.csv", llm)
    
    # Example queries
    queries = [
        "I want Pikachu cards under £50",
        "Show me booster packs",
        "What Elite Trainer Boxes do you have?",
        "Looking for Scarlet & Violet cards"
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        result = searcher.query(query, top_n=3)
        print(result["response"])
        print(f"\nFound {result['num_results']} results")


if __name__ == "__main__":
    main()
