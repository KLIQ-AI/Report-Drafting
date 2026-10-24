#!/usr/bin/env python3
"""Retail e-commerce product scraper.

Pulls structured product data (name, brand, price, availability, ratings,
GTIN/SKU, images...) from online retailers using three strategies, in order
of reliability:

  1. Shopify catalog API  -> /products.json (whole catalog, no HTML parsing)
  2. schema.org JSON-LD   -> the <script type="application/ld+json"> block
                             most retailers embed for Google Shopping / SEO
  3. Meta tag fallback    -> OpenGraph / product:price:* / microdata itemprop

Discovery of product URLs is done from sitemaps (robots.txt -> sitemap.xml)
or by following links from category/listing pages.

The scraper is polite by default: it honours robots.txt, rate-limits per
request and identifies itself with a configurable User-Agent.

Examples
--------
  # Single product pages
  python scraper.py urls https://shop.example.com/p/123 https://...

  # Entire Shopify store catalog
  python scraper.py shopify allbirds.com

  # Discover products from a retailer's sitemap (filter by URL pattern)
  python scraper.py sitemap https://www.example.com --pattern "/product/" --limit 200

  # Crawl a category page and scrape the products it links to
  python scraper.py crawl https://www.example.com/c/coffee --pattern "/p/" --limit 50

  # JS-heavy sites: render pages with headless Chromium (needs playwright)
  python scraper.py urls https://... --render
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from urllib import robotparser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("ecom-scraper")

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; RetailDataBot/1.0; +https://example.com/bot)"
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Product:
    source_url: str
    retailer: str
    scraped_at: str
    method: str  # shopify | jsonld | meta
    name: str | None = None
    brand: str | None = None
    sku: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    category: str | None = None
    price: float | None = None
    list_price: float | None = None  # pre-discount / "compare at" price
    currency: str | None = None
    availability: str | None = None  # InStock | OutOfStock | ...
    rating: float | None = None
    review_count: int | None = None
    variant: str | None = None
    image: str | None = None
    description: str | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def csv_fields(cls) -> list[str]:
        return [f.name for f in fields(cls)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    # Handle "1.234,56" (EU) and "1,234.56" (US) formats
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _clean_availability(value) -> str | None:
    if not value:
        return None
    # "https://schema.org/InStock" -> "InStock"
    return str(value).rstrip("/").rsplit("/", 1)[-1]


def _text(value, limit: int = 500) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id")
    if isinstance(value, list):
        value = ", ".join(str(_text(v)) for v in value if v)
    s = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return s[:limit] if s else None


# --------------------------------------------------------------------------- #
# HTTP client (polite: robots.txt, delay, retries)
# --------------------------------------------------------------------------- #
class Fetcher:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        delay: float = 1.5,
        timeout: float = 20,
        respect_robots: bool = True,
        render: bool = False,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
            }
        )
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.render = render
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_request = 0.0
        self._browser = None

    # -- robots.txt -------------------------------------------------------- #
    def robots(self, url: str) -> robotparser.RobotFileParser | None:
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if root not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(root + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[root] = rp
        return self._robots[root]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self.robots(url)
        return rp is None or rp.can_fetch(self.user_agent, url)

    def sitemaps_for(self, url: str) -> list[str]:
        rp = self.robots(url)
        found = (rp.site_maps() if rp else None) or []
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        return found or [root + "/sitemap.xml"]

    # -- fetching ---------------------------------------------------------- #
    def _throttle(self):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait + random.uniform(0, self.delay * 0.3))
        self._last_request = time.monotonic()

    def get(self, url: str, retries: int = 3) -> requests.Response | None:
        if not self.allowed(url):
            log.warning("Blocked by robots.txt: %s", url)
            return None
        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("Request error (%s/%s) %s: %s", attempt, retries, url, e)
                time.sleep(2**attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                backoff = int(r.headers.get("Retry-After", 2**attempt * 2))
                log.warning("HTTP %s on %s, backing off %ss", r.status_code, url, backoff)
                time.sleep(min(backoff, 60))
                continue
            if not r.ok:
                log.warning("HTTP %s on %s", r.status_code, url)
                return None
            return r
        return None

    def get_html(self, url: str) -> str | None:
        if self.render:
            return self._render(url)
        r = self.get(url)
        return r.text if r is not None else None

    def _render(self, url: str) -> str | None:
        if not self.allowed(url):
            log.warning("Blocked by robots.txt: %s", url)
            return None
        if self._browser is None:
            from playwright.sync_api import sync_playwright  # optional dependency

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self._page = self._browser.new_page(user_agent=self.user_agent)
        self._throttle()
        try:
            self._page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            return self._page.content()
        except Exception as e:  # playwright raises its own error types
            log.warning("Render failed %s: %s", url, e)
            return None

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._pw.stop()


# --------------------------------------------------------------------------- #
# Extraction: JSON-LD, meta tags
# --------------------------------------------------------------------------- #
def _iter_jsonld_nodes(soup: BeautifulSoup) -> Iterator[dict]:
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            # Some sites put trailing commas / multiple objects; try a lenient pass
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw.strip()))
            except json.JSONDecodeError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                for key in ("@graph", "itemListElement", "item", "hasVariant", "mainEntity"):
                    if key in node:
                        stack.append(node[key])


def _is_type(node: dict, *types: str) -> bool:
    t = node.get("@type")
    t = t if isinstance(t, list) else [t]
    return any(x in types for x in t)


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _offer_fields(offers) -> dict:
    """Normalise Offer / AggregateOffer / list of offers into price fields."""
    offers = offers if isinstance(offers, list) else [offers]
    offers = [o for o in offers if isinstance(o, dict)]
    if not offers:
        return {}
    o = offers[0]
    if _is_type(o, "AggregateOffer") and not o.get("price"):
        price = o.get("lowPrice")
    else:
        price = o.get("price")
    spec = _first(o.get("priceSpecification"))
    if price is None and isinstance(spec, dict):
        price = spec.get("price")
    currency = o.get("priceCurrency") or (spec or {}).get("priceCurrency")
    list_price = None
    specs = o.get("priceSpecification")
    for s in specs if isinstance(specs, list) else [specs]:
        if isinstance(s, dict) and "ListPrice" in str(s.get("priceType", "")):
            list_price = _to_float(s.get("price"))
    return {
        "price": _to_float(price),
        "list_price": list_price,
        "currency": currency,
        "availability": _clean_availability(o.get("availability")),
        "extra": {"seller": _text(o.get("seller"))} if o.get("seller") else {},
    }


def product_from_jsonld(node: dict, url: str, retailer: str) -> Product:
    rating = node.get("aggregateRating") or {}
    image = _first(node.get("image"))
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    gtin = next(
        (node.get(k) for k in ("gtin13", "gtin", "gtin12", "gtin14", "gtin8") if node.get(k)),
        None,
    )
    offer = _offer_fields(node.get("offers"))
    extra = offer.pop("extra", {})
    return Product(
        source_url=node.get("url") and urljoin(url, node["url"]) or url,
        retailer=retailer,
        scraped_at=_now(),
        method="jsonld",
        name=_text(node.get("name"), 300),
        brand=_text(node.get("brand"), 120),
        sku=_text(node.get("sku"), 100),
        gtin=_text(gtin, 30),
        mpn=_text(node.get("mpn"), 100),
        category=_text(node.get("category"), 200),
        rating=_to_float(rating.get("ratingValue")),
        review_count=_to_int(rating.get("reviewCount") or rating.get("ratingCount")),
        variant=_text(
            " / ".join(
                str(node[k]) for k in ("color", "size", "material") if node.get(k)
            )
        ),
        image=urljoin(url, image) if isinstance(image, str) else None,
        description=_text(node.get("description")),
        extra=extra,
        **offer,
    )


def products_from_jsonld(soup: BeautifulSoup, url: str, retailer: str) -> list[Product]:
    out: list[Product] = []
    for node in _iter_jsonld_nodes(soup):
        if _is_type(node, "Product", "IndividualProduct", "ProductModel"):
            out.append(product_from_jsonld(node, url, retailer))
        elif _is_type(node, "ProductGroup") and not node.get("hasVariant"):
            out.append(product_from_jsonld(node, url, retailer))
    # Variants inherit missing fields (brand, name...) from their ProductGroup
    groups = [n for n in _iter_jsonld_nodes(soup) if _is_type(n, "ProductGroup")]
    if groups:
        parent = product_from_jsonld(groups[0], url, retailer)
        for p in out:
            for k in ("name", "brand", "category", "description", "image", "rating", "review_count"):
                if getattr(p, k) is None:
                    setattr(p, k, getattr(parent, k))
    return out


def product_from_meta(soup: BeautifulSoup, url: str, retailer: str) -> Product | None:
    def meta(*names: str) -> str | None:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
            tag = soup.find(attrs={"itemprop": n})
            if tag:
                return (tag.get("content") or tag.get_text(" ", strip=True)) or None
        return None

    price = meta("product:price:amount", "og:price:amount", "price")
    name = meta("og:title", "name", "twitter:title")
    if not price and not (meta("og:type") or "").lower().startswith("product"):
        return None  # not a product page
    return Product(
        source_url=meta("og:url") or url,
        retailer=retailer,
        scraped_at=_now(),
        method="meta",
        name=name or (soup.title.get_text(strip=True) if soup.title else None),
        brand=meta("product:brand", "brand"),
        sku=meta("product:retailer_item_id", "sku"),
        gtin=meta("gtin13", "gtin", "product:gtin"),
        price=_to_float(price),
        currency=meta("product:price:currency", "og:price:currency", "priceCurrency"),
        availability=_clean_availability(meta("product:availability", "og:availability", "availability")),
        image=meta("og:image", "image"),
        description=_text(meta("og:description", "description")),
    )


def extract_products(html: str, url: str) -> list[Product]:
    retailer = urlparse(url).netloc.removeprefix("www.")
    soup = BeautifulSoup(html, "html.parser")
    products = products_from_jsonld(soup, url, retailer)
    if not products:
        p = product_from_meta(soup, url, retailer)
        products = [p] if p else []
    return products


# --------------------------------------------------------------------------- #
# Strategy: Shopify
# --------------------------------------------------------------------------- #
def scrape_shopify(fetcher: Fetcher, store: str, limit: int | None = None) -> Iterator[Product]:
    base = store if store.startswith("http") else f"https://{store}"
    base = base.rstrip("/")
    retailer = urlparse(base).netloc.removeprefix("www.")
    count, page = 0, 1
    while True:
        r = fetcher.get(f"{base}/products.json?limit=250&page={page}")
        if r is None:
            log.error("Could not read %s/products.json (not Shopify, or blocked)", base)
            return
        try:
            items = r.json().get("products", [])
        except ValueError:
            log.error("%s/products.json did not return JSON - probably not a Shopify store", base)
            return
        if not items:
            return
        for item in items:
            image = (item.get("images") or [{}])[0].get("src")
            for v in item.get("variants", []):
                yield Product(
                    source_url=f"{base}/products/{item['handle']}?variant={v['id']}",
                    retailer=retailer,
                    scraped_at=_now(),
                    method="shopify",
                    name=item.get("title"),
                    brand=item.get("vendor"),
                    sku=v.get("sku") or None,
                    gtin=v.get("barcode") or None,
                    category=item.get("product_type") or None,
                    price=_to_float(v.get("price")),
                    list_price=_to_float(v.get("compare_at_price")),
                    currency=None,  # not exposed by products.json; see store settings
                    availability="InStock" if v.get("available") else "OutOfStock",
                    variant=v.get("title") if v.get("title") != "Default Title" else None,
                    image=(v.get("featured_image") or {}).get("src") or image,
                    description=_text(item.get("body_html")),
                    extra={
                        "tags": item.get("tags"),
                        "published_at": item.get("published_at"),
                        "updated_at": v.get("updated_at"),
                    },
                )
                count += 1
                if limit and count >= limit:
                    return
        if len(items) < 250:  # last page
            return
        page += 1


# --------------------------------------------------------------------------- #
# Discovery: sitemaps & link crawling
# --------------------------------------------------------------------------- #
def iter_sitemap_urls(fetcher: Fetcher, sitemap_url: str, pattern: re.Pattern | None,
                      seen: set[str] | None = None) -> Iterator[str]:
    seen = seen if seen is not None else set()
    if sitemap_url in seen:
        return
    seen.add(sitemap_url)
    r = fetcher.get(sitemap_url)
    if r is None:
        return
    content = r.content
    if sitemap_url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except OSError:
            pass
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        log.warning("Could not parse sitemap %s", sitemap_url)
        return
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    children = [e.text.strip() for e in root.findall("sm:sitemap/sm:loc", ns) if e.text]
    if children:
        # Product sitemaps first: they are usually named "*product*"
        children.sort(key=lambda u: "product" not in u.lower())
        for child in children:
            yield from iter_sitemap_urls(fetcher, child, pattern, seen)
        return
    for e in root.findall("sm:url/sm:loc", ns):
        loc = (e.text or "").strip()
        if loc and (pattern is None or pattern.search(loc)):
            yield loc


def iter_listing_links(fetcher: Fetcher, start_url: str, pattern: re.Pattern | None,
                       max_pages: int) -> Iterator[str]:
    """Follow pagination on a category page and yield product links."""
    host = urlparse(start_url).netloc
    queue, visited, emitted = [start_url], set(), set()
    while queue and len(visited) < max_pages:
        page_url = queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        html = fetcher.get_html(page_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            link = urljoin(page_url, a["href"]).split("#")[0]
            if urlparse(link).netloc != host:
                continue
            if pattern and pattern.search(link):
                if link not in emitted:
                    emitted.add(link)
                    yield link
            elif a.get("rel") == ["next"] or re.search(r"[?&](page|p|pg)=\d+", link):
                queue.append(link)


def scrape_urls(fetcher: Fetcher, urls: Iterable[str], limit: int | None) -> Iterator[Product]:
    count = 0
    for url in urls:
        html = fetcher.get_html(url)
        if not html:
            continue
        products = extract_products(html, url)
        if not products:
            log.info("No product data found on %s", url)
        for p in products:
            yield p
            count += 1
            if limit and count >= limit:
                return


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
class Writer:
    def __init__(self, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path = out.with_suffix(".csv")
        self.jsonl_path = out.with_suffix(".jsonl")
        self._csv_f = self.csv_path.open("w", newline="", encoding="utf-8")
        self._jsonl_f = self.jsonl_path.open("w", encoding="utf-8")
        self._csv = csv.DictWriter(self._csv_f, fieldnames=Product.csv_fields())
        self._csv.writeheader()
        self.count = 0

    def write(self, p: Product):
        row = asdict(p)
        self._jsonl_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        row["extra"] = json.dumps(row["extra"], ensure_ascii=False) if row["extra"] else ""
        self._csv.writerow(row)
        self.count += 1
        # Flush as we go so long runs are not lost on interrupt
        self._csv_f.flush()
        self._jsonl_f.flush()

    def close(self):
        self._csv_f.close()
        self._jsonl_f.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--out", default="output/products",
                        help="Output path without extension (writes .csv and .jsonl)")
    common.add_argument("--limit", type=int, help="Stop after N products")
    common.add_argument("--delay", type=float, default=1.5, help="Seconds between requests (default 1.5)")
    common.add_argument("--user-agent", default=DEFAULT_UA)
    common.add_argument("--render", action="store_true",
                        help="Render pages with headless Chromium (for JS-only sites; needs playwright)")
    common.add_argument("--ignore-robots", action="store_true",
                        help="Do not check robots.txt (only for sites you own or are authorised to scrape)")
    common.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("urls", parents=[common], help="Scrape specific product page URLs")
    s.add_argument("urls", nargs="*", help="Product URLs")
    s.add_argument("-f", "--file", help="Text file with one URL per line")

    s = sub.add_parser("shopify", parents=[common], help="Dump a Shopify store's catalog")
    s.add_argument("store", help="Store domain, e.g. allbirds.com")

    s = sub.add_parser("sitemap", parents=[common], help="Discover products via sitemap.xml")
    s.add_argument("site", help="Site root or a direct sitemap URL")
    s.add_argument("--pattern", help="Regex product URLs must match, e.g. '/product/|/p/'")

    s = sub.add_parser("crawl", parents=[common], help="Crawl category/listing pages for products")
    s.add_argument("start_url", help="Category or search results URL")
    s.add_argument("--pattern", required=True, help="Regex that identifies product links, e.g. '/p/'")
    s.add_argument("--max-pages", type=int, default=20, help="Max listing pages to visit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    fetcher = Fetcher(
        user_agent=args.user_agent,
        delay=args.delay,
        respect_robots=not args.ignore_robots,
        render=args.render,
    )
    pattern = re.compile(args.pattern) if getattr(args, "pattern", None) else None

    if args.mode == "urls":
        urls = list(args.urls)
        if args.file:
            urls += [l.strip() for l in Path(args.file).read_text().splitlines() if l.strip()]
        if not urls:
            print("No URLs given", file=sys.stderr)
            return 2
        products = scrape_urls(fetcher, urls, args.limit)
    elif args.mode == "shopify":
        products = scrape_shopify(fetcher, args.store, args.limit)
    elif args.mode == "sitemap":
        site = args.site if args.site.startswith("http") else f"https://{args.site}"
        roots = [site] if site.endswith((".xml", ".xml.gz")) else fetcher.sitemaps_for(site)
        seen: set[str] = set()
        urls = (u for root in roots for u in iter_sitemap_urls(fetcher, root, pattern, seen))
        products = scrape_urls(fetcher, urls, args.limit)
    else:  # crawl
        urls = iter_listing_links(fetcher, args.start_url, pattern, args.max_pages)
        products = scrape_urls(fetcher, urls, args.limit)

    writer = Writer(Path(args.out))
    try:
        for product in products:
            writer.write(product)
            log.info("[%d] %s | %s %s | %s", writer.count, (product.name or "?")[:60],
                     product.price, product.currency or "", product.availability or "")
    except KeyboardInterrupt:
        log.warning("Interrupted - partial results saved")
    finally:
        writer.close()
        fetcher.close()
    log.info("Saved %d products to %s and %s", writer.count, writer.csv_path, writer.jsonl_path)
    return 0 if writer.count else 1


if __name__ == "__main__":
    sys.exit(main())
