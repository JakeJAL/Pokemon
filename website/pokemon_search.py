import pandas as pd
import json
from typing import List, Dict, Any
import os


class PokemonCardSearch:
    def __init__(self, csv_path: str, llm_client):
        """
        Initialize the Pokemon card search system.
        
        Args:
            csv_path: Path to the Pokemon cards CSV database
            llm_client: LLM client instance (e.g., OpenAI, Anthropic, etc.)
        """
        self.df = pd.read_csv(csv_path)
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
- "keywords": list of important search terms (card names, sets, types, etc.)
- "price_range": object with "min" and "max" if price mentioned, else null
- "intent": brief description of what user is looking for

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
        
        # Search in title field
        search_terms = keywords.get("keywords", [])
        if search_terms:
            mask = df['title'].str.lower().str.contains('|'.join(search_terms), case=False, na=False)
            df = df[mask]
        
        # Filter by price range if specified
        price_range = keywords.get("price_range")
        if price_range:
            if price_range.get("min") is not None:
                df = df[df['price'] >= price_range["min"]]
            if price_range.get("max") is not None:
                df = df[df['price'] <= price_range["max"]]
        
        # Sort by relevance (could be enhanced with scoring)
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
            
No matching Pokemon cards were found in the database. Provide a helpful response suggesting they try different search terms."""
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

    def query(self, user_query: str, top_n: int = 5) -> Dict[str, Any]:
        """
        Main function to process user query and return results.
        
        Args:
            user_query: Natural language query from user
            top_n: Number of top results to return
            
        Returns:
            Dictionary with response, results, and metadata
        """
        # Step 1: Extract keywords using LLM
        keywords = self.extract_keywords(user_query)
        
        # Step 2: Search database
        results = self.search_database(keywords, top_n)
        
        # Step 3: Generate natural language response
        response = self.generate_response(user_query, results)
        
        return {
            "response": response,
            "results": results.to_dict('records') if not results.empty else [],
            "keywords_extracted": keywords,
            "num_results": len(results)
        }


# Example usage with different LLM providers
class SimpleLLMClient:
    """Example LLM client - replace with your actual LLM implementation"""
    
    def generate(self, prompt: str) -> str:
        """Override this with your actual LLM API call"""
        raise NotImplementedError("Replace with your LLM implementation (OpenAI, Anthropic, etc.)")


# Example with OpenAI
def example_openai():
    """Example using OpenAI API"""
    try:
        from openai import OpenAI
        
        class OpenAIClient:
            def __init__(self, api_key: str = None):
                self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
            
            def generate(self, prompt: str) -> str:
                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content
        
        llm = OpenAIClient()
        searcher = PokemonCardSearch("pokemon_cards_database.csv", llm)
        result = searcher.query("I'm looking for Pikachu cards under £50")
        print(result["response"])
        
    except ImportError:
        print("OpenAI package not installed. Run: pip install openai")


# Example with Anthropic
def example_anthropic():
    """Example using Anthropic API"""
    try:
        from anthropic import Anthropic
        
        class AnthropicClient:
            def __init__(self, api_key: str = None):
                self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
            
            def generate(self, prompt: str) -> str:
                response = self.client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
        
        llm = AnthropicClient()
        searcher = PokemonCardSearch("pokemon_cards_database.csv", llm)
        result = searcher.query("Show me Elite Trainer Boxes")
        print(result["response"])
        
    except ImportError:
        print("Anthropic package not installed. Run: pip install anthropic")


if __name__ == "__main__":
    print("Pokemon Card Search System")
    print("Replace SimpleLLMClient with your LLM implementation")
    print("\nExamples:")
    print("- example_openai()")
    print("- example_anthropic()")
