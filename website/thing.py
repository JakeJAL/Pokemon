from tcgdexsdk import TCGdex, Query
import asyncio

async def main():
    sdk = TCGdex()

    # Fetch all available sets
    print("Fetching available sets...\n")
    sets = await sdk.set.list()
    
    # Display sets with numbers for selection
    print("Available Sets:")
    print("-" * 50)
    for idx, set_item in enumerate(sets, 1):
        print(f"{idx}. {set_item.name} ({set_item.id})")
    print("-" * 50)
    
    # Get user selection for set
    while True:
        try:
            set_choice = int(input(f"\nSelect a set (1-{len(sets)}): "))
            if 1 <= set_choice <= len(sets):
                selected_set = sets[set_choice - 1]
                break
            else:
                print(f"Please enter a number between 1 and {len(sets)}")
        except ValueError:
            print("Please enter a valid number")
    
    print(f"\nSelected: {selected_set.name}")

    # Get user input for rarity level
    rarity_input = input("\nEnter rarity level (rare/uncommon/common): ").lower().strip()
    
    # Map user input to actual rarity types
    rarity_map = {
        "rare": ["Hyper Rare", "Special Illustration Rare", "Illustration Rare", "Ultra Rare"],
        "uncommon": ["Uncommon", "Double Rare", "Rare"],
        "common": ["Common"]
    }
    
    if rarity_input not in rarity_map:
        print("Invalid rarity level. Please choose: rare, uncommon, or common")
        return
    
    target_rarities = rarity_map[rarity_input]
    
    # Get all cards from selected set
    cards = await sdk.card.list(Query().equal("set.id", selected_set.id))
    
    print(f"\nTotal cards in {selected_set.name}: {len(cards)}")
    print(f"Searching for {rarity_input} cards: {target_rarities}\n")
    
    matching_cards = []
    for card_resume in cards:
        # Fetch full card details to get rarity
        full_card = await sdk.card.get(card_resume.id)
        if hasattr(full_card, 'rarity') and full_card.rarity in target_rarities:
            matching_cards.append(full_card)
    
    print(f"\nFound {len(matching_cards)} {rarity_input} cards:\n")
    for card in matching_cards:
        print(f"{card.name} - {card.rarity} ({card.localId})")

if __name__ == "__main__":
    asyncio.run(main())
