# Retail e-commerce scraper

Pulls structured product data from online retailers into CSV and JSONL. Each row has the product name, brand, SKU, GTIN/EAN, price, list price, currency, availability, rating, review count, variant, image and description.

## Setup
```bash
pip install -r requirements.txt
# Optional, for JavaScript-only sites:
pip install playwright && playwright install chromium
```

## Usage
| Goal | Command |
|---|---|
| Scrape specific product pages | `python scraper.py urls URL1 URL2` or `-f urls.txt` |
| Download a Shopify store's whole catalog | `python scraper.py shopify allbirds.com` |
| Find products through the site's sitemap | `python scraper.py sitemap https://www.retailer.com --pattern "/product/" --limit 500` |
| Crawl a category page and its pagination | `python scraper.py crawl https://www.retailer.com/c/coffee --pattern "/p/"` |

Common flags: `-o output/run1` (writes `run1.csv` and `run1.jsonl`), `--limit N`, `--delay 1.5`, `--render` (headless browser), `-v`.

## How it works
1. **Shopify** reads `/products.json`, which returns clean data for every variant. Around a quarter of DTC brands run on Shopify.
2. **schema.org JSON-LD** reads the `Product` markup that retailers publish for Google Shopping. It handles `@graph` and `ProductGroup`/`hasVariant`, and parses EU and US price formats.
3. **Meta tags** (OpenGraph `product:price:*`, microdata) are the fallback.

## Good practice
- The scraper honours `robots.txt` by default. Use `--ignore-robots` only on sites you own or are authorised to scrape.
- Keep `--delay` at 1s or more. Check each retailer's Terms of Service before running at scale.
- Large marketplaces such as Amazon and Walmart block bots actively. For those, an official API (Amazon PA-API, retailer affiliate feeds) or a licensed data provider is usually the better route.

## Tests
`python -m pytest -q tests`
