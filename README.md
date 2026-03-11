# Professor Oak's Pokémon TCG Assistant

A comprehensive Pokémon Trading Card Game (TCG) assistant powered by AI that helps users find cards, check prices, and discover booster packs. Built with Flask, ChromaDB for vector search, and OpenAI's API.

## Features

- **AI-Powered Card Search**: Ask natural language questions about Pokémon cards
- **Comprehensive Database**: Access to 22,754+ Pokémon cards from TCGdx API
- **Smart Query Processing**: Handles specific Pokémon searches, rarity queries, and set information
- **Store Integration**: Find where to buy cards with real pricing data
- **Vector Search**: ChromaDB-powered semantic search for accurate results
- **Web Interface**: Clean, responsive chat interface with Professor Oak theme

## Project Structure

```
Pokemon/                       # Main application directory
├── website/                   # Flask web application
│   ├── app.py                # Main Flask application
│   ├── prof_oak_ai.py        # AI assistant logic and card search
│   ├── templates/            # HTML templates
│   │   ├── base.html        # Base template
│   │   ├── chat.html        # Chat interface
│   │   ├── home.html        # Home page
│   │   ├── price.html       # Price search page
│   │   └── search.html      # Card search page
│   ├── static/              # Static assets
│   │   └── prof_oak.png     # Professor Oak avatar
│   └── pokemon_cards_database.csv  # Store pricing data
├── chroma_db/                # ChromaDB vector database
├── all_cards.json           # Complete TCG card database (22,754+ cards)
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (API keys)
└── README.md               # This file
```

## Setup Instructions

### Prerequisites

- Python 3.8+
- OpenAI API key (or compatible API endpoint)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Pokemon
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   Create a `.env` file in the Pokemon directory:
   ```env
   API_KEY=your_openai_api_key_here
   ENDPOINT=https://api.openai.com/v1
   ```

4. **Verify data files**
   Ensure these files exist:
   - `all_cards.json` (22,754+ Pokémon cards)
   - `chroma_db/` directory (vector embeddings)
   - `website/pokemon_cards_database.csv` (store pricing data)

5. **Run the application**
   ```bash
   cd website
   python app.py
   ```

6. **Access the application**
   Open your browser and go to `http://localhost:5000`

## Usage

### Chat Interface

Navigate to the chat page and ask Professor Oak questions like:

- **Specific Pokémon**: "Show me Pikachu cards"
- **Rare Cards**: "Find rare Charizard cards"
- **Sets**: "What are the best booster packs?"
- **Pricing**: "Cheapest Pokémon booster packs"

### Query Types

The system handles several types of queries:

1. **Pokémon-Specific**: Searches for cards of a specific Pokémon
2. **Rarity-Based**: Finds rare, ultra rare, or secret rare cards
3. **Set Queries**: Information about card sets and booster packs
4. **Product Searches**: Store availability and pricing

### Response Format

Responses include:
- **Card Information**: Name, rarity, set, and description
- **Store Links**: Where to buy with current pricing
- **Formatted Lists**: Clean bullet points with proper spacing

## Technical Details

### AI Assistant (`prof_oak_ai.py`)

- **Smart Query Detection**: Identifies Pokémon names, rarity keywords, and query types
- **Dual Search System**: Direct JSON search for specific Pokémon + ChromaDB for semantic search
- **Store Integration**: Matches cards with available products and pricing
- **Response Formatting**: Ensures proper line breaks and bullet points

### Database Systems

- **JSON Database**: Complete card data from TCGdx (22,754+ cards)
- **ChromaDB**: Vector embeddings for semantic search
- **CSV Store Data**: Real pricing and availability information

### Web Application (`app.py`)

- **Flask Framework**: Lightweight web server
- **API Endpoints**: RESTful endpoints for chat and search
- **Template System**: Jinja2 templates with responsive design
- **Static Assets**: Images and styling

## API Endpoints

- `GET /` - Home page
- `GET /chat` - Chat interface
- `GET /search` - Card search page
- `GET /price` - Price search page
- `POST /api/chat` - Chat API endpoint
- `GET /api/sets` - Available card sets
- `GET /api/cards` - Card search API

## Configuration

### Environment Variables

- `API_KEY`: OpenAI API key or compatible service
- `ENDPOINT`: API endpoint URL (default: OpenAI)

### Customization

- **Model Selection**: Change AI model in `prof_oak_ai.py`
- **Response Limits**: Adjust card count limits in prompts
- **Store Data**: Update `pokemon_cards_database.csv` for pricing
- **Styling**: Modify templates and CSS for appearance

## Troubleshooting

### Common Issues

1. **"No cards found"**: Check if `all_cards.json` exists and is properly formatted
2. **API Errors**: Verify API key and endpoint in `.env` file
3. **ChromaDB Issues**: Regenerate embeddings with `data_embedding.py`
4. **Import Errors**: Ensure all dependencies are installed

### Debug Mode

Enable Flask debug mode by setting:
```python
app.run(debug=True)
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is for educational and personal use. Pokémon and TCG data are property of their respective owners.

## Acknowledgments

- **TCGdx**: Card data API
- **OpenAI**: AI language model
- **ChromaDB**: Vector database
- **Flask**: Web framework
- **The Pokémon Company**: Original card designs and data