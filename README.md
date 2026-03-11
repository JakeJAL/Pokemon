# Professor Oak's Pokémon TCG Assistant

A comprehensive Pokémon Trading Card Game (TCG) assistant powered by AI that helps users find cards, check prices, and discover booster packs. Built with Flask, ChromaDB for vector search, and OpenAI's API.

## Features

- **AI-Powered Card Search**: Ask natural language questions about Pokémon cards
- **Comprehensive Database**: Access to 22,754+ Pokémon cards from TCGdx API
- **Smart Query Processing**: Handles specific Pokémon searches, rarity queries, and set information
- **Store Integration**: Find where to buy cards with real pricing data
- **Price Sorting**: Sort results by price (ascending or descending) for better deal finding
- **Vector Search**: ChromaDB-powered semantic search for accurate results
- **Card Scanning**: OCR-powered card recognition using EasyOCR and OpenCV
- **Collection Management**: Track your personal card collection
- **Price Filtering**: Search for products within specific price ranges
- **Category Filtering**: Filter by singles, booster packs, boxes, or other products
- **Web Scraping**: Automated price data collection from online stores
- **Web Interface**: Clean, responsive chat interface with Professor Oak theme

## Project Structure

```
Pokemon/                       # Main application directory
├── app.py                    # Main Flask application with all routes
├── Dockerfile                # Docker configuration
├── docker-compose.yml        # Docker Compose configuration
├── .dockerignore            # Docker ignore file
├── .gitignore               # Git ignore file
├── .env                     # Environment variables (API keys)
├── requirements.txt         # Python dependencies
├── README.md               # This file
├── data/                    # Data files directory
│   ├── all_cards.json      # Complete TCG card database (22,754+ cards)
│   ├── pokemon_cards_database.csv  # Store pricing data
│   └── chroma_db/          # ChromaDB vector database
├── modules/                 # Python modules
│   ├── prof_oak_ai.py      # AI assistant logic and card search
│   ├── pokemon_search.py   # Card search system with LLM integration
│   ├── database_querier.py # Database query handler with OpenAI
│   └── website_scraper.py  # Web scraper for price data collection
├── templates/               # HTML templates
│   ├── base.html           # Base template
│   ├── chat.html           # Chat interface
│   ├── home.html           # Home page
│   ├── collection.html     # Collection management page
│   ├── price.html          # Price search page
│   ├── scan.html           # Card scanning page
│   └── search.html         # Card search page
└── static/                  # Static assets
    └── prof_oak.png        # Professor Oak avatar
```

## Setup Instructions

### Prerequisites

- Python 3.8+
- OpenAI API key (or compatible API endpoint like Google Gemini)
- Internet connection (for downloading OCR models on first run)

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
   
   Note: First-time installation may take several minutes as EasyOCR downloads language models.

3. **Set up environment variables**
   Create a `.env` file in the Pokemon directory:
   ```env
   API_KEY=your_openai_api_key_here
   ENDPOINT=https://api.openai.com/v1
   ```
   
   For Google Gemini or other providers, update the ENDPOINT accordingly.

4. **Initialize ChromaDB (if needed)**
   If you encounter ChromaDB schema errors, delete and recreate the database:
   ```bash
   # Windows PowerShell
   Remove-Item -Recurse -Force data/chroma_db
   
   # Linux/Mac
   rm -rf data/chroma_db
   ```
   
   The database will be automatically recreated on first run.

5. **Verify data files**
   Ensure these files exist:
   - `data/all_cards.json` (22,754+ Pokémon cards)
   - `data/pokemon_cards_database.csv` (store pricing data)

6. **Run the application**
   ```bash
   python app.py
   ```

7. **Access the application**
   Open your browser and go to `http://localhost:5000`

## Usage

### Chat Interface

Navigate to the chat page and ask Professor Oak questions like:

- **Specific Pokémon**: "Show me Pikachu cards"
- **Rare Cards**: "Find rare Charizard cards"
- **Sets**: "What are the best booster packs?"
- **Pricing**: "Cheapest Pokémon booster packs"
- **Price Ranges**: "Show me cards under £20"
- **General Info**: "What's the newest Pokémon set?"

### Price Comparison

Use the price page to:
- Search for products by name
- Filter by category (singles, booster packs, boxes, other)
- Sort by price (low to high or high to low)
- Compare prices across multiple stores
- Find the best deals on cards and products

### Card Scanning

Use the scan page to:
- Take photos of your cards using your device camera
- Automatically recognize card names using OCR technology
- Quickly add cards to your collection

### Collection Management

Track your personal card collection:
- Mark cards as owned in your vault
- View your collection statistics
- Get personalized recommendations based on your collection

### Query Types

The system handles several types of queries:

1. **Pokémon-Specific**: Searches for cards of a specific Pokémon
2. **Rarity-Based**: Finds rare, ultra rare, or secret rare cards
3. **Set Queries**: Information about card sets and booster packs
4. **Product Searches**: Store availability and pricing
5. **Price-Constrained**: Searches within specific price ranges (over/under/between)
6. **General Information**: Latest sets, release dates, and TCG information
7. **Collection-Based**: Personalized responses based on your collection

### Response Format

Responses include:
- **Card Information**: Name, rarity, set, and description
- **Store Links**: Where to buy with current pricing
- **Formatted Lists**: Clean bullet points with proper spacing

## Technical Details

### AI Assistant (`modules/prof_oak_ai.py`)

- **Smart Query Detection**: Identifies Pokémon names, rarity keywords, and query types
- **Dual Search System**: Direct JSON search for specific Pokémon + ChromaDB for semantic search
- **Store Integration**: Matches cards with available products and pricing
- **Response Formatting**: Ensures proper line breaks and bullet points
- **Price Parsing**: Extracts and handles price constraints from natural language
- **Set Information**: Provides detailed information about TCG sets and releases

### Card Recognition (`app.py` with EasyOCR)

- **OCR Technology**: Uses EasyOCR for text recognition from card images
- **Image Processing**: OpenCV for image preprocessing and enhancement
- **Fuzzy Matching**: Finds closest card matches from detected text
- **Real-time Scanning**: Camera integration for instant card recognition

### Database Systems

- **JSON Database**: Complete card data from TCGdx (22,754+ cards)
- **ChromaDB**: Vector embeddings for semantic search
- **CSV Store Data**: Real pricing and availability information
- **Pandas Integration**: Efficient data filtering and sorting

### Web Scraping (`modules/website_scraper.py`)

- **Automated Collection**: Scrapes pricing data from online stores
- **Prefect Workflows**: Orchestrated data collection tasks
- **BeautifulSoup**: HTML parsing for product information
- **Data Validation**: Ensures pricing data accuracy

### Web Application (`app.py`)

- **Flask Framework**: Lightweight web server
- **API Endpoints**: RESTful endpoints for chat, search, and scanning
- **Template System**: Jinja2 templates with responsive design
- **Static Assets**: Images and styling
- **Async Support**: Handles TCGdx API calls efficiently

## API Endpoints

- `GET /` - Home page
- `GET /chat` - Chat interface
- `GET /search` - Card search page
- `GET /price?query=<search>&category=<filter>&sort=<order>` - Price search page with category filtering and sorting
  - Parameters:
    - `query`: Search term (optional)
    - `category`: all, single, booster, box, other (default: all)
    - `sort`: asc (low to high) or desc (high to low) (default: asc)
- `GET /scan` - Card scanning page
- `GET /collection` - Collection management page
- `POST /api/chat` - Chat API endpoint (accepts collection data)
- `POST /api/scan` - Card scanning API endpoint
- `GET /api/sets` - Available card sets
- `POST /api/cards` - Card search API with sorting and pagination

## Configuration

### Environment Variables

- `API_KEY`: OpenAI API key or compatible service
- `ENDPOINT`: API endpoint URL (default: OpenAI)

### Customization

- **Model Selection**: Change AI model in `modules/prof_oak_ai.py` (default: google/gemini-2.5-flash)
- **Response Limits**: Adjust card count limits in prompts
- **Store Data**: Update `data/pokemon_cards_database.csv` for pricing
- **Styling**: Modify templates and CSS for appearance
- **OCR Settings**: Configure EasyOCR language support and confidence thresholds
- **Price Constraints**: Modify price parsing logic in `modules/prof_oak_ai.py`

## Troubleshooting

### Common Issues

1. **"No cards found"**: Check if `data/all_cards.json` exists and is properly formatted
2. **API Errors**: Verify API key and endpoint in `.env` file
3. **ChromaDB Schema Error** (`no such column: collections.topic`): 
   - Delete the `data/chroma_db` folder and restart the app
   - The database will be recreated automatically
   - This happens when ChromaDB version changes
4. **Import Errors**: Ensure all dependencies are installed (`pip install -r requirements.txt`)
5. **OCR Not Working**: EasyOCR downloads models on first run - ensure internet connection
6. **Camera Access Denied**: Check browser permissions for camera access
7. **Slow Performance**: EasyOCR and ChromaDB may be slow on first run while loading models
8. **Price Sorting Not Working**: Ensure CSV file has valid numeric price values

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
- **OpenAI/Google Gemini**: AI language models
- **ChromaDB**: Vector database
- **Flask**: Web framework
- **EasyOCR**: Optical character recognition
- **OpenCV**: Computer vision library
- **Prefect**: Workflow orchestration
- **The Pokémon Company**: Original card designs and data