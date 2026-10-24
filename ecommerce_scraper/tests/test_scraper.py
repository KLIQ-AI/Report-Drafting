from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper import _to_float, extract_products  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return (FIX / name).read_text()


def test_jsonld_graph_product():
    [p] = extract_products(load("jsonld_product.html"), "https://www.shop.com/p/1")
    assert p.retailer == "shop.com" and p.method == "jsonld"
    assert (p.name, p.brand, p.sku, p.gtin) == ("Arabica Beans 1kg", "Lavazza", "LV-1000", "8000070012345")
    assert (p.price, p.list_price, p.currency, p.availability) == (18.99, 22.5, "EUR", "InStock")
    assert (p.rating, p.review_count) == (4.6, 1284)
    assert p.image == "https://www.shop.com/img/beans.jpg"
    assert p.extra["seller"] == "Example Market"


def test_product_group_variants_inherit_parent():
    ps = extract_products(load("variants.html"), "https://shop.se/shoe")
    assert [p.sku for p in ps] == ["RS-42-BLK", "RS-43-BLK"]
    assert all(p.name == "Runner Shoe" and p.brand == "Acme" and p.review_count == 88 for p in ps)
    assert ps[0].price == 1299.0 and ps[0].availability == "OutOfStock"
    assert ps[1].price == 1199.0
    assert ps[0].variant == "Black / 42"


def test_meta_fallback():
    [p] = extract_products(load("meta_only.html"), "https://kettles.com/k")
    assert p.method == "meta" and p.name == "Steel Kettle"
    assert (p.price, p.currency) == (39.95, "USD")


def test_non_product_page():
    assert extract_products("<html><title>Home</title></html>", "https://a.com") == []


def test_price_parsing():
    assert _to_float("1.234,56 €") == 1234.56
    assert _to_float("$1,234.56") == 1234.56
    assert _to_float("12,5") == 12.5
    assert _to_float("1,299") == 1299.0
