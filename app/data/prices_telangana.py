"""Researched retail prices for Telangana (Hyderabad), Oct 2026.

Liquor MRP is fixed by TGBCL and printed on the bottle; cigarette MRP is national.
Re-run `python -m scripts.seed_prices` after editing to upsert into MongoDB.

Each row: (item_id, name, category, price_inr, pack, source_key, confidence)
  - drinks: pack = bottle size in ml
  - cigarettes: pack = sticks per pack
  - confidence: "listed" (seen on the source) | "estimate" (derived, see source note)
"""

STATE = "telangana"
AS_OF = "2026-10-20"

SOURCES = {
    "livcheers": {
        "label": "LivCheers Hyderabad retail listing (updated Sep 2026)",
        "url": "https://www.livcheers.com/hyderabad",
    },
    "tg_beer_2025": {
        "label": "Telangana beer MRP revision (Feb 2025)",
        "url": "https://www.ambrosiaindia.com/2025/02/telangana-hikes-beer-prices/",
    },
    "tsbcl_2025": {
        "label": "TSBCL price list 2025-26",
        "url": "https://www.indiansforum.in/t/where-to-check-ts-new-whisky-rum-beer-rate-list-2025/1367",
    },
    "sula_hyd": {
        "label": "Sula wine prices in Hyderabad 2026 (midpoint of listed range)",
        "url": "https://mostnext.com/sula-wine-price-in-hyderabad/",
    },
    "instamart_hyd": {
        "label": "Swiggy Instamart Hyderabad (Apr–May 2026)",
        "url": "https://www.swiggy.com/instamart/city/hyderabad/sc/paan-corner/cigarettes-682462130c0f930001b218a2",
    },
    "eden_itc": {
        "label": "Eden The Store — ITC pack prices (2026)",
        "url": "https://edenthestore.in/products?brand=itc",
    },
    "excise_feb_2026": {
        "label": "Post-Feb 2026 excise pack prices (Hindustan Times / PTI)",
        "url": "https://www.hindustantimes.com/india-news/cigarette-prices-surge-as-high-as-55-per-pack-after-excise-duty-hike-budget-2026-40-percent-gst-101770002759832.html",
    },
    "estimate_feb_2026": {
        "label": "Estimate: pre-2026 pack price + ~₹2.1/stick Feb 2026 excise",
        "url": "https://www.hindustantimes.com/india-news/cigarette-prices-surge-as-high-as-55-per-pack-after-excise-duty-hike-budget-2026-40-percent-gst-101770002759832.html",
    },
    "estimate_local": {
        "label": "Estimate: typical local shop bundle price",
        "url": None,
    },
}

DRINKS = [
    # Whisky — 750 ml unless noted
    ("bagpiper", "Bagpiper Classic", "whisky", 640, 750, "livcheers", "listed"),
    ("mcdowells-no1", "McDowell's No.1", "whisky", 680, 750, "livcheers", "listed"),
    ("officers-choice", "Officer's Choice Blue", "whisky", 720, 750, "livcheers", "listed"),
    ("imperial-blue", "Imperial Blue", "whisky", 760, 750, "livcheers", "listed"),
    ("mcdowells-platinum", "McDowell's No.1 Platinum", "whisky", 840, 750, "livcheers", "listed"),
    ("royal-stag", "Royal Stag", "whisky", 880, 750, "livcheers", "listed"),
    ("royal-stag-barrel", "Royal Stag Barrel Select", "whisky", 1120, 750, "livcheers", "listed"),
    ("signature", "Signature Rare", "whisky", 1140, 750, "livcheers", "listed"),
    ("signature-premier", "Signature Premier", "whisky", 1300, 750, "livcheers", "listed"),
    ("sterling-b10", "Sterling Reserve B10", "whisky", 1400, 750, "livcheers", "listed"),
    ("antiquity-blue", "Antiquity Blue", "whisky", 1450, 750, "livcheers", "listed"),
    ("blenders-pride", "Blenders Pride", "whisky", 1790, 750, "livcheers", "listed"),
    ("vat-69", "VAT 69", "whisky", 2000, 750, "livcheers", "listed"),
    ("black-and-white", "Black & White", "whisky", 2080, 750, "livcheers", "listed"),
    ("100-pipers", "100 Pipers Deluxe", "whisky", 2120, 750, "livcheers", "listed"),
    ("teachers", "Teacher's Highland Cream", "whisky", 2320, 750, "livcheers", "listed"),
    ("dewars", "Dewar's White Label", "whisky", 2320, 750, "livcheers", "listed"),
    ("jw-red", "Johnnie Walker Red Label", "whisky", 2610, 750, "livcheers", "listed"),
    ("ballantines", "Ballantine's Finest", "whisky", 2720, 750, "livcheers", "listed"),
    ("jameson", "Jameson", "whisky", 2760, 750, "livcheers", "listed"),
    ("jack-daniels", "Jack Daniel's", "whisky", 3570, 750, "livcheers", "listed"),
    ("glenlivet-12", "The Glenlivet 12", "whisky", 3960, 750, "livcheers", "listed"),
    ("amrut-fusion", "Amrut Fusion", "whisky", 4400, 750, "livcheers", "listed"),
    ("chivas-12", "Chivas Regal 12", "whisky", 4590, 750, "livcheers", "listed"),
    ("indri", "Indri Trini", "whisky", 4760, 750, "livcheers", "listed"),
    ("jw-black", "Johnnie Walker Black Label", "whisky", 4770, 750, "livcheers", "listed"),
    ("glenfiddich-12", "Glenfiddich 12", "whisky", 7030, 700, "livcheers", "listed"),
    # Beer — 650 ml bottle unless noted
    ("kingfisher", "Kingfisher Premium", "beer", 180, 650, "tg_beer_2025", "listed"),
    ("royal-challenge-beer", "Royal Challenge Lager", "beer", 180, 650, "livcheers", "listed"),
    ("tuborg", "Tuborg Gold", "beer", 180, 650, "livcheers", "listed"),
    ("kingfisher-strong", "Kingfisher Strong", "beer", 190, 650, "tg_beer_2025", "listed"),
    ("haywards-5000", "Haywards 5000", "beer", 190, 650, "livcheers", "listed"),
    ("knockout", "Knock Out", "beer", 190, 650, "livcheers", "listed"),
    ("becks-ice", "Beck's Ice", "beer", 210, 650, "livcheers", "listed"),
    ("carlsberg", "Carlsberg Elephant", "beer", 220, 650, "livcheers", "listed"),
    ("amstel", "Amstel Light", "beer", 220, 650, "livcheers", "listed"),
    ("budweiser", "Budweiser", "beer", 250, 650, "livcheers", "listed"),
    ("kingfisher-ultra", "Kingfisher Ultra", "beer", 250, 650, "tg_beer_2025", "listed"),
    ("bira-blonde", "Bira 91 Blonde", "beer", 250, 650, "livcheers", "listed"),
    ("budweiser-magnum", "Budweiser Magnum", "beer", 260, 650, "tg_beer_2025", "listed"),
    ("kingfisher-ultra-max", "Kingfisher Ultra Max", "beer", 260, 650, "tg_beer_2025", "listed"),
    ("tuborg-classic", "Tuborg Classic", "beer", 260, 650, "livcheers", "listed"),
    ("heineken", "Heineken", "beer", 270, 650, "tg_beer_2025", "listed"),
    ("kingfisher-ultra-witbier", "Kingfisher Ultra Witbier", "beer", 370, 650, "tg_beer_2025", "listed"),
    ("bira-white", "Bira 91 White", "beer", 460, 650, "livcheers", "listed"),
    ("corona", "Corona Extra", "beer", 250, 330, "tg_beer_2025", "listed"),
    ("hoegaarden", "Hoegaarden", "beer", 270, 330, "tg_beer_2025", "listed"),
    # Rum
    ("mcdowells-celebration", "McDowell's Celebration", "rum", 560, 750, "livcheers", "listed"),
    ("contessa", "Contessa", "rum", 680, 750, "tsbcl_2025", "listed"),
    ("old-monk", "Old Monk XXX", "rum", 720, 750, "livcheers", "listed"),
    ("captain-morgan", "Captain Morgan", "rum", 720, 750, "livcheers", "listed"),
    ("hercules", "Hercules XXX", "rum", 720, 750, "livcheers", "listed"),
    ("bacardi-black", "Bacardi Black", "rum", 760, 750, "livcheers", "listed"),
    ("bacardi-gold", "Bacardi Gold", "rum", 1310, 750, "livcheers", "listed"),
    ("bacardi-white", "Bacardi White", "rum", 1320, 750, "livcheers", "listed"),
    ("old-monk-legend", "Old Monk The Legend", "rum", 1400, 750, "livcheers", "listed"),
    # Vodka
    ("romanov", "Romanov", "vodka", 680, 750, "livcheers", "listed"),
    ("white-mischief", "White Mischief", "vodka", 680, 750, "livcheers", "listed"),
    ("magic-moments", "Magic Moments", "vodka", 840, 750, "livcheers", "listed"),
    ("magic-moments-verve", "Magic Moments Verve", "vodka", 1190, 750, "livcheers", "listed"),
    ("smirnoff", "Smirnoff", "vodka", 1200, 750, "livcheers", "listed"),
    ("absolut", "Absolut", "vodka", 2500, 750, "livcheers", "listed"),
    ("ketel-one", "Ketel One", "vodka", 2820, 750, "livcheers", "listed"),
    ("grey-goose", "Grey Goose", "vodka", 4140, 750, "livcheers", "listed"),
    # Gin
    ("greater-than", "Greater Than", "gin", 1920, 750, "livcheers", "listed"),
    ("tanqueray", "Tanqueray", "gin", 1950, 750, "livcheers", "listed"),
    ("beefeater", "Beefeater", "gin", 2300, 750, "livcheers", "listed"),
    ("stranger-sons", "Stranger & Sons", "gin", 2450, 700, "livcheers", "listed"),
    ("bombay-sapphire", "Bombay Sapphire", "gin", 2490, 750, "livcheers", "listed"),
    ("gordons", "Gordon's", "gin", 2670, 750, "livcheers", "listed"),
    # Wine
    ("sula-chenin", "Sula Chenin Blanc", "wine", 665, 750, "sula_hyd", "listed"),
    ("sula-shiraz", "Sula Cabernet Shiraz", "wine", 670, 750, "sula_hyd", "listed"),
    ("sula-sauvignon", "Sula Sauvignon Blanc", "wine", 690, 750, "sula_hyd", "listed"),
    ("fratelli", "Fratelli Classic Shiraz", "wine", 870, 750, "tsbcl_2025", "listed"),
    ("sula-dindori", "Sula Dindori Reserve Shiraz", "wine", 1115, 750, "sula_hyd", "listed"),
    ("jacobs-creek", "Jacob's Creek Shiraz Cabernet", "wine", 1235, 750, "tsbcl_2025", "listed"),
    # Brandy
    ("honey-bee", "Honey Bee", "brandy", 560, 750, "livcheers", "listed"),
    ("mansion-house", "Mansion House", "brandy", 880, 750, "livcheers", "listed"),
    ("morpheus-xo", "Morpheus XO", "brandy", 1140, 750, "livcheers", "listed"),
    ("morpheus", "Morpheus", "brandy", 1240, 750, "livcheers", "listed"),
    # Tequila
    ("camino-real", "Camino Real Blanco", "tequila", 1650, 750, "livcheers", "listed"),
    ("camino-real-gold", "Camino Real Gold", "tequila", 2890, 750, "livcheers", "listed"),
    ("jose-cuervo", "Jose Cuervo Especial Silver", "tequila", 4190, 750, "livcheers", "listed"),
    ("don-julio-blanco", "Don Julio Blanco", "tequila", 11890, 750, "livcheers", "listed"),
    ("patron-silver", "Patrón Silver", "tequila", 12380, 750, "livcheers", "listed"),
    # Breezer & ready-to-drink — 275 ml
    ("bacardi-breezer", "Bacardi Breezer", "rtd", 130, 275, "livcheers", "listed"),
    ("breezer-lemonade", "Breezer Lemonade", "rtd", 150, 275, "livcheers", "listed"),
    ("bacardi-plus", "Bacardi Plus", "rtd", 220, 275, "livcheers", "listed"),
]

CIGARETTES = [
    # (item_id, name, tier, pack_price, sticks, source, confidence)
    ("marlboro", "Marlboro Red", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("marlboro-advance", "Marlboro Advance", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("marlboro-gold", "Marlboro Gold", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("marlboro-fine-touch", "Marlboro Fine Touch", "Premium", 195, 10, "instamart_hyd", "listed"),
    ("benson-hedges", "Benson & Hedges", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("state-express-555", "State Express 555", "Premium", 480, 20, "eden_itc", "listed"),
    ("india-kings", "India Kings", "Premium", 500, 20, "eden_itc", "listed"),
    ("classic", "Classic Milds", "Premium", 240, 10, "instamart_hyd", "listed"),
    ("classic-regular", "Classic Regular", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("classic-ice-burst", "Classic Ice Burst", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("classic-double-burst", "Classic Double Burst", "Premium", 480, 20, "instamart_hyd", "listed"),
    ("classic-verve", "Classic Verve", "Premium", 312, 16, "eden_itc", "listed"),
    ("classic-connect", "Classic Connect", "Premium", 390, 20, "instamart_hyd", "listed"),
    ("american-club", "American Club", "Premium", 190, 10, "instamart_hyd", "listed"),
    ("gold-flake", "Gold Flake Kings", "Popular", 480, 20, "instamart_hyd", "listed"),
    ("lights", "Gold Flake Lights", "Popular", 220, 10, "excise_feb_2026", "listed"),
    ("navy-cut-longs", "Navy Cut Longs", "Popular", 140, 10, "eden_itc", "listed"),
    ("navy-cut", "Navy Cut", "Popular", 120, 10, "excise_feb_2026", "listed"),
    ("gold-flake-indie-mint", "Gold Flake Indie Mint", "Popular", 115, 10, "instamart_hyd", "listed"),
    ("gold-flake-neo-smart", "Gold Flake Neo Smart", "Popular", 95, 10, "instamart_hyd", "listed"),
    ("flake-special", "Flake Special", "Value", 88, 10, "eden_itc", "listed"),
    ("four-square", "Four Square", "Value", 80, 10, "excise_feb_2026", "listed"),
    ("red-white", "Red & White", "Value", 90, 10, "estimate_feb_2026", "estimate"),
    ("total", "Total", "Value", 80, 10, "estimate_feb_2026", "estimate"),
    ("cavanders", "Cavanders", "Value", 80, 10, "estimate_feb_2026", "estimate"),
    ("capstan", "Capstan", "Value", 70, 10, "estimate_feb_2026", "estimate"),
    ("bristol", "Bristol", "Value", 70, 10, "estimate_feb_2026", "estimate"),
    ("scissors", "Scissors", "Value", 70, 10, "estimate_feb_2026", "estimate"),
    ("charms", "Charms", "Value", 70, 10, "estimate_feb_2026", "estimate"),
    ("beedi", "Beedi", "Value", 30, 25, "estimate_local", "estimate"),
]
